use super::*;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

/// A tiny HTTP server that records each request body and answers `status`.
async fn mock(status: u16) -> (String, Arc<Mutex<Vec<serde_json::Value>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}/hook/secret-token", listener.local_addr().unwrap());
    let got: Arc<Mutex<Vec<serde_json::Value>>> = Default::default();
    let rec = got.clone();
    tokio::spawn(async move {
        loop {
            let Ok((mut sock, _)) = listener.accept().await else { return };
            let rec = rec.clone();
            tokio::spawn(async move {
                let mut buf = Vec::new();
                let mut chunk = [0u8; 4096];
                loop {
                    let n = sock.read(&mut chunk).await.unwrap_or(0);
                    if n == 0 {
                        return;
                    }
                    buf.extend_from_slice(&chunk[..n]);
                    let text = String::from_utf8_lossy(&buf).to_string();
                    if let Some(end) = text.find("\r\n\r\n") {
                        let len = text[..end]
                            .lines()
                            .find_map(|l| {
                                let l = l.to_ascii_lowercase();
                                l.strip_prefix("content-length:").map(|v| v.trim().parse::<usize>().unwrap_or(0))
                            })
                            .unwrap_or(0);
                        if buf.len() >= end + 4 + len {
                            let body = &buf[end + 4..end + 4 + len];
                            if let Ok(v) = serde_json::from_slice(body) {
                                rec.lock().unwrap().push(v);
                            }
                            let reply = format!("HTTP/1.1 {status} X\r\ncontent-length: 0\r\nconnection: close\r\n\r\n");
                            let _ = sock.write_all(reply.as_bytes()).await;
                            return;
                        }
                    }
                }
            });
        }
    });
    (url, got)
}

fn quick(url: &str, format: AlertFormat) -> AlertConfig {
    let mut c = AlertConfig::new(url, format);
    c.batch_wait = Duration::from_millis(50);
    c
}

