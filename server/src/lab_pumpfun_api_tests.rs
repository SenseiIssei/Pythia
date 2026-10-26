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

#[tokio::test]
async fn the_lab_reads_the_factories_the_zoo_and_the_allocator_without_their_details() {
    let d = std::env::temp_dir().join(format!("pythia-lab-factory-api-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    let get = |root: Option<std::path::PathBuf>, method: &'static str| async move {
        let req = Request::builder().method(method).uri("/api/lab/factory").body(Body::empty()).unwrap();
        let resp = lab_factory_routes(root).with_state(state()).oneshot(req).await.unwrap();
        let code = resp.status();
        let bytes = to_bytes(resp.into_body(), 1 << 20).await.unwrap();
        (code, serde_json::from_slice::<serde_json::Value>(&bytes).unwrap_or(serde_json::Value::Null))
    };
    let (code, v) = get(None, "GET").await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["found"], false);
    let (_, v) = get(Some(d.clone()), "GET").await;
    assert_eq!(v["found"], false);
    assert!(v["factories"]["F3"].is_null() && v["zoo"].is_null() && v["allocator"].is_null());
    std::fs::create_dir_all(d.join("reports/pumpfun_rt")).unwrap();
    std::fs::write(
        d.join("reports/pumpfun_rt/factory.json"),
        r#"{"updated_ms":5,"night":"2026-10-26","trials_ever":330,"trials_tonight":300,"bar":{"sharpe":0.12,"trials":330},
            "best":[{"id":"F3_00042","median":0.9,"params":{"tp":0.3},"label":"migration 5 s"}],
            "holdback":[{"id":"F3_00042","median":0.48,"pnl_sol":-0.03,"entries":40,"days":["x"]}],
            "models":{"win30":{"adopted":true},"rug0t":{"adopted":false}},
            "books":[{"book":"F3_00011","sol":0.61,"eur":97.6}],"retired":[{"book":"F3_00001","retired_ms":4,"params":{}}],
            "proposals":[],"winners":[],"sol_eur":160.0}"#,
    )
    .unwrap();
    std::fs::write(d.join("reports/pumpfun_rt/zoo.json"), r#"{"updated_ms":6,"labels":{"win30":{"pick":"lgb","days":4,"changes":[],"regimes":{}}}}"#).unwrap();
    std::fs::write(
        d.join("reports/pumpfun_rt/allocator.json"),
        r#"{"updated_ms":7,"choice":"P_pool0_wait","live_rule":"P_pool0_wait","armed":false,"why":"x",
            "arms":{"P_pool0_wait":{"p_best":0.6,"posterior_mean":0.01,"posterior_sd":0.02,"rewards":{"2026-10-25":0.1}}}}"#,
    )
    .unwrap();
    let (code, v) = get(Some(d.clone()), "GET").await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["found"], true);
    let f3 = &v["factories"]["F3"];
    assert_eq!(f3["trials_ever"], 330);
    assert_eq!(f3["best"][0]["id"], "F3_00042");
    assert!(f3["best"][0].get("params").is_none(), "no trial's parameters");
    assert_eq!(f3["holdback"][0]["pnl_sol"], -0.03);
    assert_eq!(f3["adopted"], serde_json::json!(["win30"]));
    assert_eq!(f3["books"][0]["eur"], 97.6);
    assert_eq!(f3["retired"][0]["book"], "F3_00001");
    assert!(v["factories"]["F2"].is_null(), "F2 has no report: null");
    assert_eq!(v["zoo"]["labels"]["win30"]["pick"], "lgb");
    assert!(v["zoo"]["labels"]["win30"].get("regimes").is_none());
    assert_eq!(v["allocator"]["arms"]["P_pool0_wait"]["p_best"], 0.6);
    assert!(v["allocator"]["arms"]["P_pool0_wait"].get("rewards").is_none(), "no reward series");
    let (code, _) = get(Some(d.clone()), "POST").await;
    assert_eq!(code, StatusCode::METHOD_NOT_ALLOWED);
    let _ = std::fs::remove_dir_all(&d);
}
