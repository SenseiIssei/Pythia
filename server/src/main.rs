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

use pythia_core::connectors::Side;
use pythia_core::engine::{Engine, EngineState, RiskLimits, StrategyConfig, StrategyState};
use pythia_core::{alerts, claude, marketdata};

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
        .route("/api/claude/signal", post(post_claude_signal))
        // The dashboards are served from a different origin in dev; allow them.
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = std::env::var("PYTHIA_BIND").unwrap_or_else(|_| "0.0.0.0:8787".into());
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .unwrap_or_else(|e| panic!("cannot bind {addr}: {e}"));
    tracing::info!("Pythia backend listening on http://{addr}");
    if claude::is_configured() {
        tracing::info!("Claude signal provider: ENABLED (ANTHROPIC_API_KEY present)");
    } else {
        tracing::info!("Claude signal provider: disabled (set ANTHROPIC_API_KEY to enable)");
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
    }
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

#[derive(Debug, Deserialize)]
struct ClaudeReq {
    /// Caller-built market context: question/symbol, price/odds, recent moves,
    /// any news. Kept opaque so the model can weigh whatever the caller surfaces.
    context: String,
}

/// Ask Claude for a structured signal. 503 when the key isn't configured, 502
/// on any upstream/parse failure — the engine treats absence as "no opinion".
async fn post_claude_signal(Json(req): Json<ClaudeReq>) -> impl IntoResponse {
    match claude::signal(&req.context).await {
        Ok(sig) => (StatusCode::OK, Json(sig)).into_response(),
        Err(claude::ClaudeError::NotConfigured) => (
            StatusCode::SERVICE_UNAVAILABLE,
            "Claude disabled — set ANTHROPIC_API_KEY on the server",
        )
            .into_response(),
        Err(e) => {
            tracing::warn!("claude signal failed: {e}");
            (StatusCode::BAD_GATEWAY, format!("claude error: {e}")).into_response()
        }
    }
}
