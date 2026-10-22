//! The pump.fun wallet page's API: reads what the live service wrote, takes
//! only lower limits, writes the kill file and offers no way to remove it.

use super::*;
use axum::body::{to_bytes, Body};
use axum::http::Request;
use tower::ServiceExt;

fn state() -> AppState {
    let (tx, _) = broadcast::channel(4);
    AppState {
        engine: Arc::new(Mutex::new(Engine::new())),
        tx,
        webhook: Arc::new(Mutex::new(None)),
        alert_sink: None,
        alert_log: alerts::AlertLog::default(),
        alert_files: Arc::new(AlertFiles { notify_dir: None, state_file: None, event_from: Vec::new(), image_roots: Vec::new() }),
        creds: Arc::new(credentials_from(&|_| None)),
    }
}

fn root(name: &str) -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!("pythia-pumpfun-api-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(d.join("reports").join("pumpfun_rt")).unwrap();
    d
}

async fn call(root: &std::path::Path, method: &str, uri: &str, body: Option<serde_json::Value>) -> (StatusCode, serde_json::Value) {
    let mut req = Request::builder().method(method).uri(uri);
    let body = match body {
        Some(v) => {
            req = req.header("content-type", "application/json");
            Body::from(v.to_string())
        }
        None => Body::empty(),
    };
    let resp = pumpfun_routes(Some(root.to_path_buf())).with_state(state()).oneshot(req.body(body).unwrap()).await.unwrap();
    let code = resp.status();
    let bytes = to_bytes(resp.into_body(), 1 << 20).await.unwrap();
    (code, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
}

fn write_status(root: &std::path::Path) {
    let s = serde_json::json!({
        "t": now_ms(), "running": true, "on": true, "mode": "test", "rule": "P_pool60",
        "address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU", "balance_sol": 0.8,
        "ack": {"mode": "test", "strategy": "P_pool60", "max_total_sol": 1.0, "max_daily_loss_sol": 0.3, "max_trade_sol": 0.02}
    });
    std::fs::write(root.join("reports/pumpfun_rt/live_status.json"), s.to_string()).unwrap();
}

#[tokio::test]
async fn the_page_reads_the_status_and_the_address() {
    let d = root("read");
    let (code, v) = call(&d, "GET", "/api/pumpfun/live", None).await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["running"], false);
    assert!(v["address"].is_null());
    write_status(&d);
    let (_, v) = call(&d, "GET", "/api/pumpfun/live", None).await;
    assert_eq!(v["running"], true);
    assert_eq!(v["status"]["balanceSol"], 0.8);
    assert_eq!(v["address"], "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU");
    let (code, v) = call(&d, "GET", "/api/pumpfun/live/trades", None).await;
    assert_eq!((code, v), (StatusCode::OK, serde_json::json!([])));
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn limits_go_down_only() {
    let d = root("limits");
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/settings", Some(serde_json::json!({"maxTradeSol": 0.01}))).await;
    assert_eq!(code, StatusCode::BAD_REQUEST, "{v}");
    write_status(&d);
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/settings", Some(serde_json::json!({"maxTradeSol": 0.01, "maxTotalSol": 0.5}))).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!(v["maxTradeSol"], 0.01);
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/settings", Some(serde_json::json!({"maxTradeSol": 0.03}))).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    assert!(v["error"].as_str().unwrap().contains("only be lowered"));
    let (code, _) = call(&d, "POST", "/api/pumpfun/live/settings", Some(serde_json::json!({"hardMax": 9}))).await;
    assert!(code.is_client_error());
    let (_, v) = call(&d, "GET", "/api/pumpfun/live", None).await;
    assert_eq!(v["settings"]["maxTotalSol"], 0.5);
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn the_kill_switch_is_one_way() {
    let d = root("kill");
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/kill", None).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!(v["killFile"], true);
    assert!(d.join("reports/pumpfun_rt/KILL").exists());
    let (_, v) = call(&d, "GET", "/api/pumpfun/live", None).await;
    assert_eq!(v["killFile"], true);
    for (method, uri) in [("DELETE", "/api/pumpfun/live/kill"), ("POST", "/api/pumpfun/live/unkill")] {
        let (code, _) = call(&d, method, uri, None).await;
        assert!(code.is_client_error(), "{method} {uri}");
    }
    assert!(d.join("reports/pumpfun_rt/KILL").exists());
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn there_is_no_withdraw_or_transfer_route() {
    let d = root("none");
    for uri in ["/api/pumpfun/live/withdraw", "/api/pumpfun/live/transfer", "/api/pumpfun/live/send"] {
        let (code, _) = call(&d, "POST", uri, Some(serde_json::json!({"to": "x", "sol": 1}))).await;
        assert_eq!(code, StatusCode::NOT_FOUND, "{uri}");
    }
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn the_feed_is_there_without_the_socket_too() {
    let d = root("feed");
    let (code, v) = call(&d, "GET", "/api/pumpfun/live/feed", None).await;
    assert_eq!((code, v), (StatusCode::OK, serde_json::Value::Null));
    let feed = serde_json::json!({"t": 1, "coins": [{"mint": "M", "points": [[1, 2e-6, 0.5, 1]], "exit": null}]});
    std::fs::write(d.join("reports").join("pumpfun_rt").join("live_feed.json"), feed.to_string()).unwrap();
    let (code, v) = call(&d, "GET", "/api/pumpfun/live/feed", None).await;
    assert_eq!((code, v), (StatusCode::OK, feed));
    // A plain GET of the socket's path (what a proxy without upgrades sends) is refused, not hung.
    let (code, _) = call(&d, "GET", "/api/pumpfun/live/ws", None).await;
    assert!(code.is_client_error(), "{code}");
    let _ = std::fs::remove_dir_all(&d);
}
