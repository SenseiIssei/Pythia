use super::*;
use crate::llm::{self, CompleteRequest, LlmConfig, LlmError, Provider};
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

const DAY: i64 = 86_400_000;
/// 2026-10-15 12:00 UTC.
const NOW: i64 = 1_792_065_600_000;

fn tmp() -> PathBuf {
    let d = std::env::temp_dir().join(format!("pythia-ai-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn entry(ts: i64, cost: f64) -> Entry {
    Entry {
        ts,
        source: "test".into(),
        job: "brief".into(),
        model: "claude-haiku-5-5".into(),
        served_by: String::new(),
        usage: Usage::default(),
        batch: false,
        cost_usd: cost,
        ok: true,
    }
}

fn write_ledger(dir: &Path, entries: &[Entry]) {
    let mut s = String::new();
    for e in entries {
        s.push_str(&serde_json::to_string(e).unwrap());
        s.push('\n');
    }
    std::fs::write(dir.join("ledger.jsonl"), s).unwrap();
}

fn usage(i: u64, o: u64) -> Usage {
    Usage { input_tokens: i, output_tokens: o, ..Usage::default() }
}

// ── prices and cost math ────────────────────────────────────────────────────

#[test]
fn the_price_table_has_the_claude_5_family() {
    let t = prices();
    let (h, known) = t.price("claude-haiku-5-5");
    assert!(known);
    assert_eq!((h.input, h.output), (0.10, 0.50));
    assert_eq!((t.price("claude-sonnet-5-5").0.input, t.price("claude-sonnet-5-5").0.output), (2.0, 10.0));
    assert_eq!((t.price("claude-opus-5-5").0.input, t.price("claude-opus-5-5").0.output), (4.0, 20.0));
    assert_eq!(t.batch_discount, 0.5);
    assert!(!t.as_of.is_empty());
}

#[test]
fn cost_math() {
    let t = prices();
    let eq = |a: f64, b: f64| assert!((a - b).abs() < 1e-12, "{a} != {b}");
    // A million in, a million out (Haiku: a prompt of 100K, its short-rate limit).
    eq(t.cost("claude-haiku-5-5", &usage(100_000, 1_000_000), false), 0.01 + 0.50);
    eq(t.cost("claude-sonnet-5-5", &usage(1_000_000, 1_000_000), false), 12.0);
    eq(t.cost("claude-opus-5-5", &usage(1_000_000, 1_000_000), false), 24.0);
    // A typical brief: 6,000 in, 800 out on Haiku.
    eq(t.cost("claude-haiku-5-5", &usage(6_000, 800), false), 0.0006 + 0.0004);
    // Batch at half price.
    eq(t.cost("claude-sonnet-5-5", &usage(20_000, 3_000), true), (0.04 + 0.03) / 2.0);
    // Cache: written at 1.25x, read at 0.1x on Haiku.
    let cached = Usage { input_tokens: 100, output_tokens: 0, cache_write_tokens: 50_000, cache_read_tokens: 40_000 };
    eq(t.cost("claude-haiku-5-5", &cached, false), (100.0 * 0.10 + 50_000.0 * 0.125 + 40_000.0 * 0.01) / 1e6);
    // Cached tokens count toward the prompt length that picks the long rates.
    let long = Usage { input_tokens: 100, output_tokens: 0, cache_write_tokens: 0, cache_read_tokens: 200_000 };
    eq(t.cost("claude-haiku-5-5", &long, false), (100.0 * 0.50 + 200_000.0 * 0.01 * 5.0) / 1e6);
    // Haiku past 100K prompt tokens bills the long rates on everything.
    eq(t.cost("claude-haiku-5-5", &usage(200_000, 1_000_000), false), 200_000.0 * 0.5 / 1e6 + 2.5);
    // An unknown model is never cheap: it costs the dearest row.
    let (worst, known) = t.price("claude-made-up-9");
    assert!(!known);
    assert!(worst.output >= 50.0);
}

#[test]
fn a_fallback_model_is_costed_at_the_dearer_rate() {
    let d = tmp();
    let b = Budget::open(Some(d), "test");
    let r = b.reserve(0.1, NOW).unwrap();
    let e = r.record("signal", "claude-sonnet-5-5", "claude-opus-5-5", usage(1_000, 1_000), false, true, NOW);
    assert!((e.cost_usd - (1_000.0 * 4.0 + 1_000.0 * 20.0) / 1e6).abs() < 1e-12);
    assert_eq!(e.served_by, "claude-opus-5-5");
}

#[test]
fn the_estimate_is_a_worst_case() {
    // Every output token allowed, and the prompt at two characters a token.
    let est = estimate("claude-haiku-5-5", 4_000, 1_000, false);
    let real = prices().cost("claude-haiku-5-5", &usage(1_000, 300), false);
    assert!(est > real);
    assert!((estimate("claude-sonnet-5-5", 0, 1_000, true) * 2.0 - estimate("claude-sonnet-5-5", 0, 1_000, false)).abs() < 1e-12);
}

// ── caps ────────────────────────────────────────────────────────────────────

#[test]
fn caps_default_sanitize_and_persist() {
    assert_eq!(Caps::default(), Caps { lifetime_usd: 90.0, monthly_usd: 15.0, daily_usd: 1.5 });
    let bad = Caps { lifetime_usd: f64::NAN, monthly_usd: -3.0, daily_usd: 5_000.0 }.sanitized();
    assert_eq!(bad, Caps { lifetime_usd: 90.0, monthly_usd: 15.0, daily_usd: MAX_CAP_USD });

    let d = tmp();
    let b = Budget::open(Some(d.clone()), "test");
    assert_eq!(b.caps(), DEFAULT_CAPS, "no file: the defaults");
    b.set_caps(Caps { lifetime_usd: 50.0, monthly_usd: 10.0, daily_usd: 1.0 }).unwrap();
    // Another process (a fresh Budget on the folder) sees them.
    assert_eq!(Budget::open(Some(d.clone()), "other").caps().lifetime_usd, 50.0);
    // A broken file falls back to the defaults, the low ones.
    std::fs::write(d.join("budget.json"), "{not json").unwrap();
    assert_eq!(b.caps(), DEFAULT_CAPS);
}

// ── refusal at each cap ─────────────────────────────────────────────────────

#[test]
fn the_daily_cap_refuses() {
    let d = tmp();
    write_ledger(&d, &[entry(NOW - 3_600_000, 1.45)]);
    let b = Budget::open(Some(d), "test");
    assert!(b.reserve(0.04, NOW).is_ok(), "1.49 fits under 1.50");
    match b.reserve(0.10, NOW) {
        Err(Refusal::Daily { spent_usd, cap_usd, .. }) => {
            assert!((spent_usd - 1.45).abs() < 1e-9);
            assert_eq!(cap_usd, 1.5);
        }
        Err(other) => panic!("wrong cap: {other}"),
        Ok(_) => panic!("should refuse"),
    }
    // Tomorrow the day is fresh.
    assert!(b.reserve(0.10, NOW + DAY).is_ok());
}

#[test]
fn the_monthly_cap_refuses() {
    let d = tmp();
    // 14.90 spent earlier this month, a little each day, under the daily cap.
    let entries: Vec<Entry> = (1..=10).map(|k| entry(NOW - k * DAY, 1.49)).collect();
    write_ledger(&d, &entries);
    let b = Budget::open(Some(d), "test");
    let r = b.reserve(0.2, NOW).unwrap_err();
    assert!(matches!(r, Refusal::Monthly { .. }), "{r}");
    assert!(r.to_string().contains("monthly cap of $15.00"));
    // Last month's spend does not count: on 1 November the month is fresh.
    let nov = 1_793_491_200_000; // 2026-11-01 00:00 UTC
    assert!(b.reserve(0.2, nov).is_ok());
}

#[test]
fn the_lifetime_cap_refuses_and_never_resets() {
    let d = tmp();
    // 89.95 spread over the past year, under every monthly cap.
    let entries: Vec<Entry> = (1..=60).map(|k| entry(NOW - k * 5 * DAY, 89.95 / 60.0)).collect();
    write_ledger(&d, &entries);
    let b = Budget::open(Some(d), "test");
    let r = b.reserve(0.10, NOW).unwrap_err();
    assert!(matches!(r, Refusal::Lifetime { .. }), "{r}");
    assert!(b.reserve(0.10, NOW + 400 * DAY).is_err(), "lifetime means lifetime");
    assert!(b.reserve(0.01, NOW).is_ok(), "what still fits, fits");
}

#[test]
fn a_zero_cap_switches_the_api_off() {
    let b = Budget::open(None, "test");
    b.set_caps(Caps { lifetime_usd: 90.0, monthly_usd: 15.0, daily_usd: 0.0 }).unwrap();
    assert!(matches!(b.reserve(0.0, NOW), Err(Refusal::Daily { .. })));
}

#[test]
fn reservations_hold_room_until_recorded_or_dropped() {
    let b = Budget::open(None, "test");
    let first = b.reserve(1.0, NOW).unwrap();
    assert!(b.reserve(0.6, NOW).is_err(), "1.0 in flight + 0.6 > 1.5");
    drop(first);
    let second = b.reserve(1.4, NOW).unwrap();
    second.record("brief", "claude-haiku-5-5", "", usage(1_000, 100), false, true, NOW);
    assert!(b.spend(NOW).in_flight_usd.abs() < 1e-12);
    assert!(b.reserve(1.4, NOW).is_ok(), "the real cost was tiny, the room is back");
}

// ── the ledger ──────────────────────────────────────────────────────────────

#[test]
fn the_ledger_survives_a_restart() {
    let d = tmp();
    {
        let b = Budget::open(Some(d.clone()), "server");
        for _ in 0..3 {
            let r = b.reserve(0.01, NOW).unwrap();
            r.record("brief", "claude-haiku-5-5", "", usage(10_000, 1_000), false, true, NOW);
        }
    }
    let again = Budget::open(Some(d.clone()), "server");
    let s = again.spend(NOW);
    assert_eq!(s.calls, 3);
    assert!((s.lifetime_usd - 3.0 * 0.0015).abs() < 1e-12);
    assert_eq!(s.calls_today, 3);
    let recent = again.recent(10);
    assert_eq!(recent.len(), 3);
    assert_eq!(recent[0].source, "server");
    assert_eq!(recent[0].usage.input_tokens, 10_000);
    // The file is plain JSON lines a person can read.
    let text = std::fs::read_to_string(d.join("ledger.jsonl")).unwrap();
    assert_eq!(text.lines().count(), 3);
    assert!(text.contains("\"costUsd\""));
}

#[test]
fn two_processes_share_one_ledger() {
    let d = tmp();
    let a = Budget::open(Some(d.clone()), "server");
    let b = Budget::open(Some(d.clone()), "autopilot");
    a.reserve(0.5, NOW).unwrap().record("x", "claude-sonnet-5-5", "", usage(100_000, 30_000), false, true, NOW);
    // b never wrote anything, and still sees a's 0.50.
    assert!((b.spend(NOW).today_usd - 0.5).abs() < 1e-12);
    b.reserve(0.5, NOW).unwrap().record("y", "claude-sonnet-5-5", "", usage(100_000, 30_000), false, true, NOW);
    assert!((a.spend(NOW).today_usd - 1.0).abs() < 1e-12);
    assert!(a.reserve(0.6, NOW).is_err());
}

#[test]
fn a_half_written_or_broken_line_does_not_break_the_ledger() {
    let d = tmp();
    let good = serde_json::to_string(&entry(NOW, 0.25)).unwrap();
    std::fs::write(d.join("ledger.jsonl"), format!("{good}\nnot json at all\n{{\"ts\":1,\"mod")).unwrap();
    let b = Budget::open(Some(d.clone()), "test");
    assert_eq!(b.spend(NOW).calls, 1);
    // The other process finishes its line: now it counts.
    let mut f = std::fs::OpenOptions::new().append(true).open(d.join("ledger.jsonl")).unwrap();
    f.write_all(b"el\":\"claude-haiku-5-5\",\"inputTokens\":0,\"outputTokens\":0,\"costUsd\":0.5}\n").unwrap();
    let s = b.spend(NOW);
    assert_eq!(s.calls, 2);
    assert!((s.lifetime_usd - 0.75).abs() < 1e-12);
}

#[test]
fn a_mirrored_ledger_counts_toward_the_caps() {
    let server = tmp();
    write_ledger(&server, &[entry(NOW, 1.2)]);
    let desktop = tmp();
    let b = Budget::open(Some(desktop), "desktop").with_mirror(server.join("ledger.jsonl"));
    assert!((b.spend(NOW).today_usd - 1.2).abs() < 1e-12);
    assert!(b.reserve(0.4, NOW).is_err());
}

// ── alerts ──────────────────────────────────────────────────────────────────

fn collect(b: &Budget) -> Arc<Mutex<Vec<BudgetAlert>>> {
    let got: Arc<Mutex<Vec<BudgetAlert>>> = Default::default();
    let g = got.clone();
    b.set_alert_hook(move |a| g.lock().unwrap().push(a.clone()));
    got
}

#[test]
fn alerts_at_50_80_and_100_percent_once_each() {
    let d = tmp();
    let b = Budget::open(Some(d.clone()), "test");
    b.set_caps(Caps { lifetime_usd: 10.0, monthly_usd: 100.0, daily_usd: 100.0 }).unwrap();
    let got = collect(&b);
    let spend = |usd: f64| {
        let r = b.reserve(usd, NOW).unwrap();
        // 1M output tokens on Haiku cost 0.50.
        r.record("x", "claude-haiku-5-5", "", usage(0, (usd / 0.5 * 1e6) as u64), false, true, NOW);
    };
    spend(4.5);
    assert!(got.lock().unwrap().is_empty());
    spend(1.0); // 5.5: past 50 %
    spend(1.0); // 6.5
    spend(1.5); // 8.0: past 80 %
    {
        let g = got.lock().unwrap();
        assert_eq!(g.iter().map(|a| a.percent).collect::<Vec<_>>(), vec![50, 80]);
        assert!(g[0].text().contains("50 %"));
    }
    // A restart does not repeat them.
    let again = Budget::open(Some(d.clone()), "test");
    let got2 = collect(&again);
    again.reserve(0.5, NOW).unwrap().record("x", "claude-haiku-5-5", "", usage(0, 1_000_000), false, true, NOW);
    assert!(got2.lock().unwrap().is_empty());
    // 8.5 spent: a call of 1.6 is refused, but 1.5 still fits, so not "used up".
    assert!(again.reserve(1.6, NOW).is_err());
    assert!(got2.lock().unwrap().is_empty());
    again.reserve(1.5, NOW).unwrap().record("x", "claude-haiku-5-5", "", usage(0, 3_000_000), false, true, NOW);
    let g = got2.lock().unwrap();
    assert_eq!(g.len(), 1);
    assert_eq!(g[0].percent, 100);
    assert!(g[0].text().contains("used up"));
}

#[test]
fn the_100_percent_alert_also_fires_on_the_first_refusal() {
    let d = tmp();
    write_ledger(&d, &[entry(NOW - 40 * DAY, 89.995)]);
    let b = Budget::open(Some(d.clone()), "test");
    let got = collect(&b);
    assert!(b.reserve(0.02, NOW).is_err());
    assert!(b.reserve(0.02, NOW).is_err());
    let g = got.lock().unwrap();
    assert_eq!(g.len(), 1, "once, not on every refusal");
    assert!(g[0].refused);
    assert_eq!(g[0].percent, 100);
}

#[test]
fn the_view_says_what_is_left_and_what_refuses() {
    let d = tmp();
    write_ledger(&d, &[entry(NOW, 1.5)]);
    let v = Budget::open(Some(d), "test").view(NOW);
    assert_eq!(v.left_today_usd, 0.0);
    assert!((v.left_lifetime_usd - 88.5).abs() < 1e-9);
    assert!(v.refusing.as_deref().unwrap_or_default().contains("daily"));
    assert!(v.persisted);
    assert_eq!(v.recent.len(), 1);
}

// ── calls, with a mocked API ────────────────────────────────────────────────

/// What the mock answers: (status, body) for (method, path, request body).
type Route = Arc<dyn Fn(&str, &str, &serde_json::Value) -> (u16, String) + Send + Sync>;

/// A tiny HTTP server that records each request and answers from `route`.
async fn mock(route: Route) -> (String, Arc<Mutex<Vec<(String, String, serde_json::Value)>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let got: Arc<Mutex<Vec<(String, String, serde_json::Value)>>> = Default::default();
    let rec = got.clone();
    tokio::spawn(async move {
        loop {
            let Ok((mut sock, _)) = listener.accept().await else { return };
            let rec = rec.clone();
            let route = route.clone();
            tokio::spawn(async move {
                let mut buf = Vec::new();
                let mut chunk = [0u8; 8192];
                loop {
                    let n = sock.read(&mut chunk).await.unwrap_or(0);
                    if n == 0 {
                        return;
                    }
                    buf.extend_from_slice(&chunk[..n]);
                    let text = String::from_utf8_lossy(&buf).to_string();
                    let Some(end) = text.find("\r\n\r\n") else { continue };
                    let head = &text[..end];
                    let len = head
                        .lines()
                        .find_map(|l| l.to_ascii_lowercase().strip_prefix("content-length:").map(|v| v.trim().parse::<usize>().unwrap_or(0)))
                        .unwrap_or(0);
                    if buf.len() < end + 4 + len {
                        continue;
                    }
                    let mut first = head.lines().next().unwrap_or_default().split_whitespace();
                    let method = first.next().unwrap_or_default().to_string();
                    let path = first.next().unwrap_or_default().to_string();
                    let body: serde_json::Value = serde_json::from_slice(&buf[end + 4..end + 4 + len]).unwrap_or_default();
                    // The key is sent in its header and nowhere else.
                    assert!(head.to_ascii_lowercase().contains("x-api-key: test-key"));
                    let (status, reply) = route(&method, &path, &body);
                    rec.lock().unwrap().push((method, path, body));
                    let out = format!(
                        "HTTP/1.1 {status} X\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{reply}",
                        reply.len()
                    );
                    let _ = sock.write_all(out.as_bytes()).await;
                    return;
                }
            });
        }
    });
    (base, got)
}

fn message(text: &str, input: u64, output: u64) -> String {
    serde_json::json!({
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{ "type": "text", "text": text }],
        "stop_reason": "end_turn",
        "usage": { "input_tokens": input, "output_tokens": output,
                   "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0 }
    })
    .to_string()
}

fn cfg(base: &str) -> LlmConfig {
    LlmConfig::new(Provider::Anthropic, "", "test-key").with_base_url(base).with_job("brief")
}

const SIGNAL: &str = r#"{"probability":0.6,"direction":"long","confidence":0.3,"rationale":"x"}"#;

#[tokio::test]
async fn a_call_is_metered_and_written_to_the_ledger() {
    let (base, got) = mock(Arc::new(|_, _, _| (200, message(SIGNAL, 2_000, 100)))).await;
    let d = tmp();
    let b = Budget::open(Some(d.clone()), "server");
    let sig = llm::signal_in(&b, &cfg(&base), "BTC").await.unwrap();
    assert_eq!(sig.probability, 0.6);
    let reqs = got.lock().unwrap();
    assert_eq!(reqs.len(), 1);
    assert_eq!(reqs[0].1, "/v1/messages");
    assert_eq!(reqs[0].2["max_tokens"], 1024, "small max_tokens on Haiku");
    let recent = b.recent(5);
    assert_eq!(recent.len(), 1);
    assert_eq!(recent[0].job, "brief");
    assert!((recent[0].cost_usd - (2_000.0 * 0.1 + 100.0 * 0.5) / 1e6).abs() < 1e-15);
    assert!(std::fs::read_to_string(d.join("ledger.jsonl")).unwrap().contains("\"job\":\"brief\""));
}

#[tokio::test]
async fn nothing_is_sent_when_the_budget_refuses() {
    let (base, got) = mock(Arc::new(|_, _, _| (200, message(SIGNAL, 1, 1)))).await;
    let d = tmp();
    write_ledger(&d, &[entry(NOW.max(chrono::Utc::now().timestamp_millis()), 1.5)]);
    let b = Budget::open(Some(d), "server");
    let err = llm::signal_in(&b, &cfg(&base), "BTC").await.unwrap_err();
    assert!(matches!(err, LlmError::Budget(Refusal::Daily { .. })), "{err}");
    let mut req = CompleteRequest::new("sys", "facts", 500);
    req.batch = true;
    assert!(matches!(llm::complete_in(&b, &cfg(&base), &req).await, Err(LlmError::Budget(_))));
    assert!(got.lock().unwrap().is_empty(), "the API was never called");
}

#[tokio::test]
async fn nothing_is_called_without_a_key() {
    let (base, got) = mock(Arc::new(|_, _, _| (200, message(SIGNAL, 1, 1)))).await;
    let b = Budget::open(None, "server");
    let no_key = LlmConfig::new(Provider::Anthropic, "", "  ").with_base_url(&base);
    assert!(matches!(llm::signal_in(&b, &no_key, "BTC").await, Err(LlmError::NoKey(_))));
    let req = CompleteRequest::new("sys", "facts", 500);
    assert!(matches!(llm::complete_in(&b, &no_key, &req).await, Err(LlmError::NoKey(_))));
    assert!(got.lock().unwrap().is_empty());
    assert_eq!(b.spend(NOW).calls, 0);
}

#[tokio::test]
async fn an_http_error_is_not_billed_but_a_refusal_is() {
    let d = tmp();
    let b = Budget::open(Some(d), "server");
    let (base, _) = mock(Arc::new(|_, _, _| (529, r#"{"type":"error"}"#.into()))).await;
    assert!(matches!(llm::signal_in(&b, &cfg(&base), "BTC").await, Err(LlmError::Api { status: 529, .. })));
    assert_eq!(b.spend(chrono::Utc::now().timestamp_millis()).calls, 0);
    assert_eq!(b.spend(chrono::Utc::now().timestamp_millis()).in_flight_usd, 0.0, "room freed");

    let refusal = serde_json::json!({
        "model": "claude-haiku-5-5", "content": [], "stop_reason": "refusal",
        "stop_details": { "type": "refusal", "category": "cyber" },
        "usage": { "input_tokens": 500, "output_tokens": 0 }
    })
    .to_string();
    let (base, _) = mock(Arc::new(move |_, _, _| (200, refusal.clone()))).await;
    assert!(matches!(llm::signal_in(&b, &cfg(&base), "BTC").await, Err(LlmError::Refused(c)) if c == "cyber"));
    let r = b.recent(1);
    assert_eq!(r.len(), 1);
    assert!(!r[0].ok);
    assert_eq!(r[0].usage.input_tokens, 500);
}

#[tokio::test]
async fn a_completion_that_is_not_json_is_billed_and_reported() {
    let (base, _) = mock(Arc::new(|_, _, _| (200, message("Sorry, I cannot do JSON today.", 3_000, 20)))).await;
    let b = Budget::open(None, "server");
    let mut req = CompleteRequest::new("sys", "facts", 500);
    req.schema = Some(serde_json::json!({ "type": "object" }));
    let c = llm::complete_in(&b, &cfg(&base), &req).await.unwrap();
    assert!(c.json.is_none());
    assert!(c.parse_error.as_deref().unwrap().contains("not a JSON object"));
    assert!(c.cost_usd > 0.0);
    assert_eq!(b.spend(chrono::Utc::now().timestamp_millis()).calls, 1);

    let (base, _) = mock(Arc::new(|_, _, _| (200, message("```json\n{\"a\": 1}\n```", 3_000, 20)))).await;
    let c = llm::complete_in(&b, &cfg(&base), &req).await.unwrap();
    assert_eq!(c.json.unwrap()["a"], 1);
}

#[tokio::test]
async fn a_batch_is_submitted_polled_read_and_costed_at_half_price() {
    let polls = Arc::new(Mutex::new(0));
    let p = polls.clone();
    let base_cell: Arc<Mutex<String>> = Default::default();
    let bc = base_cell.clone();
    let route: Route = Arc::new(move |method, path, body| match (method, path) {
        ("POST", "/v1/messages/batches") => {
            let params = &body["requests"][0]["params"];
            assert!(params.get("fallbacks").is_none(), "the Batches API rejects fallbacks");
            assert_eq!(params["system"][0]["cache_control"]["type"], "ephemeral");
            (200, r#"{"id":"msgbatch_1","processing_status":"in_progress"}"#.into())
        }
        ("GET", "/v1/messages/batches/msgbatch_1") => {
            let mut n = p.lock().unwrap();
            *n += 1;
            let st = if *n >= 2 { "ended" } else { "in_progress" };
            let url = format!("{}/results/msgbatch_1", bc.lock().unwrap());
            (200, serde_json::json!({ "id": "msgbatch_1", "processing_status": st, "results_url": url }).to_string())
        }
        ("GET", "/results/msgbatch_1") => {
            let msg: serde_json::Value = serde_json::from_str(&message(r#"{"ok":true}"#, 10_000, 1_000)).unwrap();
            (200, serde_json::json!({ "custom_id": "pythia-1", "result": { "type": "succeeded", "message": msg } }).to_string())
        }
        _ => (404, "{}".into()),
    });
    let (base, got) = mock(route).await;
    *base_cell.lock().unwrap() = base.clone();
    let b = Budget::open(None, "server");
    let mut req = CompleteRequest::new("sys", "facts", 2_000);
    req.schema = Some(serde_json::json!({ "type": "object" }));
    req.batch = true;
    req.poll_every = std::time::Duration::from_millis(10);
    let c = llm::complete_in(&b, &cfg(&base), &req).await.unwrap();
    assert_eq!(c.batch_id.as_deref(), Some("msgbatch_1"));
    assert_eq!(c.json.unwrap()["ok"], true);
    assert!((c.cost_usd - (10_000.0 * 0.1 + 1_000.0 * 0.5) / 1e6 / 2.0).abs() < 1e-15);
    assert!(b.recent(1)[0].batch);
    assert_eq!(got.lock().unwrap().len(), 4, "submit, two polls, results");
}

#[tokio::test]
async fn a_batch_that_does_not_finish_is_cancelled_and_counted_at_its_worst_case() {
    let route: Route = Arc::new(|method, path, _| match (method, path) {
        ("POST", "/v1/messages/batches") => (200, r#"{"id":"msgbatch_2","processing_status":"in_progress"}"#.into()),
        ("POST", "/v1/messages/batches/msgbatch_2/cancel") => (200, r#"{"id":"msgbatch_2","processing_status":"canceling"}"#.into()),
        _ => (200, r#"{"id":"msgbatch_2","processing_status":"in_progress"}"#.into()),
    });
    let (base, got) = mock(route).await;
    let b = Budget::open(None, "server");
    let mut req = CompleteRequest::new("sys", "facts", 2_000);
    req.batch = true;
    req.poll_every = std::time::Duration::from_millis(10);
    req.batch_wait = std::time::Duration::from_millis(60);
    let err = llm::complete_in(&b, &cfg(&base), &req).await.unwrap_err();
    assert!(matches!(err, LlmError::BatchTimeout(ref id) if id == "msgbatch_2"), "{err}");
    assert!(got.lock().unwrap().iter().any(|(m, p, _)| m == "POST" && p.ends_with("/cancel")));
    let e = &b.recent(1)[0];
    assert!(!e.ok);
    assert!((e.cost_usd - estimate("claude-haiku-5-5", 3 + 5, 2_000, true)).abs() < 1e-15);
}

#[tokio::test]
async fn only_claude_runs_scheduled_jobs() {
    let b = Budget::open(None, "server");
    let other = LlmConfig::new(Provider::OpenAI, "", "k");
    let req = CompleteRequest::new("s", "u", 10);
    assert!(matches!(llm::complete_in(&b, &other, &req).await, Err(LlmError::Unsupported(_))));
}
