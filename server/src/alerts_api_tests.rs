//! The operator alerts API against a mock webhook on 127.0.0.1.

use super::*;
use axum::body::{to_bytes, Body};
use axum::http::Request;
use tower::ServiceExt;

/// A webhook on 127.0.0.1 that records each JSON body and answers `status`.
async fn mock_hook(status: u16) -> (String, Arc<Mutex<Vec<serde_json::Value>>>) {
    let got: Arc<Mutex<Vec<serde_json::Value>>> = Default::default();
    let rec = got.clone();
    let app = Router::new().route(
        "/hook/:token",
        post(move |Json(v): Json<serde_json::Value>| {
            let rec = rec.clone();
            async move {
                rec.lock().unwrap().push(v);
                StatusCode::from_u16(status).unwrap()
            }
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}/hook/SECRETTOKEN12345", listener.local_addr().unwrap());
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (url, got)
}

fn quick(url: &str, format: alerts::AlertFormat) -> alerts::AlertConfig {
    let mut c = alerts::AlertConfig::new(url, format);
    c.batch_wait = Duration::from_millis(30);
    c
}

/// An app with the alert routes. `cfg` None: alerts off.
fn app_state(cfg: Option<alerts::AlertConfig>, files: AlertFiles) -> AppState {
    let (tx, _) = broadcast::channel(4);
    let log = alerts::AlertLog::default();
    AppState {
        engine: Arc::new(Mutex::new(Engine::new())),
        tx,
        webhook: Arc::new(Mutex::new(None)),
        alert_sink: cfg.map(|c| alerts::AlertSink::spawn_with_log(c, log.clone())),
        alert_log: log,
        alert_files: Arc::new(files),
        creds: Arc::new(credentials_from(&|_| None)),
    }
}

async fn call(st: &AppState, method: &str, uri: &str, body: Option<serde_json::Value>) -> (StatusCode, serde_json::Value) {
    call_from(st, "127.0.0.1:50000", method, uri, body).await
}

/// A call as if from `peer` (what `into_make_service_with_connect_info` hands in).
async fn call_from(
    st: &AppState,
    peer: &str,
    method: &str,
    uri: &str,
    body: Option<serde_json::Value>,
) -> (StatusCode, serde_json::Value) {
    let peer: std::net::SocketAddr = peer.parse().unwrap();
    let mut req = Request::builder().method(method).uri(uri).extension(axum::extract::ConnectInfo(peer));
    let body = match body {
        Some(v) => {
            req = req.header("content-type", "application/json");
            Body::from(v.to_string())
        }
        None => Body::empty(),
    };
    let resp = alert_routes().with_state(st.clone()).oneshot(req.body(body).unwrap()).await.unwrap();
    let code = resp.status();
    let bytes = to_bytes(resp.into_body(), 1 << 20).await.unwrap();
    (code, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
}

fn tmp_dir(name: &str) -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!("pythia-alerts-api-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

#[tokio::test]
async fn get_alerts_when_off_says_so() {
    let st = app_state(None, AlertFiles::default());
    let (code, v) = call(&st, "GET", "/api/alerts", None).await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["enabled"], false);
    assert_eq!(v["destination"], serde_json::Value::Null);
    assert_eq!(v["mutedUntilMs"], 0);
    assert_eq!(v["counts"], serde_json::json!({ "sentToday": 0, "failedToday": 0, "suppressedToday": 0 }));
    assert_eq!(v["recent"], serde_json::json!([]));
    assert_eq!(v["lastDigest"], serde_json::Value::Null);
}

#[tokio::test]
async fn test_message_is_409_with_a_reason_when_alerts_are_off() {
    let st = app_state(None, AlertFiles::default());
    let (code, v) = call(&st, "POST", "/api/alerts/test", None).await;
    assert_eq!(code, StatusCode::CONFLICT);
    assert!(v["error"].as_str().unwrap().contains("not configured"));
}

#[tokio::test]
async fn test_message_goes_through_and_shows_in_recent() {
    let (url, got) = mock_hook(204).await;
    let st = app_state(Some(quick(&url, alerts::AlertFormat::Discord)), AlertFiles::default());
    let (code, v) = call(&st, "POST", "/api/alerts/test", None).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!(v["delivered"], true);
    assert_eq!(v["kinds"], serde_json::json!(["test"]));
    assert_eq!(got.lock().unwrap().len(), 1);
    assert!(got.lock().unwrap()[0]["content"].as_str().unwrap().starts_with("**✅ Test message**"));

    let (_, v) = call(&st, "GET", "/api/alerts", None).await;
    assert_eq!(v["enabled"], true);
    assert_eq!(v["destination"], "discord");
    assert_eq!(v["counts"]["sentToday"], 1);
    assert_eq!(v["recent"][0]["delivered"], true);
    assert_eq!(v["recent"][0]["error"], serde_json::Value::Null);
}

#[tokio::test]
async fn a_failing_destination_is_502_and_the_error_has_no_secret() {
    let (url, _got) = mock_hook(500).await;
    let st = app_state(Some(quick(&url, alerts::AlertFormat::Slack)), AlertFiles::default());
    let (code, v) = call(&st, "POST", "/api/alerts/test", None).await;
    assert_eq!(code, StatusCode::BAD_GATEWAY);
    assert_eq!(v["delivered"], false);
    assert_eq!(v["error"], "HTTP 500");

    // A dead destination: the connection error names neither host nor token.
    let st = app_state(
        Some(quick("http://127.0.0.1:9/hook/SECRETTOKEN12345", alerts::AlertFormat::Discord)),
        AlertFiles::default(),
    );
    let (code, v) = call(&st, "POST", "/api/alerts/test", None).await;
    assert_eq!(code, StatusCode::BAD_GATEWAY);
    let (_, all) = call(&st, "GET", "/api/alerts", None).await;
    let text = all.to_string() + &v.to_string();
    assert!(!text.contains("SECRETTOKEN12345") && !text.contains("127.0.0.1:9"), "{text}");
    assert_eq!(all["counts"]["failedToday"], 1);
}

#[tokio::test]
async fn telegram_is_reported_as_the_destination() {
    let (url, got) = mock_hook(200).await;
    let mut cfg = quick(&url, alerts::AlertFormat::Telegram);
    cfg.chat_id = Some("12345678".into());
    let st = app_state(Some(cfg), AlertFiles::default());
    let (_, v) = call(&st, "GET", "/api/alerts", None).await;
    assert_eq!(v["destination"], "telegram");
    let (code, _) = call(&st, "POST", "/api/alerts/test", None).await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(got.lock().unwrap()[0]["chat_id"], "12345678");
}

#[tokio::test]
async fn mute_records_instead_of_sending_and_lets_the_kill_switch_through() {
    let (url, got) = mock_hook(204).await;
    let st = app_state(Some(quick(&url, alerts::AlertFormat::Discord)), AlertFiles::default());
    let (code, v) = call(&st, "POST", "/api/alerts/mute", Some(serde_json::json!({ "minutes": 60 }))).await;
    assert_eq!(code, StatusCode::OK);
    let until = v["mutedUntilMs"].as_i64().unwrap();
    assert!((until - now_ms() - 3_600_000).abs() < 5_000);
    assert_eq!(st.engine.lock().unwrap().alerts_muted_until(), until);

    let sink = st.alert_sink.clone().unwrap();
    sink.send(alerts::AlertEvent::new(alerts::AlertKind::DataStale, "stale", "quotes stale"));
    sink.send(alerts::AlertEvent::new(alerts::AlertKind::KillSwitch, "kill", "engaged"));
    for _ in 0..100 {
        if st.alert_log.view(now_ms()).recent.len() >= 2 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let (_, v) = call(&st, "GET", "/api/alerts", None).await;
    assert_eq!(v["mutedUntilMs"], until);
    assert_eq!(v["counts"]["sentToday"], 1);
    assert_eq!(v["counts"]["suppressedToday"], 1);
    let recent = v["recent"].as_array().unwrap();
    let muted = recent.iter().find(|r| r["reason"] == "muted").expect("a muted record");
    assert_eq!(muted["delivered"], false);
    assert_eq!(muted["kinds"], serde_json::json!(["dataStale"]));
    let posted = got.lock().unwrap().clone();
    assert_eq!(posted.len(), 1);
    assert!(posted[0]["content"].as_str().unwrap().contains("Kill switch"));

    // 0 unmutes.
    let (code, v) = call(&st, "POST", "/api/alerts/mute", Some(serde_json::json!({ "minutes": 0 }))).await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["mutedUntilMs"], 0);
    assert_eq!(st.engine.lock().unwrap().alerts_muted_until(), 0);
}

#[tokio::test]
async fn mute_is_capped_at_seven_days_and_rejects_bad_input() {
    let st = app_state(None, AlertFiles::default());
    let (code, _) = call(&st, "POST", "/api/alerts/mute", Some(serde_json::json!({ "minutes": 7 * 24 * 60 }))).await;
    assert_eq!(code, StatusCode::OK, "a mute works even with alerts off, for when they are turned on");
    let (code, v) = call(&st, "POST", "/api/alerts/mute", Some(serde_json::json!({ "minutes": 7 * 24 * 60 + 1 }))).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    assert!(v["error"].as_str().unwrap().contains("seven days"));
    let (code, _) = call(&st, "POST", "/api/alerts/mute", Some(serde_json::json!({ "minutes": -5 }))).await;
    assert!(code.is_client_error());
}

#[tokio::test]
async fn the_mute_survives_a_restart_through_the_state_file() {
    let dir = tmp_dir("mute");
    let state = dir.join("state.json");
    let files = AlertFiles { state_file: Some(state.clone()), ..Default::default() };
    let st = app_state(None, files);
    let (_, v) = call(&st, "POST", "/api/alerts/mute", Some(serde_json::json!({ "minutes": 120 }))).await;
    let until = v["mutedUntilMs"].as_i64().unwrap();

    // What `main` does at startup: restore the engine, then the log's mute from it.
    let mut e = Engine::new();
    match pythia_core::persist::load(&state) {
        pythia_core::persist::Loaded::Restored(p) => e.apply_persisted(*p),
        _ => panic!("the mute did not save the state file"),
    }
    assert_eq!(e.alerts_muted_until(), until);
    let log = alerts::AlertLog::default();
    log.set_muted_until(e.alerts_muted_until());
    assert_eq!(log.view(now_ms()).muted_until_ms, until);
    let _ = std::fs::remove_dir_all(&dir);
}

#[tokio::test]
async fn digest_request_writes_the_file_the_lab_reads_and_last_digest_is_reported() {
    let dir = tmp_dir("digest");
    let notify = dir.join("reports").join("notify");
    let st = app_state(None, AlertFiles { notify_dir: Some(notify.clone()), ..Default::default() });
    let (code, v) = call(&st, "POST", "/api/alerts/digest", None).await;
    assert_eq!(code, StatusCode::ACCEPTED);
    let req: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(notify.join("request.json")).unwrap()).unwrap();
    assert_eq!(req["ts"], v["requestedAt"]);

    std::fs::write(
        notify.join("latest.json"),
        r#"{"ts": 1760424600000, "text": "Pythia daily 2026-10-14\nForward test: ok.", "delivered": true}"#,
    )
    .unwrap();
    let (_, v) = call(&st, "GET", "/api/alerts", None).await;
    assert_eq!(v["lastDigest"]["ts"], 1760424600000_i64);
    assert!(v["lastDigest"]["text"].as_str().unwrap().starts_with("Pythia daily"));
    let _ = std::fs::remove_dir_all(&dir);
}

#[tokio::test]
async fn digest_request_is_409_without_a_data_folder() {
    let st = app_state(None, AlertFiles::default());
    let (code, v) = call(&st, "POST", "/api/alerts/digest", None).await;
    assert_eq!(code, StatusCode::CONFLICT);
    assert!(v["error"].as_str().unwrap().contains("PYTHIA_DATA"));
}

// ── settings ─────────────────────────────────────────────────────────────────

#[tokio::test]
async fn settings_are_listed_changed_saved_and_written_for_the_lab() {
    let dir = tmp_dir("settings");
    let notify = dir.join("reports").join("notify");
    let state = dir.join("state.json");
    let files = AlertFiles { notify_dir: Some(notify.clone()), state_file: Some(state.clone()), ..Default::default() };
    let st = app_state(None, files);
    let (code, v) = call(&st, "GET", "/api/alerts/settings", None).await;
    assert_eq!(code, StatusCode::OK);
    let cats = v["categories"].as_array().unwrap();
    assert_eq!(cats.len(), 14);
    assert!(cats.iter().all(|c| c["on"] == true));
    let ids: Vec<&str> = cats.iter().map(|c| c["id"].as_str().unwrap()).collect();
    for id in ["trades", "rebalances", "dailyPnl", "bigMoves", "autopilot", "risk", "venue", "models", "studies", "listings", "trending", "cs2", "pokemon", "weekly"] {
        assert!(ids.contains(&id), "{id}");
    }
    assert_eq!(v["quietHours"], serde_json::json!({"enabled": true, "start": "23:00", "end": "07:00", "timezone": "Europe/Berlin"}));
    assert_eq!(v["bigMoves"], serde_json::json!({"hourPct": 3.0, "dayPct": 8.0}));

    let (code, v) = call(
        &st,
        "POST",
        "/api/alerts/settings",
        Some(serde_json::json!({"categories": {"trades": false, "pokemon": false}, "quietHours": {"start": "22:00", "end": "06:30"}, "bigMoves": {"dayPct": 10}})),
    )
    .await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!(v["categories"][0]["on"], false);
    assert_eq!(v["quietHours"]["start"], "22:00");
    assert_eq!(v["bigMoves"]["dayPct"], 10.0);
    assert!(!st.alert_log.settings().enabled(alerts::AlertCategory::Pokemon));
    assert!(!st.engine.lock().unwrap().alert_settings().enabled(alerts::AlertCategory::Trades));

    // The lab's copy.
    let lab: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(notify.join("settings.json")).unwrap()).unwrap();
    assert_eq!(lab["quietHours"]["end"], "06:30");
    assert!(lab["categories"].as_array().unwrap().iter().any(|c| c["id"] == "pokemon" && c["on"] == false));

    // Saved at once: a restart keeps them.
    let mut e = Engine::new();
    match pythia_core::persist::load(&state) {
        pythia_core::persist::Loaded::Restored(p) => e.apply_persisted(*p),
        _ => panic!("the settings did not save the state file"),
    }
    assert!(!e.alert_settings().enabled(alerts::AlertCategory::Trades));
    assert_eq!(e.alert_settings().quiet_hours.start, "22:00");

    // A bad change is refused whole.
    let (code, v) = call(&st, "POST", "/api/alerts/settings", Some(serde_json::json!({"categories": {"risk": false}, "quietHours": {"start": "9pm"}}))).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    assert!(v["error"].as_str().unwrap().contains("HH:MM"));
    assert!(st.alert_log.settings().enabled(alerts::AlertCategory::Risk));
    let (code, _) = call(&st, "POST", "/api/alerts/settings", Some(serde_json::json!({"categories": {"nope": true}}))).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    let (code, _) = call(&st, "POST", "/api/alerts/settings", Some(serde_json::json!({"volume": 3}))).await;
    assert!(code.is_client_error());
    let _ = std::fs::remove_dir_all(&dir);
}

// ── events from the lab ──────────────────────────────────────────────────────

/// A Telegram look-alike on 127.0.0.1: `sendMessage` records the JSON,
/// `sendPhoto` the raw multipart body.
async fn mock_telegram() -> (String, Arc<Mutex<Vec<serde_json::Value>>>, Arc<Mutex<Vec<Vec<u8>>>>) {
    let msgs: Arc<Mutex<Vec<serde_json::Value>>> = Default::default();
    let photos: Arc<Mutex<Vec<Vec<u8>>>> = Default::default();
    let (m, p) = (msgs.clone(), photos.clone());
    let app = Router::new()
        .route(
            "/:bot/sendMessage",
            post(move |Json(v): Json<serde_json::Value>| {
                let m = m.clone();
                async move {
                    m.lock().unwrap().push(v);
                    StatusCode::OK
                }
            }),
        )
        .route(
            "/:bot/sendPhoto",
            post(move |body: axum::body::Bytes| {
                let p = p.clone();
                async move {
                    p.lock().unwrap().push(body.to_vec());
                    StatusCode::OK
                }
            }),
        );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}/botSECRETTOKEN12345/sendMessage", listener.local_addr().unwrap());
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (url, msgs, photos)
}

