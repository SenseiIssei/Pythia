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
use pythia_core::connectors::cex::{self, Exchange};
use pythia_core::connectors::{Side, Venue};
use pythia_core::engine::{Engine, EngineState, LiveConfig, RiskLimits, StrategyConfig, StrategyState};
use pythia_core::execution::{self, Credentials};
use pythia_core::forecast::ForecastConfig;
use pythia_core::llm::{self, LlmConfig, Provider};
use pythia_core::predict::{self, EnsembleKeys};
use pythia_core::wallets::{self, WalletSources, WatchedAddress};
use pythia_core::{alerts, marketdata};

/// Shared server state. The engine lives behind a Mutex (locked only briefly,
/// never across an await); `tx` fans out each tick's serialized state to every
/// connected WebSocket.
#[derive(Clone)]
struct AppState {
    engine: Arc<Mutex<Engine>>,
    tx: broadcast::Sender<String>,
    webhook: Arc<Mutex<Option<String>>>,
    /// Venue credentials, read once from the environment at boot. Restart the
    /// server to pick up an edited `.env` — keys are not hot-reloaded, so a
    /// half-saved file can never arm a venue mid-session.
    creds: Arc<Credentials>,
}

fn env_str(key: &str) -> Option<String> {
    std::env::var(key).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty())
}

fn env_flag(key: &str) -> bool {
    matches!(env_str(key).as_deref(), Some("1" | "true" | "TRUE" | "yes" | "on"))
}

/// Assemble venue credentials from the process environment.
fn credentials_from_env() -> Credentials {
    let alpaca = match (env_str("APCA_API_KEY_ID"), env_str("APCA_API_SECRET_KEY")) {
        (Some(k), Some(s)) => Some((k, s)),
        _ => None,
    };
    // One exchange at a time — `PYTHIA_EXCHANGE` picks which.
    let exchange = env_str("PYTHIA_EXCHANGE")
        .as_deref()
        .and_then(Exchange::parse)
        .and_then(|ex| {
            let k = env_str("PYTHIA_EXCHANGE_KEY")?;
            let s = env_str("PYTHIA_EXCHANGE_SECRET")?;
            Some((ex, k, s, env_str("PYTHIA_EXCHANGE_PASSPHRASE").unwrap_or_default()))
        });
    Credentials {
        alpaca,
        exchange,
        alpaca_extended_hours: env_flag("PYTHIA_EXTENDED_HOURS"),
        alpaca_allow_shorts: env_flag("PYTHIA_ALLOW_SHORTS"),
    }
}

/// How often to run an automatic ensemble sweep, in ticks (~1.5s each).
/// `None` disables it, which is the default — model calls cost money and should
/// be an explicit choice, not something a server does quietly overnight.
fn sweep_ticks() -> Option<u64> {
    let minutes: u64 = env_str("PYTHIA_FORECAST_SWEEP_MIN")?.parse().ok()?;
    (minutes > 0).then(|| (minutes * 40).max(40)) // 40 ticks ≈ 1 minute
}

/// How many markets one sweep covers. Bounds the spend per sweep.
fn sweep_markets() -> usize {
    env_str("PYTHIA_FORECAST_SWEEP_MARKETS")
        .and_then(|v| v.parse().ok())
        .unwrap_or(3)
}

/// Watch-only on-chain addresses, as a JSON array in `PYTHIA_WALLETS`:
/// `[{"chain":"ethereum","address":"0x…","label":"cold"}]`
fn watched_addresses() -> Vec<WatchedAddress> {
    let Some(raw) = env_str("PYTHIA_WALLETS") else { return vec![] };
    match serde_json::from_str::<Vec<WatchedAddress>>(&raw) {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("PYTHIA_WALLETS is not a valid address array: {e}");
            vec![]
        }
    }
}

