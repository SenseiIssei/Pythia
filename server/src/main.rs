//! Pythia standalone backend.
//!
//! Hosts the SAME `pythia_core` engine the desktop app runs, but over the
//! network instead of Tauri IPC — so a web dashboard, a phone app, or the
//! desktop shell can all connect to one authoritative brain.
//!
//!   GET  /api/health           → liveness
//!   GET  /api/state            → current EngineState (JSON, camelCase)
//!   GET  /api/stream           → WebSocket: full EngineState pushed every tick
//!   POST /api/command          → mutate the engine (see `Command`)
//!   POST /api/claude/signal    → ask Claude for a structured signal (env-gated)
//!
//! Paper-first, exactly like the desktop app: real money stays gated behind the
//! same sovereign risk manager and vault. This process only ever runs the
//! simulated matching engine.

use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use tokio::sync::broadcast;
use tower_http::cors::CorsLayer;

use pythia_core::connectors::alpaca::{AlpacaAccount, AlpacaConnector};
use pythia_core::connectors::{MarketConnector, OrderRequest, OrderType, Side};
use pythia_core::engine::{Engine, EngineState, LiveOrderOut, RiskLimits, StrategyConfig, StrategyState};
use pythia_core::llm::{self, LlmConfig, Provider};
use pythia_core::{alerts, marketdata};

/// Shared server state. The engine lives behind a Mutex (locked only briefly,
/// never across an await); `tx` fans out each tick's serialized state to every
/// connected WebSocket.
#[derive(Clone)]
struct AppState {
    engine: Arc<Mutex<Engine>>,
    tx: broadcast::Sender<String>,
    webhook: Arc<Mutex<Option<String>>>,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "pythia_server=info,tower_http=warn".into()),
        )
        .init();

    let (tx, _rx) = broadcast::channel::<String>(64);
    let state = AppState {
        engine: Arc::new(Mutex::new(Engine::new())),
        tx: tx.clone(),
        webhook: Arc::new(Mutex::new(std::env::var("PYTHIA_WEBHOOK_URL").ok())),
    };

    // The engine daemon — the network analog of the desktop tick loop.
    tokio::spawn(tick_loop(state.clone()));

    let app = Router::new()
        .route("/api/health", get(health))
        .route("/api/state", get(get_state))
        .route("/api/stream", get(ws_stream))
        .route("/api/command", post(post_command))
        .route("/api/llm/providers", get(get_llm_providers))
        .route("/api/llm/signal", post(post_llm_signal))
        .route("/api/live/config", post(post_live_config))
        .route("/api/live/account", get(get_live_account))
        // The dashboards are served from a different origin in dev; allow them.
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = std::env::var("PYTHIA_BIND").unwrap_or_else(|_| "0.0.0.0:8787".into());
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .unwrap_or_else(|e| panic!("cannot bind {addr}: {e}"));
    tracing::info!("Pythia backend listening on http://{addr}");
    let configured: Vec<&str> = Provider::ALL
        .iter()
        .filter(|p| p.needs_key() && p.configured_in_env())
        .map(|p| p.id())
        .collect();
    if configured.is_empty() {
        tracing::info!("LLM providers: none configured (set e.g. ANTHROPIC_API_KEY / OPENAI_API_KEY / XAI_API_KEY / ZAI_API_KEY)");
    } else {
        tracing::info!("LLM providers configured: {}", configured.join(", "));
    }

    axum::serve(listener, app).await.unwrap();
}

/// Tick the engine ~every 1.5s, refresh real read-only feeds periodically, and
/// broadcast the fresh state + flush any queued alerts. Mirrors the desktop
/// daemon in `src-tauri/src/lib.rs`.
async fn tick_loop(state: AppState) {
    let mut interval = tokio::time::interval(Duration::from_millis(1500));
    let mut n: u64 = 0;
    loop {
        interval.tick().await;
        n += 1;

        // Refresh real market data on the first tick and every ~12s. Awaits
        // happen here with no lock held.
        if n % 8 == 1 {
            let kraken = marketdata::fetch_kraken().await;
            let poly = marketdata::fetch_polymarket().await;
            let mut e = state.engine.lock().unwrap();
            e.apply_kraken(&kraken);
            e.apply_polymarket(&poly);
        }

        let (json, queued) = {
            let mut e = state.engine.lock().unwrap();
            e.tick();
            (serde_json::to_string(&e.state()).unwrap_or_default(), e.drain_alerts())
        };
        // Ignore the "no receivers" error — clients come and go.
        let _ = state.tx.send(json);

        if !queued.is_empty() {
            let url = state.webhook.lock().unwrap().clone();
            if let Some(url) = url.filter(|u| !u.is_empty()) {
                alerts::post(&url, &queued.join("\n")).await;
            }
        }

        // Submit any armed live orders (Alpaca). Keys come from the server env.
        let live_orders = { state.engine.lock().unwrap().drain_live_orders() };
        for o in live_orders {
            submit_live_order(&state, o).await;
        }
    }
}

