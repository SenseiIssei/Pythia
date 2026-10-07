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

use std::sync::{Arc, Mutex, OnceLock};
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
use pythia_core::engine::{
    AiPolicy, AiView, BrokerStatus, Engine, EngineState, LiveConfig, RiskLimits, StrategyConfig,
    StrategyState,
};
use pythia_core::execution::{self, Credentials};
use pythia_core::forecast::ForecastConfig;
use pythia_core::llm::{self, Effort, LlmConfig, Provider};
use pythia_core::predict::{self, EnsembleKeys};
use pythia_core::costs::{self, CostVenue};
use pythia_core::research::{self, backtest::BacktestConfig};
use pythia_core::validation;
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
///
/// Alpaca issues **separate** key pairs for the paper and live accounts, and
/// each only authenticates against its own endpoint. `APCA_LIVE_*` holds the
/// live pair; when it's unset the base pair is used for both, which is correct
/// for the common case of only ever running on paper.
fn credentials_from_env() -> Credentials {
    let alpaca = match (env_str("APCA_API_KEY_ID"), env_str("APCA_API_SECRET_KEY")) {
        (Some(k), Some(s)) => Some((k, s)),
        _ => None,
    };
    let alpaca_live = match (env_str("APCA_LIVE_API_KEY_ID"), env_str("APCA_LIVE_API_SECRET_KEY")) {
        (Some(k), Some(s)) => Some((k, s)),
        _ => alpaca.clone(),
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
        alpaca_live,
        exchange,
        // Marketable-limit band for Alpaca market orders; 25bps when unset.
        alpaca_slippage_bps: env_str("PYTHIA_SLIPPAGE_BPS").and_then(|v| v.parse().ok()),
        alpaca_allow_shorts: env_flag("PYTHIA_ALLOW_SHORTS"),
    }
}