#[tokio::main]
async fn main() {
    // Load a local .env (gitignored) so keys never touch shell history.
    let _ = dotenvy::dotenv();
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "pythia_server=info,tower_http=warn".into()),
        )
        .init();

    let (tx, _rx) = broadcast::channel::<String>(64);
    let creds = Arc::new(credentials_from_env());
    let engine = Arc::new(Mutex::new(Engine::new()));
    // Reflect which venues actually have usable keys before the first tick, so
    // the UI never shows a venue as armable that cannot route.
    engine.lock().unwrap().set_connected(creds.connected_venues());
    let state = AppState {
        engine,
        tx: tx.clone(),
        webhook: Arc::new(Mutex::new(std::env::var("PYTHIA_WEBHOOK_URL").ok())),
        creds,
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
        .route("/api/live/verify", get(get_live_verify))
        .route("/api/exchanges", get(get_exchanges))
        .route("/api/wallets", get(get_wallets))
        .route("/api/forecast/ensemble", post(post_ensemble))
        .route("/api/forecast/config", post(post_forecast_config))
        // The dashboards are served from a different origin in dev; allow them.
        .layer(CorsLayer::permissive())
        .with_state(state.clone());

    let addr = std::env::var("PYTHIA_BIND").unwrap_or_else(|_| "0.0.0.0:8787".into());
    let listener = match tokio::net::TcpListener::bind(&addr).await {
        Ok(l) => l,
        Err(e) => {
            tracing::error!(
                "cannot bind {addr}: {e}\n\
                 → is another Pythia server already running? Stop it, or set \
                 PYTHIA_BIND to a free port in .env"
            );
            std::process::exit(1);
        }
    };
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
    // Venue preflight — what a live run actually depends on.
    if state.creds.alpaca.is_some() {
        tracing::info!(
            "Alpaca: keys present → real equity quotes ({} feed) + live execution available{}",
            std::env::var("APCA_FEED").unwrap_or_else(|_| "iex".into()),
            if state.creds.alpaca_extended_hours { " (extended hours ON)" } else { "" }
        );
    } else {
        tracing::info!("Alpaca: no keys (APCA_API_KEY_ID / APCA_API_SECRET_KEY) — equities stay simulated, live orders will be rejected");
    }
    match &state.creds.exchange {
        Some((ex, ..)) => tracing::info!("Crypto exchange: {} configured → live crypto execution available", ex.label()),
        None => tracing::info!(
            "Crypto exchange: none (set PYTHIA_EXCHANGE + PYTHIA_EXCHANGE_KEY/SECRET) — crypto stays simulated"
        ),
    }
    let watched = watched_addresses().len();
    if watched > 0 {
        tracing::info!("Wallets: watching {watched} on-chain address(es), read-only");
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
            // Real equity quotes when Alpaca keys are in the env (else stays simulated).
            let alpaca = marketdata::fetch_alpaca(
                &std::env::var("APCA_API_KEY_ID").unwrap_or_default(),
                &std::env::var("APCA_API_SECRET_KEY").unwrap_or_default(),
                &std::env::var("APCA_FEED").unwrap_or_else(|_| "iex".into()),
            )
            .await;
            let mut e = state.engine.lock().unwrap();
            e.apply_kraken(&kraken);
            e.apply_polymarket(&poly);
            e.apply_alpaca(&alpaca);
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

        // Submit new live orders and poll the ones already out. Both are
        // network calls, so they happen with no engine lock held.
        execution::cycle(&state.engine, &state.creds).await;

        // Reconcile against the broker every ~2 minutes: it is the only way to
        // notice a fill that happened while we were restarting.
        if n % 80 == 1 {
            execution::reconcile(&state.engine, &state.creds).await;
        }

        // Optional ensemble sweep. Off by default: every sweep is one API call
        // per provider per market, and that is the operator's money.
        if let Some(period) = sweep_ticks() {
            if n % period == 1 {
                let runs = predict::sweep(&state.engine, &EnsembleKeys::from_env(), sweep_markets()).await;
                let answered: usize = runs.iter().map(|r| r.answered).sum();
                if answered > 0 {
                    tracing::info!("ensemble sweep: {answered} opinion(s) across {} market(s)", runs.len());
                }
            }
        }

        // Push the post-execution state so listeners see fills promptly rather
        // than a tick later.
        let s = serde_json::to_string(&state.engine.lock().unwrap().state()).unwrap_or_default();
        let _ = state.tx.send(s);
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
    /// Let the execution policy rest orders inside the spread and learn from
    /// what they cost. Off by default.
    SetAdaptiveExecution { on: bool },
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
            Command::SetAdaptiveExecution { on } => e.set_adaptive_execution(on),
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
    /// Which venues may route. Omitted means Alpaca only — the historical
    /// behaviour, and the conservative one.
    #[serde(default)]
    venues: Option<Vec<Venue>>,
    #[serde(default)]
    timeout_sec: Option<u64>,
}
fn default_true() -> bool {
    true
}

/// Arm/disarm live execution. Returns fresh state so the UI reflects it at once.
///
/// Arming is refused unless every requested venue answers a read-only account
/// check first. Discovering a bad key when the first signal fires — with the
/// order already gone — is exactly the failure this prevents.
async fn post_live_config(
    State(st): State<AppState>,
    Json(req): Json<LiveConfigReq>,
) -> impl IntoResponse {
    let defaults = LiveConfig::default();
    let cfg = LiveConfig {
        armed: req.armed,
        paper: req.paper,
        dry_run: req.dry_run,
        venues: req.venues.unwrap_or(defaults.venues),
        timeout_sec: req.timeout_sec.unwrap_or(defaults.timeout_sec),
    };

    if cfg.armed && !cfg.dry_run {
        for venue in &cfg.venues {
            if let Err(e) = execution::verify(&st.creds, *venue, cfg.paper).await {
                return (
                    StatusCode::SERVICE_UNAVAILABLE,
                    format!("cannot arm {venue:?}: {e}"),
                )
                    .into_response();
            }
        }
    }

    let dto = {
        let mut e = st.engine.lock().unwrap();
        e.set_connected(st.creds.connected_venues());
        e.set_live(cfg);
        let s = e.state();
        let _ = st.tx.send(serde_json::to_string(&s).unwrap_or_default());
        s
    };
    // Pick up anything that filled while we were disarmed.
    execution::reconcile(&st.engine, &st.creds).await;
    Json(dto).into_response()
}

#[derive(Debug, Deserialize)]
struct AccountQuery {
    #[serde(default = "default_true")]
    paper: bool,
}

/// Read-only Alpaca account check (buying power, status) for the "test
/// connection" button. Keys come from the server env.
async fn get_live_account(
    State(st): State<AppState>,
    axum::extract::Query(q): axum::extract::Query<AccountQuery>,
) -> impl IntoResponse {
    let Some((key, secret)) = st.creds.alpaca.clone() else {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            "Alpaca keys not set (APCA_API_KEY_ID / APCA_API_SECRET_KEY)",
        )
            .into_response();
    };
    let conn = AlpacaConnector::new(Some(key), Some(secret), q.paper);
    match conn.account().await {
        Ok(acct) => (StatusCode::OK, Json::<AlpacaAccount>(acct)).into_response(),
        Err(e) => (StatusCode::BAD_GATEWAY, format!("alpaca: {e}")).into_response(),
    }
}