/// Submit one live order to Alpaca (keys from env) and apply the result back to
/// the engine. Dry-run and missing-key cases resolve without any network call.
async fn submit_live_order(state: &AppState, o: LiveOrderOut) {
    if o.dry_run {
        state.engine.lock().unwrap().apply_live_reject(&o.order_id, "dry-run: not submitted");
    } else {
        let conn = AlpacaConnector::from_fields(|k| std::env::var(k).ok(), o.paper);
        if !conn.is_live_ready() {
            state.engine.lock().unwrap().apply_live_reject(
                &o.order_id,
                "Alpaca keys not set (APCA_API_KEY_ID / APCA_API_SECRET_KEY)",
            );
        } else {
            let req = OrderRequest {
                market_id: o.symbol.clone(),
                side: o.side,
                order_type: OrderType::Market,
                qty: o.qty,
                limit_price: None,
            };
            match conn.place_order(req).await {
                Ok(fill) => state.engine.lock().unwrap().apply_live_fill(&o.order_id, fill.qty, fill.price),
                Err(e) => state.engine.lock().unwrap().apply_live_reject(&o.order_id, &e.to_string()),
            }
        }
    }
    // Push the updated state so listeners see the fill/rejection promptly.
    let s = serde_json::to_string(&state.engine.lock().unwrap().state()).unwrap_or_default();
    let _ = state.tx.send(s);
}

async fn health() -> &'static str {
    "ok"
}

async fn get_state(State(st): State<AppState>) -> Json<EngineState> {
    let dto = st.engine.lock().unwrap().state();
    Json(dto)
}

/// WebSocket: push the current state immediately, then every broadcast tick.
async fn ws_stream(ws: WebSocketUpgrade, State(st): State<AppState>) -> impl IntoResponse {
    ws.on_upgrade(move |socket| ws_task(socket, st))
}

async fn ws_task(mut socket: WebSocket, st: AppState) {
    let mut rx = st.tx.subscribe();

    // Send a snapshot right away so the client renders without waiting a tick.
    let snapshot = serde_json::to_string(&st.engine.lock().unwrap().state()).unwrap_or_default();
    if socket.send(Message::Text(snapshot)).await.is_err() {
        return;
    }

    loop {
        tokio::select! {
            msg = rx.recv() => match msg {
                Ok(text) => {
                    if socket.send(Message::Text(text)).await.is_err() {
                        break; // client gone
                    }
                }
                // Lagged behind the broadcast buffer — resync from live state.
                Err(broadcast::error::RecvError::Lagged(_)) => {
                    let live = serde_json::to_string(&st.engine.lock().unwrap().state())
                        .unwrap_or_default();
                    if socket.send(Message::Text(live)).await.is_err() {
                        break;
                    }
                }
                Err(broadcast::error::RecvError::Closed) => break,
            },
            // Drain inbound frames so pings/closes are handled; ignore contents.
            inbound = socket.recv() => match inbound {
                Some(Ok(_)) => {}
                _ => break,
            },
        }
    }
}

/// The mutation surface — the network mirror of the Tauri commands. One tagged
/// enum keeps the wire contract explicit and matches the frontend EngineClient.
#[derive(Debug, Deserialize)]
#[serde(tag = "cmd", rename_all = "camelCase", rename_all_fields = "camelCase")]
enum Command {
    ToggleKill,
    SetLimits { patch: RiskLimits },
    SetStrategyState { id: String, state: StrategyState },
    SetStrategyParam { id: String, key: String, value: f64 },
    AddStrategy { cfg: StrategyConfig },
    ManualOrder { market_id: String, side: Side, notional: f64 },
    Flatten { market_id: String },
}