async fn wait_for(got: &Arc<Mutex<Vec<serde_json::Value>>>, n: usize) {
    for _ in 0..100 {
        if got.lock().unwrap().len() >= n {
            return;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

#[tokio::test]
async fn discord_posts_content_and_batches_what_arrives_together() {
    let (url, got) = mock(204).await;
    let sink = AlertSink::spawn(quick(&url, AlertFormat::Discord));
    sink.send(AlertEvent::new(AlertKind::KillSwitch, "kill", "engaged by you"));
    sink.send(AlertEvent::new(AlertKind::FloorHit, "floor:a", "Momentum stopped at its floor"));
    wait_for(&got, 1).await;
    tokio::time::sleep(Duration::from_millis(100)).await;
    let got = got.lock().unwrap();
    assert_eq!(got.len(), 1, "one post for both");
    let c = got[0]["content"].as_str().unwrap();
    assert!(c.starts_with("**Pythia**"));
    assert!(c.contains("**Kill switch** engaged by you"));
    assert!(c.contains("**Floor hit** Momentum stopped"));
    assert!(got[0].get("text").is_none());
}

#[tokio::test]
async fn slack_posts_text() {
    let (url, got) = mock(200).await;
    let sink = AlertSink::spawn(quick(&url, AlertFormat::Slack));
    sink.send(AlertEvent::new(AlertKind::DataStale, "stale", "quotes stale for 11 min"));
    wait_for(&got, 1).await;
    let got = got.lock().unwrap();
    assert_eq!(got[0]["text"].as_str().unwrap(), "*Pythia*\n*Market data stale* quotes stale for 11 min");
    assert!(got[0].get("content").is_none());
}

#[tokio::test]
async fn the_same_key_is_sent_once_inside_the_window() {
    let (url, got) = mock(204).await;
    let sink = AlertSink::spawn(quick(&url, AlertFormat::Discord));
    for _ in 0..3 {
        sink.send(AlertEvent::new(AlertKind::OrderRejects, "rejects:demo", "4 in a row"));
        tokio::time::sleep(Duration::from_millis(120)).await;
    }
    sink.send(AlertEvent::new(AlertKind::KillSwitch, "kill", "engaged"));
    wait_for(&got, 2).await;
    tokio::time::sleep(Duration::from_millis(100)).await;
    let got = got.lock().unwrap();
    assert_eq!(got.len(), 2);
    assert!(got[1]["content"].as_str().unwrap().contains("Kill switch"));
}

#[tokio::test]
async fn the_hourly_cap_holds_back_and_counts() {
    let (url, got) = mock(204).await;
    let mut cfg = quick(&url, AlertFormat::Discord);
    cfg.max_per_hour = 1;
    let sink = AlertSink::spawn(cfg);
    sink.send(AlertEvent::new(AlertKind::KillSwitch, "a", "one"));
    wait_for(&got, 1).await;
    tokio::time::sleep(Duration::from_millis(100)).await;
    sink.send(AlertEvent::new(AlertKind::KillSwitch, "b", "two"));
    tokio::time::sleep(Duration::from_millis(200)).await;
    assert_eq!(got.lock().unwrap().len(), 1, "the second post waits for the hour");
}

#[tokio::test]
async fn a_failing_or_dead_webhook_never_blocks_the_sender() {
    let (url, _got) = mock(500).await;
    let sink = AlertSink::spawn(quick(&url, AlertFormat::Discord));
    let t = std::time::Instant::now();
    for i in 0..500 {
        sink.send(AlertEvent::new(AlertKind::OrderRejects, format!("k{i}"), "x"));
    }
    // Nothing listens on port 9 on a test box: connection refused.
    let dead = AlertSink::spawn(quick("http://127.0.0.1:9/hook", AlertFormat::Discord));
    for i in 0..500 {
        dead.send(AlertEvent::new(AlertKind::OrderRejects, format!("k{i}"), "x"));
    }
    assert!(t.elapsed() < Duration::from_millis(200), "sending only queues");
}

#[test]
fn throttle_window_and_cap() {
    let mut t = Throttle::new(Duration::from_secs(60), 2);
    assert!(t.fresh("k", 0));
    assert!(!t.fresh("k", 59_000));
    assert!(t.fresh("k", 60_000));
    assert!(t.may_post(0));
    assert!(t.may_post(1));
    assert!(!t.may_post(2));
    assert!(t.may_post(3_600_000));
}

#[test]
fn config_from_env_and_the_secret_stays_out_of_debug() {
    let env = |pairs: &'static [(&'static str, &'static str)]| {
        move |k: &str| pairs.iter().find(|(n, _)| *n == k).map(|(_, v)| v.to_string())
    };
    assert!(AlertConfig::from_lookup(env(&[])).is_none());
    assert!(AlertConfig::from_lookup(env(&[("PYTHIA_ALERT_WEBHOOK", "  ")])).is_none());
    let c = AlertConfig::from_lookup(env(&[
        ("PYTHIA_ALERT_WEBHOOK", "https://example.invalid/hook/very-secret"),
        ("PYTHIA_ALERT_FORMAT", "Slack"),
        ("PYTHIA_ALERT_DEDUP_MIN", "5"),
        ("PYTHIA_ALERT_MAX_PER_HOUR", "7"),
    ]))
    .unwrap();
    assert_eq!(c.format, AlertFormat::Slack);
    assert_eq!(c.dedup, Duration::from_secs(300));
    assert_eq!(c.max_per_hour, 7);
    assert!(!format!("{c:?}").contains("very-secret"));
    let d = AlertConfig::from_lookup(env(&[("PYTHIA_ALERT_WEBHOOK", "https://x.invalid"), ("PYTHIA_ALERT_FORMAT", "teams")]))
        .unwrap();
    assert_eq!(d.format, AlertFormat::Discord);
}

#[test]
fn bodies_are_truncated_per_format() {
    let long = "x".repeat(5000);
    let d = AlertFormat::Discord.body(&long);
    assert!(d["content"].as_str().unwrap().chars().count() <= 1901);
    let s = AlertFormat::Slack.body(&long);
    assert!(s["text"].as_str().unwrap().chars().count() <= 3001);
}

#[test]
fn drift_mutes_once_and_says_when_it_clears() {
    use crate::ml::{FeatureDrift, MlStatus};
    use pythia_ml::drift::DriftLevel;
    let mut st = MlStatus::default();
    let feat = |level| FeatureDrift { feature: "rv_24h".into(), psi: 0.4, outside_pct: 12.0, level };
    st.drift = vec![feat(DriftLevel::Stable)];
    let mut w = DriftWatch::default();
    assert!(w.check(&st).is_empty());
    st.drift = vec![feat(DriftLevel::Drift)];
    let on = w.check(&st);
    assert_eq!(on.len(), 1);
    assert_eq!(on[0].kind, AlertKind::ModelDrift);
    assert!(on[0].text.contains("volatility model muted"), "{}", on[0].text);
    assert!(on[0].text.contains("rv_24h 12 % outside"));
    assert!(w.check(&st).is_empty(), "still muted: no repeat");
    st.drift = vec![feat(DriftLevel::Shift)];
    let off = w.check(&st);
    assert_eq!(off.len(), 1);
    assert!(off[0].text.contains("back in the trained range"));
}
