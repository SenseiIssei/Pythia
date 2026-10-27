//! Pythia News and Lab Live: read only, from the files the lab's news and lablive jobs write.

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

async fn call(root: Option<std::path::PathBuf>, method: &str, uri: &str) -> (StatusCode, serde_json::Value) {
    let req = Request::builder().method(method).uri(uri).body(Body::empty()).unwrap();
    let resp = lab_news_routes(root).with_state(state()).oneshot(req).await.unwrap();
    let code = resp.status();
    let bytes = to_bytes(resp.into_body(), 1 << 22).await.unwrap();
    (code, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
}

fn dir(name: &str) -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!("pythia-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    d
}

fn write_news(d: &std::path::Path) {
    std::fs::create_dir_all(d.join("reports/news")).unwrap();
    let arts: Vec<serde_json::Value> = (0..25)
        .map(|i: i64| {
            let category = if i % 5 == 0 { "Warnung" } else { "Forschung" };
            let about: Vec<&str> = if i == 3 { vec!["book:tsmom"] } else { Vec::new() };
            serde_json::json!({
                "id": format!("a-{i}"), "time_ms": 1000 - i, "category": category,
                "headline": format!("H{i}"), "teaser": "T.", "body": "## Was passiert ist\n\nText.", "hash": "x",
                "about": about, "importance": 1
            })
        })
        .collect();
    let doc = serde_json::json!({ "updated_ms": 77, "categories": ["Forschung", "Warnung"], "articles": arts });
    std::fs::write(d.join("reports/news/articles.json"), doc.to_string()).unwrap();
}

#[tokio::test]
async fn the_news_list_pages_and_filters_without_bodies() {
    let d = dir("lab-news-api");
    let (code, v) = call(Some(d.clone()), "GET", "/api/lab/news").await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["found"], false);
    assert_eq!(v["total"], 0);
    write_news(&d);
    let (code, v) = call(Some(d.clone()), "GET", "/api/lab/news").await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["found"], true);
    assert_eq!(v["updated_ms"], 77);
    assert_eq!(v["total"], 25);
    assert_eq!(v["per"], 20);
    assert_eq!(v["articles"].as_array().unwrap().len(), 20);
    assert_eq!(v["articles"][0]["id"], "a-0");
    assert!(v["articles"][0].get("body").is_none(), "the list has no bodies");
    assert!(v["articles"][0].get("hash").is_none());
    let (_, v) = call(Some(d.clone()), "GET", "/api/lab/news?page=1&per=20").await;
    assert_eq!(v["articles"].as_array().unwrap().len(), 5);
    assert_eq!(v["articles"][0]["id"], "a-20");
    let (_, v) = call(Some(d.clone()), "GET", "/api/lab/news?category=Warnung").await;
    assert_eq!(v["total"], 5);
    assert!(v["articles"].as_array().unwrap().iter().all(|a| a["category"] == "Warnung"));
    let (_, v) = call(Some(d.clone()), "GET", "/api/lab/news?about=book:tsmom").await;
    assert_eq!(v["total"], 1);
    assert_eq!(v["articles"][0]["id"], "a-3");
    let (_, v) = call(Some(d.clone()), "GET", "/api/lab/news?per=1000").await;
    assert_eq!(v["per"], 100);
    // Read only: a POST is not a route.
    let (code, _) = call(Some(d.clone()), "POST", "/api/lab/news").await;
    assert_eq!(code, StatusCode::METHOD_NOT_ALLOWED);
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn one_article_with_its_body_or_404() {
    let d = dir("lab-news-one-api");
    write_news(&d);
    let (code, v) = call(Some(d.clone()), "GET", "/api/lab/news/a-7").await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["found"], true);
    assert_eq!(v["headline"], "H7");
    assert!(v["body"].as_str().unwrap().contains("Was passiert ist"));
    assert!(v.get("hash").is_none());
    let (code, v) = call(Some(d.clone()), "GET", "/api/lab/news/nope").await;
    assert_eq!(code, StatusCode::NOT_FOUND);
    assert_eq!(v["found"], false);
    let (code, _) = call(Some(d.clone()), "GET", "/api/lab/news/..%2F..%2Fetc").await;
    assert_eq!(code, StatusCode::NOT_FOUND);
    let (code, _) = call(None, "GET", "/api/lab/news/a-7").await;
    assert_eq!(code, StatusCode::NOT_FOUND);
    let (code, _) = call(Some(d.clone()), "DELETE", "/api/lab/news/a-7").await;
    assert_eq!(code, StatusCode::METHOD_NOT_ALLOWED);
    let _ = std::fs::remove_dir_all(&d);
}

#[tokio::test]
async fn lab_live_serves_the_graph_file() {
    let d = dir("lab-live-api");
    let (code, v) = call(Some(d.clone()), "GET", "/api/lab/live").await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["found"], false);
    assert!(v["nodes"].as_array().unwrap().is_empty());
    std::fs::create_dir_all(d.join("reports/lablive")).unwrap();
    std::fs::write(
        d.join("reports/lablive/latest.json"),
        r#"{"updated_ms":5,"columns":["data","models"],"nodes":[{"id":"job:features","state":"running"}],"edges":[{"from":"src:recorder","to":"job:features"}]}"#,
    )
    .unwrap();
    let (code, v) = call(Some(d.clone()), "GET", "/api/lab/live").await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(v["found"], true);
    assert_eq!(v["nodes"][0]["id"], "job:features");
    assert_eq!(v["edges"][0]["to"], "job:features");
    let (_, v) = call(None, "GET", "/api/lab/live").await;
    assert_eq!(v["found"], false);
    let (code, _) = call(Some(d.clone()), "POST", "/api/lab/live").await;
    assert_eq!(code, StatusCode::METHOD_NOT_ALLOWED);
    let _ = std::fs::remove_dir_all(&d);
}
