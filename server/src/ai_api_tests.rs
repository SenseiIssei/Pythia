//! The Claude budget API: who may call, what is accepted, the caps.

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
        alert_files: Arc::new(AlertFiles {
            notify_dir: None,
            state_file: None,
            event_from: Vec::new(),
            image_roots: Vec::new(),
        }),
        creds: Arc::new(credentials_from(&|_| None)),
    }
}

async fn call(peer: &str, method: &str, uri: &str, body: Option<serde_json::Value>, token: Option<&str>) -> (StatusCode, serde_json::Value) {
    let peer: std::net::SocketAddr = peer.parse().unwrap();
    let mut req = Request::builder().method(method).uri(uri).extension(axum::extract::ConnectInfo(peer));
    if let Some(t) = token {
        req = req.header("x-pythia-ai-token", t);
    }
    let body = match body {
        Some(v) => {
            req = req.header("content-type", "application/json");
            Body::from(v.to_string())
        }
        None => Body::empty(),
    };
    let resp = ai_routes().with_state(state()).oneshot(req.body(body).unwrap()).await.unwrap();
    let code = resp.status();
    let bytes = to_bytes(resp.into_body(), 1 << 20).await.unwrap();
    (code, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
}

fn brief() -> serde_json::Value {
    serde_json::json!({
        "job": "brief", "system": "fixed instructions", "user": "today's facts",
        "maxTokens": 1500, "batch": true
    })
}

#[tokio::test]
async fn a_completion_is_taken_from_this_machine_only() {
    let (code, v) = call("203.0.113.9:4000", "POST", "/api/ai/complete", Some(brief()), Some("x")).await;
    assert_eq!(code, StatusCode::FORBIDDEN);
    assert!(v["error"].as_str().unwrap().contains("this machine"));
}

#[tokio::test]
async fn without_a_key_nothing_is_called() {
    if Provider::Anthropic.configured_in_env() {
        return; // a developer machine with a real key: not the case under test
    }
    let (code, v) = call("127.0.0.1:4000", "POST", "/api/ai/complete", Some(brief()), Some("x")).await;
    assert_eq!(code, StatusCode::SERVICE_UNAVAILABLE);
    assert!(v["error"].as_str().unwrap().contains("ANTHROPIC_API_KEY"));
}

#[test]
fn the_request_is_checked_before_anything_is_spent() {
    let ok: AiCompleteReq = serde_json::from_value(brief()).unwrap();
    assert!(check_ai_request(&ok).is_ok());
    let with = |patch: serde_json::Value| {
        let mut v = brief();
        for (k, x) in patch.as_object().unwrap() {
            v[k] = x.clone();
        }
        check_ai_request(&serde_json::from_value(v).unwrap())
    };
    assert!(with(serde_json::json!({ "job": "Daily Brief!" })).is_err());
    assert!(with(serde_json::json!({ "model": "gpt-5.6" })).unwrap_err().contains("unknown model"));
    assert!(with(serde_json::json!({ "model": "claude-sonnet-5-5" })).is_ok());
    assert!(with(serde_json::json!({ "maxTokens": 0 })).is_err());
    assert!(with(serde_json::json!({ "maxTokens": 64000 })).is_err());
    assert!(with(serde_json::json!({ "maxTokens": 32000, "model": "claude-opus-5-5" })).is_ok(), "the research director");
    assert!(with(serde_json::json!({ "user": "  " })).is_err());
    assert!(with(serde_json::json!({ "user": "x".repeat(500_000) })).is_ok(), "every study summary fits");
    assert!(with(serde_json::json!({ "user": "x".repeat(900_000) })).unwrap_err().contains("too long"));
}

#[test]
fn the_caller_token_proves_the_key_without_sending_it() {
    let t = pythia_core::ai_budget::caller_token("sk-test");
    // The same value lab/ai/engine.py computes (tests/test_ai.py pins it too).
    assert_eq!(t, "61fcf2d7f8fdb52a7489f7821d53c9e5250d5d42b0902a47a6c7b7fe3aefc224");
    assert!(!t.contains("sk-test"));
    assert_ne!(t, pythia_core::ai_budget::caller_token("sk-other"));
    assert_eq!(pythia_core::ai_budget::caller_token("  "), "");
}

#[tokio::test]
async fn the_budget_reads_and_refuses_a_bad_cap() {
    let (code, v) = call("127.0.0.1:4000", "GET", "/api/ai/budget", None, None).await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["defaults"]["lifetimeUsd"], 90.0);
    assert_eq!(v["defaults"]["monthlyUsd"], 15.0);
    assert_eq!(v["defaults"]["dailyUsd"], 1.5);
    assert_eq!(v["models"]["routine"], "claude-haiku-5-5");
    assert_eq!(v["models"]["review"], "claude-sonnet-5-5");
    assert!(v["keyConfigured"].is_boolean());
    assert!(v.get("apiKey").is_none());

    let (code, v) = call("127.0.0.1:4000", "POST", "/api/ai/budget", Some(serde_json::json!({ "dailyUsd": -1 })), None).await;
    assert_eq!(code, StatusCode::BAD_REQUEST);
    assert!(v["error"].as_str().unwrap().contains("0 to"));
}

#[tokio::test]
async fn the_report_is_null_until_the_jobs_have_run() {
    let (code, v) = call("127.0.0.1:4000", "GET", "/api/ai/report", None, None).await;
    assert_eq!(code, StatusCode::OK);
    assert!(v.get("brief").is_some() && v.get("scores").is_some() && v.get("weekly").is_some());
}
