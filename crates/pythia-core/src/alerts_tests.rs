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

/// A log with quiet hours off, so a test does not depend on the time of day
/// (the default quiet hours, 23:00 to 07:00 Berlin, hold most events back).
fn awake_log() -> AlertLog {
    let log = AlertLog::default();
    log.set_settings(AlertSettings { quiet_hours: QuietHours { enabled: false, ..Default::default() }, ..Default::default() });
    log
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
    let sink = AlertSink::spawn_with_log(quick(&url, AlertFormat::Discord), awake_log());
    sink.send(AlertEvent::new(AlertKind::KillSwitch, "kill", "engaged by you"));
    sink.send(AlertEvent::new(AlertKind::FloorHit, "floor:a", "Momentum stopped at its floor"));
    wait_for(&got, 1).await;
    tokio::time::sleep(Duration::from_millis(100)).await;
    let got = got.lock().unwrap();
    assert_eq!(got.len(), 1, "one post for both");
    let c = got[0]["content"].as_str().unwrap();
    assert!(c.starts_with("**🚨 Kill switch**\nEngaged by you"), "{c}");
    assert!(c.contains("**🛑 Floor hit**\nMomentum stopped"));
    assert!(c.ends_with("*Pythia*"), "the engine's name is the footer");
    assert!(got[0].get("text").is_none());
}

#[tokio::test]
async fn the_partial_fills_of_a_rebalance_go_out_as_one_card() {
    let (url, got) = mock(204).await;
    let mut cfg = quick(&url, AlertFormat::Discord);
    cfg.fill_quiet = Duration::from_millis(300);
    cfg.fill_max = Duration::from_secs(5);
    let sink = AlertSink::spawn_with_log(cfg, awake_log());
    let fill = |i: usize, buy: bool| TradeLine {
        book: "Tranches".into(),
        buy,
        symbol: if i % 2 == 0 { "ETH".into() } else { "BTC".into() },
        qty: 0.1,
        price: 1_000.0,
        fee: 0.1,
        realized: if buy { 0.0 } else { 1.0 },
        rebalance: true,
        mode: "demo".into(),
        experiment: false,
    };
    // Seven fills, each after the sender's own batch window: one card all the same.
    for i in 0..7 {
        sink.send(AlertEvent::trade(format!("f{i}"), fill(i, i < 4)));
        tokio::time::sleep(Duration::from_millis(120)).await;
    }
    assert!(got.lock().unwrap().is_empty(), "still collecting");
    wait_for(&got, 1).await;
    tokio::time::sleep(Duration::from_millis(400)).await;
    let got = got.lock().unwrap();
    assert_eq!(got.len(), 1, "one post: {got:?}");
    let c = got[0]["content"].as_str().unwrap();
    assert!(c.starts_with("**🔁 Rebalance · Tranches**\n7 fills in 4 lines: bought $400.00, sold $300.00."), "{c}");
    assert!(c.contains("Realised  +$3.00") && c.contains("Fees       $0.70"), "{c}");
}

#[tokio::test]
async fn slack_posts_text() {
    let (url, got) = mock(200).await;
    let sink = AlertSink::spawn_with_log(quick(&url, AlertFormat::Slack), awake_log());
    sink.send(AlertEvent::new(AlertKind::DataStale, "stale", "quotes stale for 11 min"));
    wait_for(&got, 1).await;
    let got = got.lock().unwrap();
    assert_eq!(got[0]["text"].as_str().unwrap(), "*📡 Market data stale*\nQuotes stale for 11 min\n_Pythia_");
    assert!(got[0].get("content").is_none());
}

