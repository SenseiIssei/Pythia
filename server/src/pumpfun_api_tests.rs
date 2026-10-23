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

#[tokio::test]
async fn the_trends_are_read_only() {
    let d = root("trends");
    let (code, v) = call(&d, "GET", "/api/pumpfun/trends", None).await;
    assert_eq!((code, v), (StatusCode::OK, serde_json::json!({"trends": null, "dexscreener": null})));
    let t = serde_json::json!({"t": 1, "lists": {"hot": [{"mint": "M", "vol_5m": 2.0}], "migrating": [], "fresh": []}});
    std::fs::write(d.join("reports").join("pumpfun_rt").join("trends.json"), t.to_string()).unwrap();
    std::fs::create_dir_all(d.join("reports").join("trending")).unwrap();
    let rep = serde_json::json!({"updatedMs": 2, "status": "ok", "dex": [{"symbol": "CAT"}], "gainers": []});
    std::fs::write(d.join("reports").join("trending").join("latest.json"), rep.to_string()).unwrap();
    let (code, v) = call(&d, "GET", "/api/pumpfun/trends", None).await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["trends"], t);
    assert_eq!(v["dexscreener"]["items"], serde_json::json!([{"symbol": "CAT"}]));
    assert_eq!(v["dexscreener"]["updatedMs"], 2);
    for method in ["POST", "PUT", "DELETE"] {
        let (code, _) = call(&d, method, "/api/pumpfun/trends", Some(serde_json::json!({}))).await;
        assert!(code.is_client_error(), "{method}");
    }
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn the_owners_controls_round_trip_and_bad_input_is_refused() {
    let d = root("control");
    let (code, v) = call(&d, "GET", "/api/pumpfun/live/control", None).await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v, serde_json::json!({"share": null, "paused": false, "setAt": null, "shareSetAt": null, "pausedAt": null, "effective": null}));
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/control", Some(serde_json::json!({"paused": true, "share": 0.05}))).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!((v["paused"].clone(), v["share"].clone()), (serde_json::json!(true), serde_json::json!(0.05)));
    assert!(v["pausedAt"].is_i64() && v["shareSetAt"].is_i64() && v["setAt"].is_i64());
    let disk: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(d.join("reports/pumpfun_rt/control.json")).unwrap()).unwrap();
    assert_eq!((disk["paused"].clone(), disk["share"].clone()), (serde_json::json!(true), serde_json::json!(0.05)));
    let (_, v) = call(&d, "GET", "/api/pumpfun/live", None).await;
    assert_eq!((v["control"]["paused"].clone(), v["control"]["share"].clone()), (serde_json::json!(true), serde_json::json!(0.05)));
    // The app clears Stop itself; the share stays.
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/control", Some(serde_json::json!({"paused": false}))).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!((v["paused"].clone(), v["pausedAt"].clone(), v["share"].clone()), (serde_json::json!(false), serde_json::Value::Null, serde_json::json!(0.05)));
    for body in [
        serde_json::json!({}),
        serde_json::json!({"share": 0.0099}),
        serde_json::json!({"share": 1.01}),
        serde_json::json!({"share": 0.5, "resetShare": true}),
    ] {
        let (code, v) = call(&d, "POST", "/api/pumpfun/live/control", Some(body.clone())).await;
        assert_eq!(code, StatusCode::BAD_REQUEST, "{body} {v}");
        assert!(v["error"].is_string(), "{body} {v}");
    }
    for body in [serde_json::json!({"paused": true, "kill": false}), serde_json::json!({"share": "all"})] {
        let (code, _) = call(&d, "POST", "/api/pumpfun/live/control", Some(body.clone())).await;
        assert!(code.is_client_error(), "{body}");
    }
    let (_, v) = call(&d, "GET", "/api/pumpfun/live/control", None).await;
    assert_eq!((v["share"].clone(), v["paused"].clone()), (serde_json::json!(0.05), serde_json::json!(false))); // nothing refused was kept
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/control", Some(serde_json::json!({"resetShare": true}))).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert!(v["share"].is_null() && v["shareSetAt"].is_null());
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn the_share_goes_above_ten_percent_only_with_wallet_limits_and_effective_is_the_status() {
    let d = root("control-ten");
    write_status(&d);
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/control", Some(serde_json::json!({"share": 0.5}))).await;
    assert_eq!(code, StatusCode::BAD_REQUEST, "{v}");
    assert!(v["error"].as_str().unwrap().contains("limits=wallet"), "{v}");
    let (_, v) = call(&d, "GET", "/api/pumpfun/live/control", None).await;
    assert!(v["share"].is_null() && v["effective"].is_null());
    let s = serde_json::json!({
        "t": now_ms(), "running": true, "on": true, "mode": "test",
        "ack": {"mode": "test", "limits": "wallet", "stake_share": 0.1},
        "control": {"limits": "wallet", "share": 0.1, "share_source": "ack", "share_since": null, "ack_share": 0.1,
                    "requested_share": null, "paused": false, "paused_since": null, "note": null, "control_ok": true}
    });
    std::fs::write(d.join("reports/pumpfun_rt/live_status.json"), s.to_string()).unwrap();
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/control", Some(serde_json::json!({"share": 0.5}))).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!(v["share"], 0.5);
    assert_eq!(v["effective"]["shareSource"], "ack");
    assert_eq!(v["effective"]["ackShare"], 0.1);
    assert_eq!(v["effective"]["controlOk"], true);
    let (_, v) = call(&d, "GET", "/api/pumpfun/live", None).await;
    assert_eq!(v["status"]["ack"]["limits"], "wallet");
    assert_eq!(v["status"]["control"]["shareSource"], "ack");
    assert_eq!(v["control"]["share"], 0.5);
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn the_block_list_is_read_added_to_and_removed_from_atomically() {
    let d = root("blocked");
    let mint = format!("Mint{}", "1".repeat(36));
    let dev = format!("Dev{}", "1".repeat(37));
    let (code, v) = call(&d, "GET", "/api/pumpfun/live/blocked", None).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!(v["entries"], serde_json::json!([]));                    // no file: an empty list
    std::fs::create_dir_all(d.join("pumpfun_rt")).unwrap();
    std::fs::write(d.join("pumpfun_rt/blocked-mints.txt"), "# the owner's list\nsymbol:SHEKEL  # relaunches\nnot a mint\n").unwrap();
    let (_, v) = call(&d, "GET", "/api/pumpfun/live/blocked", None).await;
    assert_eq!(v["entries"], serde_json::json!([{"entry": "symbol:SHEKEL", "kind": "symbol", "value": "SHEKEL"}]));
    assert_eq!(v["ignored"], serde_json::json!(["not a mint"]));
    for add in [mint.clone(), format!("creator:{dev}"), "name: Moon Dog ".into(), "SYMBOL:$shekel".into()] {
        let (code, v) = call(&d, "POST", "/api/pumpfun/live/blocked", Some(serde_json::json!({"add": add.clone()}))).await;
        assert_eq!(code, StatusCode::OK, "{add} {v}");
    }
    let (_, v) = call(&d, "GET", "/api/pumpfun/live/blocked", None).await;
    let entries: Vec<String> = v["entries"].as_array().unwrap().iter().map(|e| e["entry"].as_str().unwrap().to_string()).collect();
    assert_eq!(entries, vec!["symbol:SHEKEL".to_string(), mint.clone(), format!("creator:{dev}"), "name:Moon Dog".into()]); // $shekel is SHEKEL
    let text = std::fs::read_to_string(d.join("pumpfun_rt/blocked-mints.txt")).unwrap();
    assert!(text.starts_with("# the owner's list\n") && text.contains("not a mint\n") && text.ends_with("name:Moon Dog\n"), "{text}");
    assert!(!d.join("pumpfun_rt/blocked-mints.txt.tmp").exists());
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/blocked", Some(serde_json::json!({"remove": "symbol:shekel"}))).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    assert_eq!(v["entries"].as_array().unwrap().len(), 3);
    let text = std::fs::read_to_string(d.join("pumpfun_rt/blocked-mints.txt")).unwrap();
    assert!(!text.contains("SHEKEL") && text.contains("# the owner's list"), "{text}");
    let (code, _) = call(&d, "POST", "/api/pumpfun/live/blocked", Some(serde_json::json!({"remove": "symbol:shekel"}))).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn the_block_list_takes_only_valid_entries() {
    let d = root("blocked-bad");
    for body in [
        serde_json::json!({"add": "not a mint"}),
        serde_json::json!({"add": "creator:short"}),
        serde_json::json!({"add": format!("Mint0{}", "1".repeat(35))}),   // 0 is not base58
        serde_json::json!({"add": "symbol:$$$"}),
        serde_json::json!({"add": format!("name:{}", "a".repeat(65))}),
        serde_json::json!({"add": "wallet:abc"}),
        serde_json::json!({"add": "symbol:A # B"}),
        serde_json::json!({"add": "symbol:A\nsymbol:B"}),
        serde_json::json!({"add": ""}),
        serde_json::json!({"add": "symbol:A", "remove": "symbol:B"}),
        serde_json::json!({}),
        serde_json::json!({"add": "symbol:A", "all": true}),
    ] {
        let (code, _) = call(&d, "POST", "/api/pumpfun/live/blocked", Some(body.clone())).await;
        assert!(code.is_client_error(), "{body}");
    }
    assert!(!d.join("pumpfun_rt/blocked-mints.txt").exists());
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn the_block_list_takes_match_entries_of_three_letters_or_more() {
    let d = root("blocked-match");
    std::fs::create_dir_all(d.join("pumpfun_rt")).unwrap();
    std::fs::write(d.join("pumpfun_rt/blocked-mints.txt"), "symbol:SHEKEL\nmatch:spacex\nmatch:ai\n").unwrap();
    let (_, v) = call(&d, "GET", "/api/pumpfun/live/blocked", None).await;
    assert_eq!(
        v["entries"],
        serde_json::json!([{"entry": "symbol:SHEKEL", "kind": "symbol", "value": "SHEKEL"},
                           {"entry": "match:spacex", "kind": "match", "value": "spacex"}])
    );
    assert_eq!(v["ignored"], serde_json::json!(["match:ai"]));                // under three letters or digits
    for add in ["match:elon", "Match: Tesla ", "match:$SPACE-X"] {
        let (code, v) = call(&d, "POST", "/api/pumpfun/live/blocked", Some(serde_json::json!({"add": add}))).await;
        assert_eq!(code, StatusCode::OK, "{add} {v}");
    }
    let (_, v) = call(&d, "GET", "/api/pumpfun/live/blocked", None).await;
    let entries: Vec<String> = v["entries"].as_array().unwrap().iter().map(|e| e["entry"].as_str().unwrap().to_string()).collect();
    assert_eq!(entries, vec!["symbol:SHEKEL", "match:spacex", "match:elon", "match:Tesla"]); // $SPACE-X is spacex
    let (code, v) = call(&d, "POST", "/api/pumpfun/live/blocked", Some(serde_json::json!({"remove": "match:ELON"}))).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    let text = std::fs::read_to_string(d.join("pumpfun_rt/blocked-mints.txt")).unwrap();
    assert!(!text.contains("elon") && text.contains("match:Tesla\n") && text.contains("symbol:SHEKEL"), "{text}");
    let long = format!("match:{}", "a".repeat(65));
    let bads: [&str; 4] = ["match:ai", "match:$-e", "match:", long.as_str()];
    for bad in bads {
        let (code, _) = call(&d, "POST", "/api/pumpfun/live/blocked", Some(serde_json::json!({"add": bad}))).await;
        assert_eq!(code, StatusCode::BAD_REQUEST, "{bad}");
    }
    let _ = std::fs::remove_dir_all(&d);
}