/// Default for the extended-hours opt-in when an arm request does not say.
/// The Live page always says; this is for scripted arming.
fn extended_hours_default() -> bool {
    env_flag("PYTHIA_EXTENDED_HOURS")
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

/// Credentials for read-only market data. `data.alpaca.markets` is shared by
/// both accounts, so either pair works: the paper pair when present, else the
/// live one. The order path never falls back like this.
fn alpaca_data_keys(creds: &Credentials) -> (String, String, String) {
    let feed = std::env::var("APCA_FEED").unwrap_or_else(|_| "iex".into());
    let (id, secret) = creds
        .alpaca_keys(true)
        .or_else(|| creds.alpaca_keys(false))
        .cloned()
        .unwrap_or_default();
    (id, secret, feed)
}

/// Build a read-only connector for one endpoint using that endpoint's own
/// keys. An unconfigured endpoint yields a connector that fails closed with a
/// "not configured" error, which is what the status checks want to report.
fn alpaca_conn(creds: &Credentials, paper: bool) -> AlpacaConnector {
    creds
        .alpaca_connector(paper, false)
        .unwrap_or_else(|_| AlpacaConnector::new(None, None, paper))
}

/// Whether *either* endpoint has usable credentials.
///
/// Checks both pairs deliberately: someone who configured only `APCA_LIVE_*`
/// still needs the broker-status loop to run, and gating it on the paper pair
/// alone would leave a live run with a permanently stale session check, which
/// the engine then blocks entries on.
fn has_alpaca_keys(creds: &Credentials) -> bool {
    creds.alpaca_keys(true).is_some() || creds.alpaca_keys(false).is_some()
}

/// Candle interval for the indicator series. 5-minute bars are the default
/// because they are slow enough that a signal survives the round trip to the
/// broker, and fast enough to trade a session.
fn bar_timeframe() -> (String, u32) {
    let tf = std::env::var("PYTHIA_BAR_TIMEFRAME").unwrap_or_else(|_| "5Min".into());
    let kraken_min: u32 = match tf.as_str() {
        "1Min" => 1,
        "15Min" => 15,
        "30Min" => 30,
        "1Hour" => 60,
        "1Day" => 1440,
        _ => 5,
    };
    (tf, kraken_min)
}

/// Reads the lab's signal files every five minutes and hands them to the
/// engine, which rebalances each lab book once per new signal.
async fn lab_loop(state: AppState) {
    let Some(dir) = pythia_core::lab::signals_dir() else {
        tracing::info!("lab strategies: PYTHIA_SIGNALS / PYTHIA_MODELS not set, none loaded");
        return;
    };
    loop {
        let (signals, errors) = pythia_core::lab::read_all(&dir);
        for e in errors {
            tracing::warn!("lab signal skipped: {e}");
        }
        {
            let mut e = state.engine.lock().unwrap();
            for s in signals {
                e.apply_lab_signal(s);
            }
        }
        tokio::time::sleep(Duration::from_secs(300)).await;
    }
}

/// The append-only record of real fills: `PYTHIA_FILLS_FILE`, else
/// `fills.jsonl` next to the state file, else in the working directory.
fn fills_file() -> std::path::PathBuf {
    if let Ok(p) = std::env::var("PYTHIA_FILLS_FILE") {
        return p.into();
    }
    state_file()
        .and_then(|s| s.parent().map(|d| d.join("fills.jsonl")))
        .unwrap_or_else(|| "fills.jsonl".into())
}

#[derive(Deserialize)]
struct TaxQuery {
    #[serde(default)]
    format: Option<String>,
}

/// The tax record: `?format=cointracking` for the CSV import file, otherwise
/// the FIFO preview as JSON.
async fn get_tax(axum::extract::Query(q): axum::extract::Query<TaxQuery>) -> impl IntoResponse {
    let (fills, bad) = pythia_core::tax::read_all(&fills_file());
    if q.format.as_deref() == Some("cointracking") {
        let exchange = std::env::var("PYTHIA_EXCHANGE").unwrap_or_else(|_| "Kraken".into());
        return (
            [(axum::http::header::CONTENT_TYPE, "text/csv; charset=utf-8")],
            pythia_core::tax::cointracking_csv(&fills, &exchange),
        )
            .into_response();
    }
    let mut v = serde_json::to_value(pythia_core::tax::fifo_summary(&fills)).unwrap_or_default();
    v["damagedLines"] = bad.into();
    Json(v).into_response()
}

/// Where the engine state is saved, if anywhere: `PYTHIA_STATE_FILE`.
fn state_file() -> Option<std::path::PathBuf> {
    std::env::var("PYTHIA_STATE_FILE").ok().map(Into::into)
}

/// Checkpoints the engine every minute (atomic replace), like the desktop app.
async fn save_loop(state: AppState) {
    let Some(path) = state_file() else { return };
    loop {
        tokio::time::sleep(Duration::from_secs(60)).await;
        let snapshot = state.engine.lock().unwrap().to_persisted();
        if let Err(e) = pythia_core::persist::save(&path, &snapshot) {
            tracing::warn!("state not saved to {}: {e}", path.display());
        }
    }
}

/// The model service's status handle, set once at startup.
static ML: OnceLock<pythia_core::ml::SharedMl> = OnceLock::new();

async fn get_ml_status() -> impl IntoResponse {
    match ML.get() {
        Some(ml) => Json(ml.read().map(|s| s.clone()).unwrap_or_default()).into_response(),
        None => (axum::http::StatusCode::SERVICE_UNAVAILABLE, "model service not started").into_response(),
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

    // Recalibrated costs: `PYTHIA_COSTS_FILE`, else the repo's own
    // `config/costs.json` when running from a checkout, so an edit there takes
    // effect on restart without a rebuild. The compiled-in copy is the fallback.
    let costs_file = std::env::var("PYTHIA_COSTS_FILE")
        .ok()
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from("config/costs.json"));
    if costs_file.exists() {
        match costs::load_file(&costs_file) {
            Ok(()) => tracing::info!("cost model loaded from {}", costs_file.display()),
            Err(e) => tracing::warn!("ignoring cost file: {e}"),
        }
    }

    let (tx, _rx) = broadcast::channel::<String>(64);
    let creds = Arc::new(credentials_from_env());
    let engine = Arc::new(Mutex::new(Engine::new()));
    // Reflect which venues actually have usable keys before the first tick, so
    // the UI never shows a venue as armable that cannot route.
    {
        let mut e = engine.lock().unwrap();
        // Resume where the last run left off: positions, strategies and their
        // forward-test records. Without this every restart would reset gate 7.
        if let Some(path) = state_file() {
            use pythia_core::persist::Loaded;
            match pythia_core::persist::load(&path) {
                Loaded::Restored(p) => {
                    e.apply_persisted(*p);
                    tracing::info!("state restored from {}", path.display());
                }
                Loaded::Missing => tracing::info!("no state file at {} yet, starting fresh", path.display()),
                Loaded::Unreadable { error, moved_to: Some(aside) } => tracing::warn!(
                    "state file {} unreadable, starting fresh; the old file is kept as {}: {error}",
                    path.display(),
                    aside.display()
                ),
                Loaded::Unreadable { error, moved_to: None } => {
                    // Saving now would overwrite the only copy. Refuse to run.
                    tracing::error!(
                        "state file {} unreadable and could not be moved aside, not starting: {error}",
                        path.display()
                    );
                    std::process::exit(1);
                }
            }
        }
        e.set_connected(creds.connected_venues());
        // A headless instance that only runs lab books (the VPS) pauses the
        // built-in indicator strategies, which would otherwise hold the same
        // coins and block the lab book from running its portfolio.
        if std::env::var("PYTHIA_LAB_ONLY").map(|v| v == "1").unwrap_or(false) {
            let ids: Vec<String> = e.state().strategies.iter().map(|s| s.id.clone()).collect();
            for id in ids {
                let _ = e.set_strategy_state(&id, pythia_core::engine::StrategyState::Paused);
            }
            tracing::info!("PYTHIA_LAB_ONLY: built-in strategies paused, lab strategies only");
        }
        // Costs follow the selected exchange even before its keys are set.
        e.set_crypto_cost_venue(
            env_str("PYTHIA_EXCHANGE").as_deref().and_then(Exchange::parse).map(CostVenue::for_exchange),
        );
    }
    let state = AppState {
        engine,
        tx: tx.clone(),
        webhook: Arc::new(Mutex::new(std::env::var("PYTHIA_WEBHOOK_URL").ok())),
        creds,
    };

    // The engine daemon — the network analog of the desktop tick loop.
    tokio::spawn(tick_loop(state.clone()));
    // The AI overlay runs on its own clock so a slow model call can never
    // delay a tick, a stop check, or an order.
    tokio::spawn(ai_loop(state.clone()));
    // Model forecasts in shadow mode (scored, never traded). Idles with a
    // status message when PYTHIA_MODELS is unset.
    let _ = ML.set(pythia_core::ml::spawn());
    // Lab strategies: pick up the research lab's daily target weights.
    tokio::spawn(lab_loop(state.clone()));
    if state_file().is_some() {
        tokio::spawn(save_loop(state.clone()));
    }

    let app = Router::new()
        .route("/api/health", get(health))
        .route("/api/preflight", get(get_preflight))
        .route("/api/research/validate", get(get_validate))
        .route("/api/research/sweep", get(get_sweep))
        .route("/api/research/passport", post(post_validation))
        .route("/api/state", get(get_state))
        .route("/api/stream", get(ws_stream))
        .route("/api/command", post(post_command))
        .route("/api/llm/providers", get(get_llm_providers))
        .route("/api/llm/signal", post(post_llm_signal))
        .route("/api/ai/config", post(post_ai_config))
        .route("/api/live/config", post(post_live_config))
        .route("/api/live/account", get(get_live_account))
        .route("/api/live/verify", get(get_live_verify))
        .route("/api/live/diagnostics", get(get_live_diagnostics))
        .route("/api/live/test-order", post(post_test_order))
        .route("/api/exchanges", get(get_exchanges))
        .route("/api/wallets", get(get_wallets))
        .route("/api/ml/status", get(get_ml_status))
        .route("/api/tax", get(get_tax))
        .route("/api/lab", get(|| async { Json(pythia_core::labview::status()) }))
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
    if has_alpaca_keys(&state.creds) {
        tracing::info!(
            "Alpaca: keys present → real equity quotes ({} feed) + live execution available{}",
            std::env::var("APCA_FEED").unwrap_or_else(|_| "iex".into()),
            if extended_hours_default() { " (extended hours default ON)" } else { "" }
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
    const TICK_MS: u64 = 1500;
    // Cadences, in ticks. Quotes move the mark; candles move the signals; the
    // broker check gates live routing and must stay well inside the engine's
    // five-minute staleness window.
    const QUOTES_EVERY: u64 = 8; // ~12s
    const BARS_EVERY: u64 = 40; // ~60s
    const BROKER_EVERY: u64 = 40; // ~60s
    const RECONCILE_EVERY: u64 = 80; // ~2min

    let mut interval = tokio::time::interval(Duration::from_millis(TICK_MS));
    let mut n: u64 = 0;
    loop {
        interval.tick().await;
        n += 1;

        // Every network refresh happens here, with NO lock held — the engine
        // mutex is only ever taken for the synchronous apply.
        if n % QUOTES_EVERY == 1 {
            let (key, secret, feed) = alpaca_data_keys(&state.creds);
            let kraken = marketdata::fetch_kraken().await;
            let poly = marketdata::fetch_polymarket().await;
            let alpaca = marketdata::fetch_alpaca(&key, &secret, &feed).await;
            let mut e = state.engine.lock().unwrap();
            e.apply_kraken(&kraken);
            e.apply_polymarket(&poly);
            e.apply_alpaca(&alpaca);
        }

        // Candle history — the series every indicator actually runs on.
        if n % BARS_EVERY == 1 {
            let (tf, kraken_min) = bar_timeframe();
            let (key, secret, feed) = alpaca_data_keys(&state.creds);
            let mut series = marketdata::fetch_kraken_bars(kraken_min).await;
            series.extend(marketdata::fetch_alpaca_bars(&key, &secret, &feed, &tf, 10).await);
            if !series.is_empty() {
                state.engine.lock().unwrap().apply_bars(&series);
            }
        }

        // Session + account state. Without a recent answer here the engine
        // refuses to route live equity entries at all.
        if n % BROKER_EVERY == 1 && has_alpaca_keys(&state.creds) {
            refresh_broker_status(&state).await;
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
        // network calls, so they happen with no engine lock held. Submission
        // returns on the venue's acknowledgement and polling is one request per
        // order, so neither can stall the tick loop the way a blocking
        // wait-for-fill would.
        execution::cycle(&state.engine, &state.creds).await;
        // Every real fill goes to the append-only tax record.
        pythia_core::tax::flush(&state.engine, &fills_file());

        // Reconcile against the broker every ~2 minutes: it is the only way to
        // notice a fill that happened while we were restarting.
        if n % RECONCILE_EVERY == 1 {
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

/// Ask Alpaca whether the market is open and whether the account may trade.
/// Uses the keys for whichever endpoint is currently selected.
async fn refresh_broker_status(state: &AppState) {
    let paper = { state.engine.lock().unwrap().live_config().paper };
    let conn = alpaca_conn(&state.creds, paper);
    let (session, account) = tokio::join!(conn.session(), conn.account());

    let (Ok((clock, extended_open, session_end)), Ok(account)) = (session, account) else {
        // Leave the previous status in place; it ages out on its own and the
        // engine blocks live entries once it does. Failing to reach the broker
        // must never look like "the market is open".
        tracing::warn!("broker status refresh failed — live entries will block once the last check goes stale");
        return;
    };

    let status = BrokerStatus {
        market_open: clock.is_open,
        extended_open,
        session_end,
        next_open: Some(clock.next_open.clone()),
        day_trade_limit_reached: account.day_trade_limit_reached(),
        restricted: account.is_restricted(),
        equity: account.equity_f64(),
        buying_power: account.buying_power_f64(),
        checked_at: chrono::Utc::now().timestamp_millis(),
    };
    state.engine.lock().unwrap().set_broker_status(status);
}

/// The AI overlay loop: one market per pass, round-robin, only while the
/// overlay is enabled.
///
/// Rate is deliberately conservative. A model call costs money and adds
/// latency, and its value decays with the bar it describes — polling every
/// market every minute would spend a lot to learn very little.
async fn ai_loop(state: AppState) {
    let period = Duration::from_secs(
        std::env::var("PYTHIA_AI_INTERVAL_SEC")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(120),
    );
    let mut interval = tokio::time::interval(period);
    let mut cursor: usize = 0;

    loop {
        interval.tick().await;

        let (enabled, candidates) = {
            let e = state.engine.lock().unwrap();
            (e.ai_enabled(), e.ai_candidates())
        };
        if !enabled || candidates.is_empty() {
            continue;
        }

        let market_id = candidates[cursor % candidates.len()].clone();
        cursor = cursor.wrapping_add(1);

        let Some(context) = ({
            let e = state.engine.lock().unwrap();
            e.ai_context(&market_id)
        }) else {
            continue;
        };

        let provider = std::env::var("PYTHIA_AI_PROVIDER")
            .ok()
            .and_then(|p| Provider::parse(&p))
            .unwrap_or(Provider::Anthropic);
        let key = std::env::var(provider.env_key()).unwrap_or_default();
        if provider.needs_key() && key.trim().is_empty() {
            state
                .engine
                .lock()
                .unwrap()
                .record_ai_error(&format!("{} has no key ({})", provider.id(), provider.env_key()));
            continue;
        }

        let effort = match std::env::var("PYTHIA_AI_EFFORT").unwrap_or_default().as_str() {
            "medium" => Effort::Medium,
            "high" => Effort::High,
            "xhigh" => Effort::Xhigh,
            "max" => Effort::Max,
            _ => Effort::Low,
        };
        let cfg = LlmConfig::new(provider, std::env::var("PYTHIA_AI_MODEL").unwrap_or_default(), key)
            .with_effort(effort)
            .with_timeout(Duration::from_secs(45));

        match llm::signal(&cfg, &context).await {
            Ok(sig) => {
                let view = AiView {
                    market_id: market_id.clone(),
                    direction: format!("{:?}", sig.direction).to_lowercase(),
                    probability: sig.probability,
                    confidence: sig.confidence,
                    rationale: sig.rationale,
                    model: if sig.served_by.is_empty() { sig.model } else { sig.served_by },
                    ts: chrono::Utc::now().timestamp_millis(),
                    latency_ms: sig.latency_ms,
                };
                state.engine.lock().unwrap().apply_ai_view(view, sig.input_tokens, sig.output_tokens);
            }
            Err(e) => {
                // A failed call is "no opinion", never a reason to stop trading.
                state.engine.lock().unwrap().record_ai_error(&e.to_string());
            }
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ValidateQuery {
    /// Out-of-sample windows. More folds means more, shorter tests.
    #[serde(default)]
    folds: Option<usize>,
    /// Include the equity universe (needs Alpaca keys). Crypto always runs.
    #[serde(default)]
    equities: Option<bool>,
    /// Multiplier on the cost model (`config/costs.json`). Set 0 to measure the
    /// same strategies with no fees or slippage, which shows how much of a
    /// result the cost model is eating; 2 or 3 to stress it.
    #[serde(default)]
    cost_mult: Option<f64>,
}

/// Walk-forward validate every shipped strategy on real daily candles.
///
/// Daily bars because the venues cap a single history request: Kraken returns
/// 720 candles whatever the interval, which is 2.5 days at 5-minute resolution
/// and roughly two years at daily. Two years supports four folds; two days
/// supports nothing, and a validation run on a sample that small would be
/// theatre.
async fn get_validate(
    State(st): State<AppState>,
    axum::extract::Query(q): axum::extract::Query<ValidateQuery>,
) -> impl IntoResponse {
    let folds = q.folds.unwrap_or(4).clamp(2, 8);
    let cost_mult = q.cost_mult.unwrap_or(1.0).clamp(0.0, 10.0);
    let crypto_venue = st.engine.lock().unwrap().crypto_cost_venue();

    // Daily crypto candles (no keys required).
    let crypto: Vec<(String, String, Vec<pythia_core::marketdata::Ohlc>)> =
        marketdata::fetch_kraken_bars(1440)
            .await
            .into_iter()
            .map(|s| {
                let symbol = s.id.trim_start_matches("crypto:").to_string();
                (s.id, symbol, s.bars)
            })
            .collect();

    let mut equities: Vec<(String, String, Vec<pythia_core::marketdata::Ohlc>)> = Vec::new();
    if q.equities.unwrap_or(true) && has_alpaca_keys(&st.creds) {
        let (key, secret, feed) = alpaca_data_keys(&st.creds);
        // ~4 years of sessions; Alpaca will return what the plan covers.
        equities = marketdata::fetch_alpaca_bars(&key, &secret, &feed, "1Day", 1460)
            .await
            .into_iter()
            .map(|s| {
                let symbol = s.id.trim_start_matches("alpaca:").to_string();
                (s.id, symbol, s.bars)
            })
            .collect();
    }

    let strategies = { st.engine.lock().unwrap().state().strategies };
    let mut reports = Vec::new();
    let mut skipped = Vec::new();

    for cfg in &strategies {
        if !research::is_validatable(cfg.kind) {
            skipped.push(serde_json::json!({
                "id": cfg.id,
                "name": cfg.name,
                "reason": "not a single-market technical rule — this harness can't score it honestly",
            }));
            continue;
        }
        // Score each strategy on the universe it actually trades.
        let is_equity = cfg.venue_class == pythia_core::connectors::Venue::Alpaca;
        let universe: Vec<_> = if is_equity { equities.clone() } else { crypto.clone() };
        let universe: Vec<_> =
            universe.into_iter().filter(|(id, _, _)| cfg.universe.contains(id)).collect();
        if universe.is_empty() {
            skipped.push(serde_json::json!({
                "id": cfg.id,
                "name": cfg.name,
                "reason": if is_equity {
                    "no equity candles — set Alpaca keys to include this one"
                } else {
                    "no candles for this universe"
                },
            }));
            continue;
        }

        let wf = research::WalkForwardConfig {
            folds,
            min_trades: 20,
            min_is_trades: 3,
            bt: BacktestConfig {
                venue: if is_equity { CostVenue::Alpaca } else { crypto_venue },
                cost_mult,
                // Daily bars: 365 for crypto (always open), 252 sessions for equities.
                bars_per_year: if is_equity { 252.0 } else { 365.0 },
                ..BacktestConfig::default()
            },
        };
        // Backtesting is CPU-bound; keep it off the async executor's threads so
        // the tick loop and websocket pushes stay responsive while it runs.
        let cfg = cfg.clone();
        let report = tokio::task::spawn_blocking(move || research::walk_forward(&cfg, &universe, &wf))
            .await
            .expect("validation task");
        reports.push(report);
    }

    reports.sort_by(|a, b| {
        b.deflated_sharpe.partial_cmp(&a.deflated_sharpe).unwrap_or(std::cmp::Ordering::Equal)
    });

    Json(serde_json::json!({
        "timeframe": "1Day",
        "folds": folds,
        "costs": {
            "cryptoVenue": crypto_venue,
            "costMult": cost_mult,
            "crypto": costs::table().venue_model(crypto_venue),
            "equities": costs::table().venue_model(CostVenue::Alpaca),
        },
        "cryptoMarkets": crypto.len(),
        "equityMarkets": equities.len(),
        "cryptoBars": crypto.first().map(|(_, _, b)| b.len()).unwrap_or(0),
        "equityBars": equities.first().map(|(_, _, b)| b.len()).unwrap_or(0),
        "reports": reports,
        "skipped": skipped,
    }))
}

#[derive(Debug, Deserialize)]
struct StrategyQuery {
    id: String,
}

/// A strategy's config, research backtest settings and daily candles, with
/// the engine lock released before the network calls.
async fn research_inputs(
    st: &AppState,
    id: &str,
) -> Result<(StrategyConfig, BacktestConfig, research::Universe), (StatusCode, String)> {
    let (cfg, bt) = {
        let e = st.engine.lock().unwrap();
        let cfg = e
            .strategy_config(id)
            .ok_or_else(|| (StatusCode::NOT_FOUND, format!("unknown strategy {id}")))?;
        let bt = e.research_bt(&cfg);
        (cfg, bt)
    };
    let alpaca = has_alpaca_keys(&st.creds).then(|| alpaca_data_keys(&st.creds));
    let universe = research::fetch_daily_universe(&cfg, alpaca)
        .await
        .map_err(|e| (StatusCode::SERVICE_UNAVAILABLE, e))?;
    Ok((cfg, bt, universe))
}

/// Sweep one strategy's parameter grid on real daily candles, with the
/// deflated Sharpe and out-of-sample/in-sample ratio of every configuration.
async fn get_sweep(
    State(st): State<AppState>,
    axum::extract::Query(q): axum::extract::Query<StrategyQuery>,
) -> impl IntoResponse {
    let (cfg, bt, universe) = match research_inputs(&st, &q.id).await {
        Ok(x) => x,
        Err(e) => return e.into_response(),
    };
    match tokio::task::spawn_blocking(move || research::sweep(&cfg, &universe, &bt, 0.6)).await {
        Ok(r) => Json(r).into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, format!("sweep failed: {e}")).into_response(),
    }
}

async fn health() -> &'static str {
    "ok"
}

/// Everything that has to be true before a live run, checked in one call.
///
/// Exists because the failure modes are all silent: keys that work against the
/// paper endpoint but not the live one, a data feed you are not subscribed to,
/// an account still onboarding, a market that closed twenty minutes ago. Each
/// of those looks identical from the dashboard — an armed engine placing no
/// trades — so the runbook needs one command that names the actual problem.
async fn get_preflight(State(st): State<AppState>) -> impl IntoResponse {
    let mut checks: Vec<serde_json::Value> = Vec::new();
    let mut check = |name: &str, ok: bool, detail: String| {
        checks.push(serde_json::json!({ "name": name, "ok": ok, "detail": detail }));
    };

    let (key, secret, feed) = alpaca_data_keys(&st.creds);
    let keys_set = !key.trim().is_empty() && !secret.trim().is_empty();
    check(
        "alpaca_keys",
        keys_set,
        if keys_set {
            format!("APCA_API_KEY_ID set (…{})", &key[key.len().saturating_sub(4)..])
        } else {
            "APCA_API_KEY_ID / APCA_API_SECRET_KEY are empty — equities stay simulated".into()
        },
    );

    let paper = { st.engine.lock().unwrap().live_config().paper };
    if keys_set {
        let conn = alpaca_conn(&st.creds, paper);
        let endpoint = if paper { "paper-api.alpaca.markets" } else { "api.alpaca.markets" };

        match conn.account().await {
            Ok(a) => {
                check(
                    "alpaca_account",
                    a.is_restricted().is_none(),
                    match a.is_restricted() {
                        Some(why) => format!("{endpoint}: {why}"),
                        None => format!(
                            "{endpoint}: {} · equity ${:.2} · buying power ${:.2}",
                            a.status,
                            a.equity_f64(),
                            a.buying_power_f64()
                        ),
                    },
                );
                check(
                    "pattern_day_trader",
                    !a.day_trade_limit_reached(),
                    format!(
                        "{} day trade(s) used; equity ${:.2}{}",
                        a.daytrade_count,
                        a.equity_f64(),
                        if a.equity_f64() < 25_000.0 { " (PDT rules apply under $25k)" } else { "" }
                    ),
                );
            }
            Err(e) => check(
                "alpaca_account",
                false,
                format!("{endpoint}: {e} — paper and live accounts have SEPARATE keys"),
            ),
        }

        match conn.clock().await {
            Ok(c) => check(
                "market_session",
                c.is_open,
                if c.is_open {
                    format!("open until {}", c.next_close)
                } else {
                    format!("closed — next open {}", c.next_open)
                },
            ),
            Err(e) => check("market_session", false, format!("clock unavailable: {e}")),
        }

        let quotes = marketdata::fetch_alpaca(&key, &secret, &feed).await;
        check(
            "equity_quotes",
            !quotes.is_empty(),
            format!("{} symbol(s) on the '{feed}' feed", quotes.len()),
        );

        let (tf, _) = bar_timeframe();
        let bars = marketdata::fetch_alpaca_bars(&key, &secret, &feed, &tf, 10).await;
        let total: usize = bars.iter().map(|b| b.bars.len()).sum();
        check(
            "equity_candles",
            bars.iter().all(|b| b.bars.len() >= 30) && !bars.is_empty(),
            format!("{} series, {total} {tf} bars — indicators need ≥30 per market", bars.len()),
        );
    }

    let (_, kraken_min) = bar_timeframe();
    let kbars = marketdata::fetch_kraken_bars(kraken_min).await;
    check(
        "crypto_candles",
        kbars.len() >= 5,
        format!("{} Kraken series (no keys needed)", kbars.len()),
    );

    let providers: Vec<&str> = Provider::ALL
        .iter()
        .filter(|p| p.needs_key() && p.configured_in_env())
        .map(|p| p.id())
        .collect();
    check(
        "ai_provider",
        !providers.is_empty(),
        if providers.is_empty() {
            "no model keys set — the AI overlay will stay idle (this is fine)".into()
        } else {
            format!("configured: {}", providers.join(", "))
        },
    );

    let live = { st.engine.lock().unwrap().state().live };
    check(
        "live_gate",
        live.blocked_reason.is_none(),
        live.blocked_reason.clone().unwrap_or_else(|| {
            if live.armed { "armed and clear".into() } else { "disarmed (paper only)".into() }
        }),
    );

    let ready = checks.iter().all(|c| c["ok"].as_bool().unwrap_or(false));
    Json(serde_json::json!({ "ready": ready, "paperEndpoint": paper, "checks": checks }))
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
) -> axum::response::Response {
    let mut refused: Option<String> = None;
    let dto = {
        let mut e = st.engine.lock().unwrap();
        match cmd {
            Command::ToggleKill => e.toggle_kill(),
            Command::SetLimits { patch } => e.set_limits(patch),
            // Live is refused until the passport is green; the reason goes
            // back to the caller as a 409 rather than vanishing into a 200.
            Command::SetStrategyState { id, state } => refused = e.set_strategy_state(&id, state).err(),
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
    match refused {
        Some(why) => (StatusCode::CONFLICT, why).into_response(),
        None => Json(dto).into_response(),
    }
}

/// Run validation gates 1 to 6 for one strategy on real daily candles, keep
/// the result in the engine, and return the full Strategy Passport.
async fn post_validation(
    State(st): State<AppState>,
    axum::extract::Query(q): axum::extract::Query<StrategyQuery>,
) -> impl IntoResponse {
    let (cfg, bt, universe) = match research_inputs(&st, &q.id).await {
        Ok(x) => x,
        Err(e) => return e.into_response(),
    };
    let now = chrono::Utc::now().timestamp_millis();
    let verdict = match tokio::task::spawn_blocking(move || {
        validation::research_gates(&cfg, &universe, &bt, &research::WalkForwardConfig { bt, ..Default::default() }, now)
    })
    .await
    {
        Ok(v) => v,
        Err(e) => return (StatusCode::INTERNAL_SERVER_ERROR, format!("validation failed: {e}")).into_response(),
    };
    let passport = {
        let mut e = st.engine.lock().unwrap();
        e.store_research(verdict);
        let s = e.state();
        let _ = st.tx.send(serde_json::to_string(&s).unwrap_or_default());
        e.passport(&q.id)
    };
    match passport {
        Some(p) => Json(p).into_response(),
        None => (StatusCode::NOT_FOUND, format!("unknown strategy {}", q.id)).into_response(),
    }
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
    /// Allow Alpaca entries in the pre-market / after-hours session. Omitted
    /// means `PYTHIA_EXTENDED_HOURS`, which itself defaults to off.
    #[serde(default)]
    extended_hours: Option<bool>,
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
        extended_hours: req.extended_hours.unwrap_or_else(extended_hours_default),
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

    {
        let mut e = st.engine.lock().unwrap();
        e.set_connected(st.creds.connected_venues());
        e.set_live(cfg);
    }
    // Pick up anything that filled while we were disarmed, and get a fresh
    // session check for the endpoint just selected: live Alpaca entries are
    // refused until one arrives.
    execution::reconcile(&st.engine, &st.creds).await;
    if has_alpaca_keys(&st.creds) {
        refresh_broker_status(&st).await;
    }
    let dto = st.engine.lock().unwrap().state();
    let _ = st.tx.send(serde_json::to_string(&dto).unwrap_or_default());
    Json(dto).into_response()
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AiConfigReq {
    enabled: bool,
    #[serde(default)]
    ttl_sec: Option<u64>,
    #[serde(default)]
    veto_confidence: Option<f64>,
    #[serde(default)]
    max_boost: Option<f64>,
}

/// Turn the AI overlay on/off and tune how much authority it has.
async fn post_ai_config(State(st): State<AppState>, Json(req): Json<AiConfigReq>) -> Json<EngineState> {
    let d = AiPolicy::default();
    let policy = AiPolicy {
        enabled: req.enabled,
        ttl_sec: req.ttl_sec.unwrap_or(d.ttl_sec).clamp(30, 86_400),
        veto_confidence: req.veto_confidence.unwrap_or(d.veto_confidence).clamp(0.0, 1.0),
        // Hard ceiling on the boost: an agreeing model may nudge size, never
        // multiply it. This bound is not user-configurable for a reason.
        max_boost: req.max_boost.unwrap_or(d.max_boost).clamp(1.0, 1.5),
    };
    let dto = {
        let mut e = st.engine.lock().unwrap();
        e.set_ai_policy(policy);
        let s = e.state();
        let _ = st.tx.send(serde_json::to_string(&s).unwrap_or_default());
        s
    };
    Json(dto)
}

/// Per-market answer to "why hasn't this traded?".
async fn get_live_diagnostics(State(st): State<AppState>) -> impl IntoResponse {
    Json(st.engine.lock().unwrap().live_diagnostics())
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct TestOrderReq {
    market_id: String,
    notional: f64,
}

/// Send one small order through the real path, to prove the pipeline.
async fn post_test_order(
    State(st): State<AppState>,
    Json(req): Json<TestOrderReq>,
) -> impl IntoResponse {
    let (status, body) = {
        let mut e = st.engine.lock().unwrap();
        // 0 means "the venue's minimum size": a connection test, not a strategy.
        let notional = if req.notional > 0.0 {
            req.notional.clamp(1.0, 5_000.0)
        } else {
            e.connection_test_notional(&req.market_id)
        };
        if let Err(why) = e.connection_test_order(&req.market_id, notional) {
            (StatusCode::CONFLICT, why)
        } else {
            let msg = e
                .state()
                .journal
                .iter()
                .find(|j| j.market_id.as_deref() == Some(req.market_id.as_str()))
                .map(|j| j.message.clone())
                .unwrap_or_else(|| "order queued".into());
            let s = e.state();
            let _ = st.tx.send(serde_json::to_string(&s).unwrap_or_default());
            (StatusCode::OK, msg)
        }
    };
    (status, body)
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
    // Each endpoint is tested with its own key pair, so a 401 here names the
    // slot that is wrong instead of blaming the other account.
    let conn = match st.creds.alpaca_connector(q.paper, false) {
        Ok(c) => c,
        Err(e) => return (StatusCode::SERVICE_UNAVAILABLE, e).into_response(),
    };
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
    let paper = st.engine.lock().unwrap().live_config().paper;
    let sources = WalletSources {
        // The account for the selected endpoint, with that endpoint's own keys.
        alpaca: st.creds.alpaca_keys(paper).cloned().map(|(k, s)| (k, s, paper)),
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