/// Apply a command and return the fresh state so the caller updates instantly
/// (WebSocket clients also get it on the next tick).
async fn post_command(
    State(st): State<AppState>,
    Json(cmd): Json<Command>,
) -> Json<EngineState> {
    let dto = {
        let mut e = st.engine.lock().unwrap();
        match cmd {
            Command::ToggleKill => e.toggle_kill(),
            Command::SetLimits { patch } => e.set_limits(patch),
            Command::SetStrategyState { id, state } => e.set_strategy_state(&id, state),
            Command::SetStrategyParam { id, key, value } => e.set_strategy_param(&id, &key, value),
            Command::AddStrategy { cfg } => e.add_strategy(cfg),
            Command::ManualOrder { market_id, side, notional } => {
                e.manual_order(&market_id, side, notional)
            }
            Command::Flatten { market_id } => e.flatten(&market_id),
        }
        // Push the mutated state to every stream listener too.
        let s = e.state();
        let _ = st.tx.send(serde_json::to_string(&s).unwrap_or_default());
        s
    };
    Json(dto)
}

/// List every supported provider and whether the server has a key for it (from
/// the environment). The frontend uses this to populate the model picker.
async fn get_llm_providers() -> impl IntoResponse {
    Json(llm::providers_from_env())
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LiveConfigReq {
    armed: bool,
    #[serde(default = "default_true")]
    paper: bool,
    #[serde(default)]
    dry_run: bool,
}
fn default_true() -> bool {
    true
}

/// Arm/disarm live execution. Returns fresh state so the UI reflects it at once.
async fn post_live_config(
    State(st): State<AppState>,
    Json(req): Json<LiveConfigReq>,
) -> Json<EngineState> {
    let dto = {
        let mut e = st.engine.lock().unwrap();
        e.set_live(req.armed, req.paper, req.dry_run);
        let s = e.state();
        let _ = st.tx.send(serde_json::to_string(&s).unwrap_or_default());
        s
    };
    Json(dto)
}

#[derive(Debug, Deserialize)]
struct AccountQuery {
    #[serde(default = "default_true")]
    paper: bool,
}

/// Read-only Alpaca account check (buying power, status) for the "test
/// connection" button. Keys come from the server env.
async fn get_live_account(axum::extract::Query(q): axum::extract::Query<AccountQuery>) -> impl IntoResponse {
    let conn = AlpacaConnector::from_fields(|k| std::env::var(k).ok(), q.paper);
    if !conn.is_live_ready() {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            "Alpaca keys not set (APCA_API_KEY_ID / APCA_API_SECRET_KEY)",
        )
            .into_response();
    }
    match conn.account().await {
        Ok(acct) => (StatusCode::OK, Json::<AlpacaAccount>(acct)).into_response(),
        Err(e) => (StatusCode::BAD_GATEWAY, format!("alpaca: {e}")).into_response(),
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LlmReq {
    /// Provider id (e.g. "anthropic", "openai", "xai", "zai"). Default: the
    /// first env-configured provider, else anthropic.
    #[serde(default)]
    provider: Option<String>,
    /// Model override; empty → the provider's default.
    #[serde(default)]
    model: Option<String>,
    /// Caller-built market context: question/symbol, price/odds, recent moves,
    /// any news. Kept opaque so the model can weigh whatever the caller surfaces.
    context: String,
}

/// Ask a provider for a structured signal. The server supplies the key from its
/// environment; the client never sends secrets. 503 when no key is configured,
/// 502 on any upstream/parse failure — the engine treats absence as "no opinion".
async fn post_llm_signal(Json(req): Json<LlmReq>) -> impl IntoResponse {
    // Resolve the provider: explicit request, else the first configured one.
    let provider = match req.provider.as_deref() {
        Some(p) => match Provider::parse(p) {
            Some(p) => p,
            None => {
                return (StatusCode::BAD_REQUEST, format!("unknown provider: {p}")).into_response()
            }
        },
        None => Provider::ALL
            .into_iter()
            .find(|p| p.needs_key() && p.configured_in_env())
            .unwrap_or(Provider::Anthropic),
    };

    let key = std::env::var(provider.env_key()).unwrap_or_default();
    if provider.needs_key() && key.trim().is_empty() {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            format!(
                "{} not configured — set {} on the server",
                provider.id(),
                provider.env_key()
            ),
        )
            .into_response();
    }

    let cfg = LlmConfig::new(provider, req.model.unwrap_or_default(), key);
    match llm::signal(&cfg, &req.context).await {
        Ok(sig) => (StatusCode::OK, Json(sig)).into_response(),
        Err(e) => {
            tracing::warn!("llm signal failed: {e}");
            (StatusCode::BAD_GATEWAY, format!("llm error: {e}")).into_response()
        }
    }
}
