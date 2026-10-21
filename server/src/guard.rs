//! Request guards for the HTTP API: which browser origins may call it, which
//! host names it answers to, and whether a caller came through a proxy.
//!
//! The API has no login of its own. It is meant to listen on 127.0.0.1 and,
//! when it has to be reached from elsewhere, to sit behind a reverse proxy
//! that authenticates (see SECURITY.md). These guards close the holes that
//! remain on a single machine:
//!
//! - **Cross-site requests.** Any web page the owner opens can send requests
//!   to `http://127.0.0.1:8787`. CORS only stops the page from *reading* the
//!   answer; a plain `POST` (the kill switch, an alert test) still runs. So a
//!   state-changing request, and the WebSocket, are refused when the browser
//!   says they come from an origin that is not allowed.
//! - **DNS rebinding.** A page on `evil.example` that re-points its own name
//!   at 127.0.0.1 makes its requests same-origin, so the browser sends no
//!   `Origin` on a GET. The `Host` header still says `evil.example`; only
//!   loopback names, IP literals and configured names are answered.
//! - **Proxied callers.** Behind a reverse proxy on the same machine, every
//!   caller arrives from 127.0.0.1. The local-only endpoints (lab events, the
//!   lab's metered AI calls) therefore refuse a request that carries proxy
//!   headers.
//!
//! Configuration: `PYTHIA_ALLOWED_ORIGINS` (comma separated, e.g.
//! `https://pythia.example.org`) adds browser origins; `PYTHIA_ALLOWED_HOSTS`
//! (comma separated host names, or `*` to switch the host check off) adds
//! names the server answers to. The hosts of the allowed origins are added
//! to the allowed hosts.

