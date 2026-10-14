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
    let mut req = Request::builder().method(method).uri(uri);
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
    assert!(got.lock().unwrap()[0]["content"].as_str().unwrap().contains("**Test**"));

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
    let files = AlertFiles { notify_dir: None, state_file: Some(state.clone()) };
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
    let st = app_state(None, AlertFiles { notify_dir: Some(notify.clone()), state_file: None });
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
