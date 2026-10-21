//! The request guards: origins, host names, proxied callers, the token compare.

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
        alert_files: Arc::new(AlertFiles::default()),
        creds: Arc::new(credentials_from(&|_| None)),
    }
}

fn cfg() -> guard::GuardConfig {
    guard::GuardConfig::from_vars(Some("https://pythia.example.org/"), Some("pythia-box"))
}

async fn send(req: Request<Body>) -> (StatusCode, axum::http::HeaderMap, serde_json::Value) {
    let peer: std::net::SocketAddr = "127.0.0.1:5000".parse().unwrap();
    let mut req = req;
    req.extensions_mut().insert(axum::extract::ConnectInfo(peer));
    let resp = app(state(), Arc::new(cfg())).oneshot(req).await.unwrap();
    let code = resp.status();
    let headers = resp.headers().clone();
    let bytes = to_bytes(resp.into_body(), 1 << 22).await.unwrap();
    (code, headers, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
}

fn post(uri: &str, origin: Option<&str>) -> Request<Body> {
    let mut b = Request::builder().method("POST").uri(uri).header("host", "127.0.0.1:8787");
    if let Some(o) = origin {
        b = b.header("origin", o);
    }
    b.header("content-type", "application/json").body(Body::from("{\"minutes\":0}")).unwrap()
}

#[test]
fn loopback_tauri_and_listed_origins_are_allowed_and_nothing_else() {
    let c = cfg();
    for ok in [
        "http://localhost:5174",
        "http://127.0.0.1:8787",
        "http://[::1]:5174",
        "http://app.localhost:3000",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "https://pythia.example.org",
        "HTTPS://Pythia.Example.org/",
    ] {
        assert!(c.origin_allowed(ok), "{ok}");
    }
    for bad in [
        "https://evil.example",
        "null",
        "http://localhost.evil.example",
        "http://127.0.0.1.evil.example",
        "https://pythia.example.org.evil.example",
        "http://pythia.example.org",
        "file://",
        "",
    ] {
        assert!(!c.origin_allowed(bad), "{bad}");
    }
}

#[test]
fn loopback_names_ip_literals_and_listed_hosts_are_served_and_rebound_names_are_not() {
    let c = cfg();
    for ok in [
        "127.0.0.1:8787",
        "localhost",
        "localhost:8788",
        "[::1]:8787",
        "::1",
        "172.17.0.1:8788",
        "10.0.0.5",
        "host.docker.internal:8787",
        "pythia-box:8787",
        "pythia.example.org",
    ] {
        assert!(c.host_allowed(ok), "{ok}");
    }
    for bad in ["evil.example", "evil.example:8787", "localhost.evil.example", "user@127.0.0.1", ""] {
        assert!(!c.host_allowed(bad), "{bad}");
    }
    assert!(guard::GuardConfig::from_vars(None, Some("*")).host_allowed("anything.example"));
}

#[tokio::test]
async fn a_cross_site_post_is_refused_before_it_changes_anything() {
    // The kill switch and the mute are plain POSTs a foreign page could send.
    for uri in ["/api/alerts/mute", "/api/pumpfun/live/kill", "/api/command", "/api/live/config"] {
        let (code, _, v) = send(post(uri, Some("https://evil.example"))).await;
        assert_eq!(code, StatusCode::FORBIDDEN, "{uri}");
        assert!(v["error"].as_str().unwrap().contains("web origin"), "{uri}: {v}");
    }
    // From the dashboard's dev origin, and from a script with no Origin, it goes through.
    let (code, _, v) = send(post("/api/alerts/mute", Some("http://localhost:5174"))).await;
    assert_eq!(code, StatusCode::OK, "{v}");
    let (code, _, _) = send(post("/api/alerts/mute", None)).await;
    assert_eq!(code, StatusCode::OK);
}

#[tokio::test]
async fn a_rebound_host_name_gets_nothing_not_even_a_read() {
    let req = Request::builder().uri("/api/health").header("host", "evil.example:8787").body(Body::empty()).unwrap();
    let (code, _, v) = send(req).await;
    assert_eq!(code, StatusCode::FORBIDDEN);
    assert!(v["error"].as_str().unwrap().contains("host name"));
    let req = Request::builder().uri("/api/health").header("host", "127.0.0.1:8787").body(Body::empty()).unwrap();
    let (code, headers, _) = send(req).await;
    assert_eq!(code, StatusCode::OK);
    assert_eq!(headers.get("x-content-type-options").unwrap(), "nosniff");
}

#[tokio::test]
async fn the_state_stream_refuses_a_foreign_page() {
    let ws = |origin: &str| {
        Request::builder()
            .uri("/api/stream")
            .header("host", "127.0.0.1:8787")
            .header("origin", origin)
            .header("connection", "upgrade")
            .header("upgrade", "websocket")
            .header("sec-websocket-version", "13")
            // The sample nonce from RFC 6455, not a credential.
            .header("sec-websocket-key", "dGhlIHNhbXBsZSBub25jZQ==") // gitleaks:allow
            .body(Body::empty())
            .unwrap()
    };
    let (code, _, _) = send(ws("https://evil.example")).await;
    assert_eq!(code, StatusCode::FORBIDDEN);
    // An allowed origin passes the guard (the test transport cannot upgrade).
    let (code, _, _) = send(ws("http://localhost:5174")).await;
    assert_ne!(code, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn cors_answers_allowed_origins_only() {
    let preflight = |origin: &str| {
        Request::builder()
            .method("OPTIONS")
            .uri("/api/command")
            .header("host", "127.0.0.1:8787")
            .header("origin", origin)
            .header("access-control-request-method", "POST")
            .header("access-control-request-headers", "content-type")
            .body(Body::empty())
            .unwrap()
    };
    let (_, h, _) = send(preflight("http://localhost:5174")).await;
    assert_eq!(h.get("access-control-allow-origin").unwrap(), "http://localhost:5174");
    let (_, h, _) = send(preflight("https://evil.example")).await;
    assert!(h.get("access-control-allow-origin").is_none(), "{h:?}");
    // A read from a foreign page gets no CORS header, so the browser hides the answer.
    let req = Request::builder()
        .uri("/api/health")
        .header("host", "127.0.0.1:8787")
        .header("origin", "https://evil.example")
        .body(Body::empty())
        .unwrap();
    let (_, h, _) = send(req).await;
    assert!(h.get("access-control-allow-origin").is_none());
}

#[tokio::test]
async fn a_proxied_request_is_not_local_even_from_127_0_0_1() {
    for uri in ["/api/alerts/event", "/api/ai/complete"] {
        let req = Request::builder()
            .method("POST")
            .uri(uri)
            .header("host", "127.0.0.1:8787")
            .header("x-forwarded-for", "203.0.113.9")
            .header("content-type", "application/json")
            .body(Body::from(
                serde_json::json!({ "category": "lab", "title": "t", "job": "brief", "system": "s", "user": "u", "maxTokens": 10 })
                    .to_string(),
            ))
            .unwrap();
        let (code, _, v) = send(req).await;
        // The AI body is not an event and vice versa; the 403 must come first either way.
        assert!(code == StatusCode::FORBIDDEN || code == StatusCode::UNPROCESSABLE_ENTITY, "{uri}: {code} {v}");
        if code == StatusCode::FORBIDDEN {
            assert!(v["error"].as_str().unwrap().contains("this machine"), "{uri}: {v}");
        }
    }
    let event = serde_json::json!({ "category": "lab", "title": "t" });
    let req = Request::builder()
        .method("POST")
        .uri("/api/alerts/event")
        .header("host", "127.0.0.1:8787")
        .header("forwarded", "for=203.0.113.9")
        .header("content-type", "application/json")
        .body(Body::from(event.to_string()))
        .unwrap();
    let (code, _, _) = send(req).await;
    assert_eq!(code, StatusCode::FORBIDDEN);
}

#[test]
fn the_token_compare_needs_the_whole_secret() {
    assert!(guard::same_secret("abc123", "abc123"));
    assert!(!guard::same_secret("abc123", "abc124"));
    assert!(!guard::same_secret("abc12", "abc123"));
    assert!(!guard::same_secret("", "abc123"));
}

#[test]
fn the_server_listens_on_loopback_unless_told_otherwise() {
    assert_eq!(DEFAULT_BIND, "127.0.0.1:8787");
}