#[tokio::test]
async fn the_same_key_is_sent_once_inside_the_window() {
    let (url, got) = mock(204).await;
    let sink = AlertSink::spawn_with_log(quick(&url, AlertFormat::Discord), awake_log());
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
    let sink = AlertSink::spawn_with_log(cfg, awake_log());
    sink.send(AlertEvent::new(AlertKind::DataStale, "a", "one"));
    wait_for(&got, 1).await;
    tokio::time::sleep(Duration::from_millis(100)).await;
    sink.send(AlertEvent::new(AlertKind::ModelDrift, "b", "two"));
    tokio::time::sleep(Duration::from_millis(200)).await;
    assert_eq!(got.lock().unwrap().len(), 1, "the second post waits for the hour");
    // An urgent alert does not wait.
    sink.send(AlertEvent::new(AlertKind::KillSwitch, "c", "engaged"));
    wait_for(&got, 2).await;
    assert_eq!(got.lock().unwrap().len(), 2, "the kill switch passes the hourly limit");
}

#[tokio::test]
async fn a_failing_or_dead_webhook_never_blocks_the_sender() {
    let (url, _got) = mock(500).await;
    let sink = AlertSink::spawn_with_log(quick(&url, AlertFormat::Discord), awake_log());
    let t = std::time::Instant::now();
    for i in 0..500 {
        sink.send(AlertEvent::new(AlertKind::OrderRejects, format!("k{i}"), "x"));
    }
    // Nothing listens on port 9 on a test box: connection refused.
    let dead = AlertSink::spawn_with_log(quick("http://127.0.0.1:9/hook", AlertFormat::Discord), awake_log());
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

#[test]
fn telegram_comes_from_its_token_and_chat_and_posts_plain_text_with_the_chat_id() {
    let env = |k: &str| match k {
        "PYTHIA_TELEGRAM_BOT_TOKEN" => Some(" 123:abc ".to_string()),
        "PYTHIA_TELEGRAM_CHAT_ID" => Some("4242".to_string()),
        _ => None,
    };
    let c = AlertConfig::from_lookup(env).expect("telegram is configured");
    assert_eq!(c.format, AlertFormat::Telegram);
    assert_eq!(c.url, "https://api.telegram.org/bot123:abc/sendMessage");
    assert!(!format!("{c:?}").contains("123:abc"), "the token never shows in a log line");
    let ev = AlertEvent::new(AlertKind::KillSwitch, "k", "all trading halted");
    let text = compose(&c, &[ev], 0);
    assert_eq!(text, "<b>🚨 Kill switch</b>\nAll trading halted\n<i>Pythia</i>");
    let b = c.body(&text);
    assert_eq!(b["chat_id"], "4242");
    assert_eq!(b["text"], text);
    assert_eq!(b["parse_mode"], "HTML");
    // A token without a chat is not enough, and a webhook wins over both.
    assert!(AlertConfig::from_lookup(|k| (k == "PYTHIA_TELEGRAM_BOT_TOKEN").then(|| "t".to_string())).is_none());
    let both = |k: &str| match k {
        "PYTHIA_ALERT_WEBHOOK" => Some("https://example.invalid/hook".to_string()),
        _ => env(k),
    };
    assert_eq!(AlertConfig::from_lookup(both).unwrap().format, AlertFormat::Discord);
}

async fn wait_log(log: &AlertLog, n: usize) {
    for _ in 0..100 {
        if log.view(now_ms()).recent.len() >= n {
            return;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

#[tokio::test]
async fn every_post_is_recorded_with_todays_counts() {
    let (url, got) = mock(204).await;
    let log = awake_log();
    let sink = AlertSink::spawn_with_log(quick(&url, AlertFormat::Discord), log.clone());
    sink.send(AlertEvent::new(AlertKind::DataStale, "stale", "quotes stale"));
    sink.send(AlertEvent::new(AlertKind::ModelDrift, "drift", "vol model muted"));
    wait_log(&log, 1).await;
    wait_for(&got, 1).await;
    let v = log.view(now_ms());
    assert_eq!(v.recent.len(), 1);
    assert_eq!(v.recent[0].kinds, vec![AlertKind::DataStale, AlertKind::ModelDrift]);
    assert!(v.recent[0].delivered);
    assert!(v.recent[0].error.is_none());
    assert!(v.recent[0].text.contains("Quotes stale"));
    assert_eq!(v.recent[0].title.as_deref(), Some("Market data stale"));
    assert_eq!(v.counts, AlertCounts { sent_today: 1, failed_today: 0, suppressed_today: 0 });
    let json = serde_json::to_value(&v.recent[0]).unwrap();
    assert_eq!(json["kinds"], serde_json::json!(["dataStale", "modelDrift"]));
    assert!(json.get("reason").is_none());
}

#[tokio::test]
async fn a_failed_post_is_recorded_without_the_url_or_token() {
    let (url, _got) = mock(500).await;
    let log = awake_log();
    let sink = AlertSink::spawn_with_log(quick(&url, AlertFormat::Discord), log.clone());
    sink.send(AlertEvent::new(AlertKind::OrderRejects, "r", "4 in a row"));
    wait_log(&log, 1).await;
    let v = log.view(now_ms());
    assert!(!v.recent[0].delivered);
    assert_eq!(v.recent[0].error.as_deref(), Some("HTTP 500"));
    assert_eq!(v.counts.failed_today, 1);

    // Nothing listens on port 9: the connection error says so, never where.
    let mut cfg = quick("http://127.0.0.1:9/bot123456:SECRETTOKEN/sendMessage", AlertFormat::Telegram);
    cfg.chat_id = Some("-1009876543".into());
    let log = awake_log();
    let sink = AlertSink::spawn_with_log(cfg, log.clone());
    let rec = sink.test().await;
    assert!(!rec.delivered);
    let err = rec.error.unwrap();
    assert!(!err.contains("SECRETTOKEN") && !err.contains("127.0.0.1:9") && !err.contains("9876543"), "{err}");
}

#[test]
fn scrub_takes_out_every_secret_part() {
    let mut cfg = AlertConfig::new("https://api.telegram.org/bot123456:SECRETTOKEN/sendMessage", AlertFormat::Telegram);
    cfg.chat_id = Some("-1009876543".into());
    let msg = "error for https://api.telegram.org/bot123456:SECRETTOKEN/sendMessage, token bot123456:SECRETTOKEN, chat -1009876543, HTTP 429";
    let out = scrub(msg, &cfg);
    assert!(!out.contains("SECRETTOKEN") && !out.contains("9876543"), "{out}");
    assert!(out.ends_with("HTTP 429"));
}

#[tokio::test]
async fn muted_events_are_recorded_not_sent_but_the_kill_switch_and_floor_still_go_out() {
    let (url, got) = mock(204).await;
    let log = awake_log();
    log.set_muted_until(now_ms() + 60_000);
    let sink = AlertSink::spawn_with_log(quick(&url, AlertFormat::Discord), log.clone());
    sink.send(AlertEvent::new(AlertKind::DataStale, "stale", "quotes stale"));
    sink.send(AlertEvent::new(AlertKind::KillSwitch, "kill", "engaged"));
    sink.send(AlertEvent::new(AlertKind::FloorHit, "floor", "floor hit"));
    wait_log(&log, 2).await;
    wait_for(&got, 1).await;
    tokio::time::sleep(Duration::from_millis(100)).await;
    let posted = got.lock().unwrap().clone();
    assert_eq!(posted.len(), 1);
    let c = posted[0]["content"].as_str().unwrap();
    assert!(c.contains("Kill switch") && c.contains("Floor hit") && !c.contains("stale"), "{c}");
    let v = log.view(now_ms());
    let muted = v.recent.iter().find(|r| r.reason.as_deref() == Some("muted")).unwrap();
    assert_eq!(muted.kinds, vec![AlertKind::DataStale]);
    assert!(!muted.delivered && muted.error.is_none());
    assert_eq!(v.counts, AlertCounts { sent_today: 1, failed_today: 0, suppressed_today: 1 });
    assert!(v.muted_until_ms > now_ms());

    // Unmuted, the next event goes out again.
    log.set_muted_until(0);
    assert_eq!(log.view(now_ms()).muted_until_ms, 0);
    sink.send(AlertEvent::new(AlertKind::ModelDrift, "drift", "vol model"));
    wait_for(&got, 2).await;
    assert_eq!(got.lock().unwrap().len(), 2);
}

#[tokio::test]
async fn the_hourly_limit_is_recorded_as_suppressed() {
    let (url, got) = mock(204).await;
    let mut cfg = quick(&url, AlertFormat::Discord);
    cfg.max_per_hour = 1;
    let log = awake_log();
    let sink = AlertSink::spawn_with_log(cfg, log.clone());
    sink.send(AlertEvent::new(AlertKind::KillSwitch, "a", "one"));
    wait_for(&got, 1).await;
    tokio::time::sleep(Duration::from_millis(100)).await;
    sink.send(AlertEvent::new(AlertKind::DataStale, "b", "two"));
    wait_log(&log, 2).await;
    let v = log.view(now_ms());
    assert_eq!(v.recent[0].reason.as_deref(), Some("hourlyLimit"));
    assert_eq!(v.counts.suppressed_today, 1);
}

#[test]
fn the_log_keeps_the_last_hundred_newest_first_and_counts_per_utc_day() {
    let log = awake_log();
    let day = 20_000 * 86_400_000_i64;
    for i in 0..105 {
        log.record(AlertRecord {
            ts: day + i,
            kinds: vec![AlertKind::DataStale],
            title: None,
            text: format!("n{i}"),
            delivered: true,
            error: None,
            reason: None,
            photo: false,
        });
    }
    let v = log.view(day + 200);
    assert_eq!(v.recent.len(), RECENT_POSTS);
    assert_eq!(v.recent[0].text, "n104");
    assert_eq!(v.counts.sent_today, 105);
    assert_eq!(log.view(day + 86_400_000).counts, AlertCounts::default(), "a new UTC day starts at zero");
    assert_eq!(log.view(day + 86_400_000).recent.len(), RECENT_POSTS, "the posts stay");
}

#[tokio::test]
async fn the_test_message_goes_out_even_when_muted() {
    let (url, got) = mock(200).await;
    let mut cfg = quick(&url, AlertFormat::Telegram);
    cfg.chat_id = Some("42".into());
    let log = awake_log();
    log.set_muted_until(now_ms() + 60_000);
    let sink = AlertSink::spawn_with_log(cfg, log.clone());
    let rec = sink.test().await;
    assert!(rec.delivered, "{rec:?}");
    assert_eq!(rec.kinds, vec![AlertKind::Test]);
    let got = got.lock().unwrap();
    assert_eq!(got[0]["chat_id"], "42");
    let text = got[0]["text"].as_str().unwrap();
    assert!(text.starts_with("<b>✅ Test message</b>\nAlerts from the engine reach this chat."), "{text}");
    assert!(text.contains("Quiet hours"), "{text}");
    assert_eq!(got[0]["parse_mode"], "HTML");
    assert_eq!(log.view(now_ms()).counts.sent_today, 1);
}

#[test]
fn the_mute_is_saved_with_the_engine_state() {
    let mut e = crate::engine::Engine::new();
    assert_eq!(e.alerts_muted_until(), 0);
    e.set_alerts_muted_until(1_900_000_000_000);
    let saved = serde_json::to_string(&e.to_persisted()).unwrap();
    let mut back = crate::engine::Engine::new();
    back.apply_persisted(serde_json::from_str(&saved).unwrap());
    assert_eq!(back.alerts_muted_until(), 1_900_000_000_000);
    // A save from before the mute existed loads unmuted.
    let mut old: serde_json::Value = serde_json::from_str(&saved).unwrap();
    old.as_object_mut().unwrap().remove("alerts_muted_until_ms");
    let mut back = crate::engine::Engine::new();
    back.apply_persisted(serde_json::from_value(old).unwrap());
    assert_eq!(back.alerts_muted_until(), 0);
}
