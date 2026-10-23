//! The on-chain wallet's API: reads what the locked trader wrote, writes only a
//! conversion request, the confirm of a fresh proposal and the kill file, and
//! offers no way to remove the kill file or to send money anywhere.

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

/// A made-up address (base58, 32 characters), not a real wallet.
const ADDR: &str = "11111111111111111111111111111111";

fn root(name: &str) -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!("pythia-onchain-api-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(d.join("reports").join("onchain_live").join("convert")).unwrap();
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
    let resp = onchain_routes(Some(root.to_path_buf())).with_state(state()).oneshot(req.body(body).unwrap()).await.unwrap();
    let code = resp.status();
    let bytes = to_bytes(resp.into_body(), 1 << 20).await.unwrap();
    (code, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
}

fn write_status(root: &std::path::Path) {
    let s = serde_json::json!({
        "t": now_ms(), "running": true, "on": false, "mode": "test", "gate": ["the proof gate has not passed"],
        "address": ADDR, "total_usd": 30.0,
        "balances": [{"coin": "SOL", "symbol": "SOL", "amount": 0.1, "usd": 15.0, "price_usd": 150.0},
                     {"coin": "USDC", "symbol": "USDC", "amount": 15.0, "usd": 15.0, "price_usd": 1.0}],
        "coins": [{"coin": "SOL", "symbol": "SOL", "decimals": 9, "allowed": true},
                  {"coin": "USDC", "symbol": "USDC", "decimals": 6, "allowed": true}],
        "stops": {"daily": false, "total": false}, "kill": false
    });
    std::fs::write(root.join("reports/onchain_live/status.json"), s.to_string()).unwrap();
}

#[tokio::test]
async fn the_section_reads_the_status_and_the_address() {
    let d = root("read");
    let (code, v) = call(&d, "GET", "/api/onchain/live", None).await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["running"], false);
    assert!(v["status"].is_null() && v["address"].is_null());
    assert_eq!((v["trades"].clone(), v["converts"].clone()), (serde_json::json!([]), serde_json::json!([])));
    write_status(&d);
    let (_, v) = call(&d, "GET", "/api/onchain/live", None).await;
    assert_eq!(v["running"], true);
    assert_eq!(v["status"]["totalUsd"], 30.0);
    assert_eq!(v["status"]["balances"][0]["priceUsd"], 150.0);
    assert_eq!(v["address"], ADDR);
    assert_eq!(v["killFile"], false);
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn a_conversion_is_asked_for_then_confirmed_while_its_proposal_is_fresh() {
    let d = root("convert");
    let ask = serde_json::json!({"from": "USDC", "to": "SOL", "amount": 10.0});
    let (code, v) = call(&d, "POST", "/api/onchain/live/convert", Some(ask.clone())).await;
    assert_eq!(code, StatusCode::BAD_REQUEST, "{v}");
    assert!(v["error"].as_str().unwrap().contains("not running"));
    write_status(&d);
    let (code, v) = call(&d, "POST", "/api/onchain/live/convert", Some(ask)).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    let id = v["id"].as_str().unwrap().to_string();
    assert!(pythia_core::onchain_live::is_id(&id), "{id}");
    let dir = d.join("reports/onchain_live/convert");
    assert!(dir.join(format!("{id}.request.json")).exists());
    let (_, v) = call(&d, "GET", "/api/onchain/live", None).await;
    assert_eq!(v["converts"][0]["state"], "waiting");
    // Nothing to confirm before the trader proposed.
    let (code, _) = call(&d, "POST", "/api/onchain/live/convert/confirm", Some(serde_json::json!({"id": id}))).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    let t = now_ms();
    let proposal = serde_json::json!({"id": id, "from": "USDC", "to": "SOL", "amount": 10.0, "in_raw": "10000000",
        "expected_out": 0.0667, "min_out": 0.0663, "min_out_raw": "66300000", "cost_bps": 4.2, "in_usd": 10.0,
        "route": ["Whirlpool"], "t": t, "expires_ms": t + 60_000, "status": "proposed", "why": null});
    std::fs::write(dir.join(format!("{id}.proposal.json")), proposal.to_string()).unwrap();
    let (_, v) = call(&d, "GET", "/api/onchain/live", None).await;
    assert_eq!((v["converts"][0]["state"].clone(), v["converts"][0]["minOut"].clone()), (serde_json::json!("proposed"), serde_json::json!(0.0663)));
    let (code, v) = call(&d, "POST", "/api/onchain/live/convert/confirm", Some(serde_json::json!({"id": id}))).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!(v["confirmed"], true);
    let c: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(dir.join(format!("{id}.confirm.json"))).unwrap()).unwrap();
    assert_eq!((c["proposal_t"].clone(), c["min_out_raw"].clone()), (serde_json::json!(t), serde_json::json!("66300000")));
    let (code, v) = call(&d, "POST", "/api/onchain/live/convert/confirm", Some(serde_json::json!({"id": id}))).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    assert!(v["error"].as_str().unwrap().contains("already confirmed"));
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn bad_requests_are_refused() {
    let d = root("bad");
    write_status(&d);
    for body in [
        serde_json::json!({"from": "SOL", "to": "SOL", "amount": 1.0}),
        serde_json::json!({"from": "USDC", "to": "BONK", "amount": 1.0}),
        serde_json::json!({"from": "USDC", "to": "SOL", "amount": -1.0}),
    ] {
        let (code, v) = call(&d, "POST", "/api/onchain/live/convert", Some(body.clone())).await;
        assert_eq!(code, StatusCode::BAD_REQUEST, "{body} {v}");
    }
    // Unknown fields (a slippage of one's own, a destination) are refused before anything is read.
    for body in [
        serde_json::json!({"from": "USDC", "to": "SOL", "amount": 1.0, "slippageBps": 5000}),
        serde_json::json!({"from": "USDC", "to": "SOL", "amount": 1.0, "destination": ADDR}),
    ] {
        let (code, _) = call(&d, "POST", "/api/onchain/live/convert", Some(body.clone())).await;
        assert!(code.is_client_error(), "{body}");
    }
    for id in ["../status", "c1792449990001-ABCD", "c1792449990001-abcd/../../KILL"] {
        let (code, v) = call(&d, "POST", "/api/onchain/live/convert/confirm", Some(serde_json::json!({"id": id}))).await;
        assert_eq!(code, StatusCode::BAD_REQUEST, "{id}");
        assert!(v["error"].as_str().unwrap().contains("Not a conversion id"), "{id}");
    }
    assert_eq!(std::fs::read_dir(d.join("reports/onchain_live/convert")).unwrap().count(), 0);
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn the_kill_switch_is_one_way() {
    let d = root("kill");
    let (code, v) = call(&d, "POST", "/api/onchain/live/kill", None).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!(v["killFile"], true);
    assert!(d.join("reports/onchain_live/KILL").exists());
    let (_, v) = call(&d, "GET", "/api/onchain/live", None).await;
    assert_eq!(v["killFile"], true);
    for (method, uri) in [("DELETE", "/api/onchain/live/kill"), ("POST", "/api/onchain/live/unkill")] {
        let (code, _) = call(&d, method, uri, None).await;
        assert!(code.is_client_error(), "{method} {uri}");
    }
    assert!(d.join("reports/onchain_live/KILL").exists());
    // With the kill file there, no conversion is asked for.
    write_status(&d);
    let (code, v) = call(&d, "POST", "/api/onchain/live/convert", Some(serde_json::json!({"from": "USDC", "to": "SOL", "amount": 1.0}))).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    assert!(v["error"].as_str().unwrap().contains("kill switch"));
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn there_is_no_withdraw_or_transfer_route() {
    let d = root("none");
    for uri in ["/api/onchain/live/withdraw", "/api/onchain/live/transfer", "/api/onchain/live/send", "/api/onchain/live/sign"] {
        let (code, _) = call(&d, "POST", uri, Some(serde_json::json!({"to": ADDR, "amount": 1}))).await;
        assert_eq!(code, StatusCode::NOT_FOUND, "{uri}");
    }
    let _ = std::fs::remove_dir_all(&d);
}