#[derive(Debug, Deserialize)]
struct VerifyQuery {
    venue: Venue,
    #[serde(default = "default_true")]
    paper: bool,
}

/// Read-only credential check for any venue. Never places an order.
async fn get_live_verify(
    State(st): State<AppState>,
    axum::extract::Query(q): axum::extract::Query<VerifyQuery>,
) -> impl IntoResponse {
    match execution::verify(&st.creds, q.venue, q.paper).await {
        Ok(summary) => (StatusCode::OK, Json(serde_json::json!({ "ok": true, "summary": summary }))).into_response(),
        Err(e) => (StatusCode::SERVICE_UNAVAILABLE, e).into_response(),
    }
}

/// Every exchange Pythia can route to, and whether this server has keys for it.
async fn get_exchanges(State(st): State<AppState>) -> impl IntoResponse {
    let selected = st.creds.exchange.as_ref().map(|(e, ..)| *e);
    Json(cex::exchanges_with(|e| selected == Some(e)))
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct EnsembleReq {
    market_id: String,
    /// Anything the operator wants every model to weigh.
    #[serde(default)]
    notes: String,
}

/// Ask every configured provider about one market, independently, and fold the
/// answers into that market's forecast. Costs one API call per provider.
async fn post_ensemble(State(st): State<AppState>, Json(req): Json<EnsembleReq>) -> impl IntoResponse {
    match predict::ensemble_for_market(&st.engine, &EnsembleKeys::from_env(), &req.market_id, &req.notes).await
    {
        Ok(run) => {
            let s = serde_json::to_string(&st.engine.lock().unwrap().state()).unwrap_or_default();
            let _ = st.tx.send(s);
            (StatusCode::OK, Json(run)).into_response()
        }
        Err(e) => (StatusCode::SERVICE_UNAVAILABLE, e).into_response(),
    }
}

/// Update the forecasting tunables (horizon, costs, bootstrap trust, …).
async fn post_forecast_config(
    State(st): State<AppState>,
    Json(cfg): Json<ForecastConfig>,
) -> Json<EngineState> {
    let mut e = st.engine.lock().unwrap();
    e.set_forecast_config(cfg);
    let s = e.state();
    let _ = st.tx.send(serde_json::to_string(&s).unwrap_or_default());
    Json(s)
}

/// The unified balance sheet: broker, exchange and watch-only on-chain
/// addresses. Read-only — this endpoint cannot move anything.
async fn get_wallets(State(st): State<AppState>) -> impl IntoResponse {
    let sources = WalletSources {
        alpaca: st.creds.alpaca.clone().map(|(k, s)| {
            let paper = st.engine.lock().unwrap().live_config().paper;
            (k, s, paper)
        }),
        exchanges: st
            .creds
            .exchange
            .clone()
            .map(|(ex, k, s, p)| vec![(ex, k, s, p)])
            .unwrap_or_default(),
        addresses: watched_addresses(),
    };
    Json(wallets::snapshot(&sources).await)
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
