//! The Lab page's pump.fun section: read only, from the lab's data folder.

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

async fn call(root: Option<std::path::PathBuf>, method: &str) -> (StatusCode, serde_json::Value) {
    let req = Request::builder().method(method).uri("/api/lab/pumpfun").body(Body::empty()).unwrap();
    let resp = lab_pumpfun_routes(root).with_state(state()).oneshot(req).await.unwrap();
    let code = resp.status();
    let bytes = to_bytes(resp.into_body(), 1 << 20).await.unwrap();
    (code, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
}

#[tokio::test]
async fn the_lab_reads_the_pumpfun_study_and_its_paper_books() {
    let d = std::env::temp_dir().join(format!("pythia-lab-pumpfun-api-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    let (code, v) = call(Some(d.clone()), "GET").await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["found"], false);
    std::fs::create_dir_all(d.join("reports/pumpfun_rt")).unwrap();
    std::fs::create_dir_all(d.join("paper/pumpfun_rt")).unwrap();
    std::fs::write(
        d.join("reports/pumpfun_rt/latest.json"),
        r#"{"status":"bad","headline":"Paper only.","updated_ms":5,"readiness":{"P_pool0":{"days":4,"ready":false}},"shadow":{}}"#,
    )
    .unwrap();
    std::fs::write(d.join("reports/pumpfun_rt/execution.json"), r#"{"fills":3,"verdict":"slow"}"#).unwrap();
    let t = now_ms() - 60_000;
    std::fs::write(d.join("paper/pumpfun_rt/ledger.csv"), format!("rule,symbol,exit_ms,pnl_sol,ret\nP_pool0,AAA,{t},0.02,0.2\n")).unwrap();
    let (code, v) = call(Some(d.clone()), "GET").await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["found"], true);
    assert_eq!(v["readiness"]["P_pool0"]["days"], 4);
    assert_eq!(v["execution"]["fills"], 3);
    assert_eq!(v["books"][0]["rule"], "P_pool0");
    assert_eq!(v["books"][0]["entries"], 1);
    assert_eq!(v["books"][0]["recent"][0]["symbol"], "AAA");
    // Nothing written, nothing else answered: a POST is not a route here.
    let (code, _) = call(Some(d.clone()), "POST").await;
    assert_eq!(code, StatusCode::METHOD_NOT_ALLOWED);
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn without_a_data_folder_the_section_is_empty() {
    let (code, v) = call(None, "GET").await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["found"], false);
    assert!(v["books"].as_array().unwrap().is_empty());
}