use axum::{
    extract::{Request, State},
    http::{header, HeaderMap, HeaderValue, Method, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use std::sync::Arc;
use tower_http::cors::{AllowOrigin, CorsLayer};

/// What the guards allow besides loopback.
#[derive(Debug, Clone, Default)]
pub struct GuardConfig {
    /// Extra browser origins, exactly as the browser sends them
    /// (`scheme://host[:port]`), lower case, without a trailing slash.
    pub origins: Vec<String>,
    /// Extra host names (without port), lower case.
    pub hosts: Vec<String>,
    /// `PYTHIA_ALLOWED_HOSTS=*`: answer any Host.
    pub any_host: bool,
}

impl GuardConfig {
    /// From `PYTHIA_ALLOWED_ORIGINS` and `PYTHIA_ALLOWED_HOSTS`.
    pub fn from_env() -> Self {
        Self::from_vars(
            std::env::var("PYTHIA_ALLOWED_ORIGINS").ok().as_deref(),
            std::env::var("PYTHIA_ALLOWED_HOSTS").ok().as_deref(),
        )
    }

    pub fn from_vars(origins: Option<&str>, hosts: Option<&str>) -> Self {
        let list = |v: Option<&str>| -> Vec<String> {
            v.unwrap_or_default()
                .split(',')
                .map(|s| s.trim().trim_end_matches('/').to_ascii_lowercase())
                .filter(|s| !s.is_empty())
                .collect()
        };
        let origins = list(origins);
        let raw_hosts = list(hosts);
        let any_host = raw_hosts.iter().any(|h| h == "*");
        let mut hosts: Vec<String> = raw_hosts.into_iter().filter(|h| h != "*").collect();
        hosts.extend(origins.iter().filter_map(|o| origin_host(o)));
        hosts.sort();
        hosts.dedup();
        Self { origins, hosts, any_host }
    }

    /// Whether a browser origin may call the API.
    pub fn origin_allowed(&self, origin: &str) -> bool {
        let o = origin.trim().trim_end_matches('/').to_ascii_lowercase();
        if matches!(o.as_str(), "tauri://localhost" | "http://tauri.localhost" | "https://tauri.localhost") {
            return true;
        }
        if self.origins.iter().any(|a| *a == o) {
            return true;
        }
        // Any port on a loopback name: the Vite dev server, a local dashboard.
        o.starts_with("http://") && origin_host(&o).is_some_and(|h| is_loopback_name(&h))
    }

    /// Whether the API answers a request with this `Host` header.
    pub fn host_allowed(&self, host: &str) -> bool {
        if self.any_host {
            return true;
        }
        let Some(name) = host_name(host) else { return false };
        is_loopback_name(&name)
            || name.parse::<std::net::IpAddr>().is_ok()
            || name == "host.docker.internal"
            || self.hosts.iter().any(|h| *h == name)
    }
}

/// `localhost`, `*.localhost`, 127.0.0.0/8 and ::1.
fn is_loopback_name(name: &str) -> bool {
    name == "localhost"
        || name.ends_with(".localhost")
        || name.parse::<std::net::IpAddr>().is_ok_and(|ip| ip.to_canonical().is_loopback())
}

/// The host of `scheme://host[:port]`, lower case, brackets of an IPv6
/// literal removed.
fn origin_host(origin: &str) -> Option<String> {
    let rest = origin.split_once("://")?.1;
    let authority = rest.split(['/', '?', '#']).next().unwrap_or_default();
    host_name(authority)
}

/// The name in a `Host` value (`name`, `name:port`, `[v6]:port`).
fn host_name(host: &str) -> Option<String> {
    let h = host.trim().to_ascii_lowercase();
    if h.is_empty() || h.contains('@') {
        return None;
    }
    if let Some(v6) = h.strip_prefix('[') {
        return v6.split(']').next().map(str::to_string).filter(|s| !s.is_empty());
    }
    // A bare IPv6 literal has more than one colon and no port.
    if h.matches(':').count() > 1 {
        return Some(h);
    }
    Some(h.split(':').next().unwrap_or_default().to_string()).filter(|s| !s.is_empty())
}

/// Whether a request changes something, from the guard's point of view:
/// everything but GET, HEAD and OPTIONS, and every WebSocket upgrade (the
/// state stream is readable cross-site otherwise, since browsers apply no
/// CORS to WebSockets).
fn needs_origin_check(method: &Method, headers: &HeaderMap) -> bool {
    let upgrade = headers
        .get(header::UPGRADE)
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.eq_ignore_ascii_case("websocket"));
    upgrade || !matches!(*method, Method::GET | Method::HEAD | Method::OPTIONS)
}

fn refuse(msg: &str) -> Response {
    (StatusCode::FORBIDDEN, Json(serde_json::json!({ "error": msg }))).into_response()
}

/// The guard as an axum middleware: the Host check on every request, the
/// Origin check on state-changing ones and WebSockets, and `nosniff` on
/// every answer.
pub async fn guard(State(cfg): State<Arc<GuardConfig>>, req: Request, next: Next) -> Response {
    let headers = req.headers();
    if let Some(host) = headers.get(header::HOST).and_then(|v| v.to_str().ok()) {
        if !cfg.host_allowed(host) {
            return refuse("this host name is not served (see PYTHIA_ALLOWED_HOSTS)");
        }
    }
    if needs_origin_check(req.method(), headers) {
        if let Some(origin) = headers.get(header::ORIGIN) {
            let ok = origin.to_str().is_ok_and(|o| cfg.origin_allowed(o));
            if !ok {
                return refuse("requests from this web origin are not accepted (see PYTHIA_ALLOWED_ORIGINS)");
            }
        }
    }
    let mut resp = next.run(req).await;
    resp.headers_mut().insert(header::X_CONTENT_TYPE_OPTIONS, HeaderValue::from_static("nosniff"));
    resp
}

/// CORS for the allowed origins only (the dashboards run on another port in
/// development). Replaces the old permissive layer, which let any web page
/// read the engine state and the account answers.
pub fn cors(cfg: Arc<GuardConfig>) -> CorsLayer {
    CorsLayer::new()
        .allow_origin(AllowOrigin::predicate(move |origin: &HeaderValue, _| {
            origin.to_str().is_ok_and(|o| cfg.origin_allowed(o))
        }))
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers([header::CONTENT_TYPE])
}

/// Whether a request came through a proxy (it carries a forwarding header).
/// A proxy on the same machine makes every caller look like 127.0.0.1, so the
/// local-only endpoints refuse these.
pub fn proxied(headers: &HeaderMap) -> bool {
    ["forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip"].iter().any(|h| headers.contains_key(*h))
}

/// Compare two secrets in time that does not depend on where they differ.
pub fn same_secret(a: &str, b: &str) -> bool {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}