fn telegram_state(url: &str, files: AlertFiles) -> AppState {
    let mut cfg = quick(url, alerts::AlertFormat::Telegram);
    cfg.chat_id = Some("4242".into());
    app_state(Some(cfg), files)
}

async fn wait_msgs<T>(got: &Arc<Mutex<Vec<T>>>, n: usize) {
    for _ in 0..150 {
        if got.lock().unwrap().len() >= n {
            return;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

#[tokio::test]
async fn a_lab_event_goes_out_as_a_card() {
    let (url, msgs, _) = mock_telegram().await;
    let st = telegram_state(&url, AlertFiles::default());
    // Quiet hours off, so the test does not depend on the time of day.
    st.alert_log.set_settings(alerts::AlertSettings {
        quiet_hours: alerts::QuietHours { enabled: false, ..Default::default() },
        ..Default::default()
    });
    let (code, v) = call(
        &st,
        "POST",
        "/api/alerts/event",
        Some(serde_json::json!({
            "category": "studies",
            "title": "Factory <run> 2026-10-17",
            "text": "3 new strategies survived the holdout & 1 was retired.",
            "rows": [["Tried", "120"], {"label": "Best OOS", "value": "+1.40", "sign": 1.4}],
            "table": {"header": ["Name", "Sharpe"], "rows": [["tsmom_v2", "1.40"], ["carry", "0.90"]]}
        })),
    )
    .await;
    assert_eq!(code, StatusCode::ACCEPTED, "{v}");
    assert_eq!(v["queued"], true);
    wait_msgs(&msgs, 1).await;
    let m = msgs.lock().unwrap()[0].clone();
    assert_eq!(m["parse_mode"], "HTML");
    assert_eq!(m["chat_id"], "4242");
    let text = m["text"].as_str().unwrap();
    assert!(text.starts_with("<b>🧪 Factory &lt;run&gt; 2026-10-17</b>\n3 new strategies survived the holdout &amp; 1 was retired.\n<pre>"), "{text}");
    assert!(text.contains("Best OOS  +1.40 🟢"), "{text}");
    assert!(text.contains("Name     Sharpe\ntsmom_v2   1.40"), "{text}");
    let (_, all) = call(&st, "GET", "/api/alerts", None).await;
    assert_eq!(all["recent"][0]["kinds"], serde_json::json!(["event"]));
    assert_eq!(all["recent"][0]["title"], "Factory <run> 2026-10-17");
}

#[tokio::test]
async fn events_come_from_this_machine_only() {
    let (url, msgs, _) = mock_telegram().await;
    let ev = serde_json::json!({"category": "trending", "title": "BONK surge"});
    let st = telegram_state(&url, AlertFiles::default());
    let (code, v) = call_from(&st, "203.0.113.9:4000", "POST", "/api/alerts/event", Some(ev.clone())).await;
    assert_eq!(code, StatusCode::FORBIDDEN);
    assert!(v["error"].as_str().unwrap().contains("this machine"));
    let (code, _) = call_from(&st, "[::1]:4000", "POST", "/api/alerts/event", Some(ev.clone())).await;
    assert_eq!(code, StatusCode::ACCEPTED, "IPv6 loopback");
    let (code, _) = call_from(&st, "[::ffff:127.0.0.1]:4000", "POST", "/api/alerts/event", Some(ev.clone())).await;
    assert_eq!(code, StatusCode::ACCEPTED, "IPv4 loopback seen through IPv6");
    // A Docker bridge, when listed.
    let files = AlertFiles { event_from: vec!["172.17.".into()], ..Default::default() };
    let st = telegram_state(&url, files);
    let (code, _) = call_from(&st, "172.17.0.5:4000", "POST", "/api/alerts/event", Some(ev.clone())).await;
    assert_eq!(code, StatusCode::ACCEPTED);
    let (code, _) = call_from(&st, "172.18.0.5:4000", "POST", "/api/alerts/event", Some(ev)).await;
    assert_eq!(code, StatusCode::FORBIDDEN);
    let _ = msgs;
}

#[tokio::test]
async fn bad_events_are_refused_and_a_switched_off_category_is_not_queued() {
    let (url, msgs, _) = mock_telegram().await;
    let st = telegram_state(&url, AlertFiles::default());
    let post_ev = |v: serde_json::Value| {
        let st = st.clone();
        async move { call(&st, "POST", "/api/alerts/event", Some(v)).await }
    };
    let (code, v) = post_ev(serde_json::json!({"category": "weather", "title": "x"})).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    assert!(v["error"].as_str().unwrap().contains("unknown category weather"));
    let (code, _) = post_ev(serde_json::json!({"category": "cs2", "title": ""})).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    let (code, _) = post_ev(serde_json::json!({"category": "cs2", "title": "x", "colour": "red"})).await;
    assert!(code.is_client_error());
    let mut s = alerts::AlertSettings::default();
    s.categories.insert("cs2".into(), false);
    st.alert_log.set_settings(s);
    let (code, v) = post_ev(serde_json::json!({"category": "cs2", "title": "AK-47 Redline +12 %"})).await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v, serde_json::json!({"queued": false, "reason": "off"}));
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert!(msgs.lock().unwrap().is_empty());
    // Alerts off: 409.
    let off = app_state(None, AlertFiles::default());
    let (code, _) = call(&off, "POST", "/api/alerts/event", Some(serde_json::json!({"category": "cs2", "title": "x"}))).await;
    assert_eq!(code, StatusCode::CONFLICT);
}

/// A 1x1 PNG.
const PNG: &[u8] = &[
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00,
    0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4, 0x89, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x44, 0x41, 0x54, 0x78,
    0x9C, 0x63, 0xF8, 0xFF, 0xFF, 0x3F, 0x00, 0x05, 0xFE, 0x02, 0xFE, 0xA7, 0x35, 0x81, 0x84, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,
    0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
];

#[tokio::test]
async fn an_event_with_an_image_is_sent_as_a_photo_with_its_card_as_caption() {
    let (url, msgs, photos) = mock_telegram().await;
    let dir = tmp_dir("image");
    let charts = dir.join("reports").join("notify");
    std::fs::create_dir_all(&charts).unwrap();
    std::fs::write(charts.join("weekly.png"), PNG).unwrap();
    let outside = tmp_dir("image-outside");
    std::fs::write(outside.join("x.png"), PNG).unwrap();
    std::fs::write(dir.join("notes.txt"), "hello").unwrap();
    let files = AlertFiles { image_roots: vec![dir.clone()], ..Default::default() };
    let st = telegram_state(&url, files);
    st.alert_log.set_settings(alerts::AlertSettings {
        quiet_hours: alerts::QuietHours { enabled: false, ..Default::default() },
        ..Default::default()
    });
    let (code, v) = call(
        &st,
        "POST",
        "/api/alerts/event",
        Some(serde_json::json!({"category": "weekly", "title": "Week 42", "text": "Up 2.1 % against BTC +0.4 %.", "image": "reports/notify/weekly.png"})),
    )
    .await;
    assert_eq!(code, StatusCode::ACCEPTED, "{v}");
    wait_msgs(&photos, 1).await;
    let body = String::from_utf8_lossy(&photos.lock().unwrap()[0]).to_string();
    assert!(body.contains("name=\"chat_id\"\r\n\r\n4242"));
    assert!(body.contains("<b>🗓️ Week 42</b>\nUp 2.1 % against BTC +0.4 %."), "{body}");
    assert!(body.contains("name=\"parse_mode\"\r\n\r\nHTML"));
    assert!(body.contains("Content-Type: image/png"));
    assert!(msgs.lock().unwrap().is_empty(), "the photo carries the card");
    let (_, all) = call(&st, "GET", "/api/alerts", None).await;
    assert_eq!(all["recent"][0]["photo"], true);

    // Outside the data folder, not a picture, or missing: refused.
    for (img, why) in [
        (outside.join("x.png").to_string_lossy().to_string(), "inside the data folder"),
        ("notes.txt".to_string(), ".png or .jpg"),
        ("reports/notify/none.png".to_string(), "not found"),
    ] {
        let (code, v) = call(&st, "POST", "/api/alerts/event", Some(serde_json::json!({"category": "weekly", "title": "x", "image": img}))).await;
        assert_eq!(code, StatusCode::BAD_REQUEST, "{img}");
        assert!(v["error"].as_str().unwrap().contains(why), "{v}");
    }
    let _ = std::fs::remove_dir_all(&dir);
    let _ = std::fs::remove_dir_all(&outside);
}

#[tokio::test]
async fn quiet_hours_hold_back_and_the_morning_note_follows() {
    let (url, msgs, _) = mock_telegram().await;
    let mut cfg = quick(&url, alerts::AlertFormat::Telegram);
    cfg.chat_id = Some("4242".into());
    cfg.wake = Duration::from_millis(50);
    let st = app_state(Some(cfg), AlertFiles::default());
    // Quiet from three hours ago to three hours from now, Berlin time.
    let berlin = chrono::Utc::now().with_timezone(&chrono_tz_berlin());
    let hhmm = |h: i64| (berlin + chrono::Duration::hours(h)).format("%H:%M").to_string();
    let quiet = alerts::QuietHours { enabled: true, start: hhmm(-3), end: hhmm(3), timezone: "Europe/Berlin".into() };
    assert!(quiet.contains(now_ms()));
    st.alert_log.set_settings(alerts::AlertSettings { quiet_hours: quiet.clone(), ..Default::default() });
    let sink = st.alert_sink.clone().unwrap();
    sink.send(alerts::AlertEvent::new(alerts::AlertKind::AutopilotStarted, "a", "Momentum started").titled("Momentum started"));
    sink.send(alerts::AlertEvent::new(alerts::AlertKind::KillSwitch, "k", "engaged by hand."));
    wait_msgs(&msgs, 1).await;
    tokio::time::sleep(Duration::from_millis(150)).await;
    {
        let m = msgs.lock().unwrap();
        assert_eq!(m.len(), 1, "only the urgent one in quiet hours");
        assert!(m[0]["text"].as_str().unwrap().contains("Kill switch"));
    }
    let v = st.alert_log.view(now_ms());
    assert!(v.recent.iter().any(|r| r.reason.as_deref() == Some("quiet")));
    // Quiet hours end: the note says what was held.
    st.alert_log.set_settings(alerts::AlertSettings {
        quiet_hours: alerts::QuietHours { enabled: false, ..quiet },
        ..Default::default()
    });
    wait_msgs(&msgs, 2).await;
    let m = msgs.lock().unwrap();
    assert_eq!(m.len(), 2);
    let text = m[1]["text"].as_str().unwrap();
    assert!(text.starts_with("<b>🌙 Quiet hours are over</b>\n1 alert was held back"), "{text}");
    assert!(text.contains("Momentum started"), "{text}");
}

fn chrono_tz_berlin() -> chrono::FixedOffset {
    // The test needs only an offset close to Berlin's for the window it sets;
    // a window six hours wide covers summer and winter time alike.
    let now = chrono::Utc::now();
    let summer = matches!(now.format("%m").to_string().as_str(), "04" | "05" | "06" | "07" | "08" | "09");
    chrono::FixedOffset::east_opt(if summer { 7200 } else { 3600 }).unwrap()
}
