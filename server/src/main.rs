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
//!   GET  /api/alerts           → operator alerts: destination, mute, counts, recent posts
//!   POST /api/alerts/test      → send one test message (409 when alerts are off)
//!   POST /api/alerts/mute      → mute for `{minutes}` (0 unmutes, at most 7 days)
//!   POST /api/alerts/digest    → ask the lab's notify job for a digest now (202)
//!   GET  /api/alerts/settings  → category switches, quiet hours, big-move sizes
//!   POST /api/alerts/settings  → change them (saved with the engine state)
//!   POST /api/alerts/event     → a lab job posts an alert (localhost only)
//!   GET  /api/ai/budget        → Claude API caps, spend and the last calls
//!   POST /api/ai/budget        → change the caps
//!   POST /api/ai/complete      → a lab job's metered Claude call (localhost, key token)
//!   GET  /api/ai/report        → the AI brief, its scores and the weekly review
//!   GET  /api/readiness/settings → the real money readiness check's risk step
//!   POST /api/readiness/settings → change it (`{riskStep}`, 1 to 5); report only
//!
//! Paper-first, exactly like the desktop app: real money stays gated behind the
//! same sovereign risk manager and vault. This process only ever runs the
//! simulated matching engine.
//!
//! The API has no login of its own. It listens on 127.0.0.1 unless
//! `PYTHIA_BIND` says otherwise, refuses state-changing requests from foreign
//! web origins and requests for foreign host names (`guard.rs`), and is meant
//! to be reached from elsewhere only through an authenticating reverse proxy
//! (SECURITY.md).

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

mod guard;

use pythia_core::connectors::alpaca::{AlpacaAccount, AlpacaConnector};
use pythia_core::connectors::cex::{self, Exchange};
use pythia_core::connectors::perps::PerpExchange;
use pythia_core::connectors::{Environment, Side, Venue};
use pythia_core::engine::autopilot::{AutopilotConfig, AutopilotMode, AutopilotUpdate, VenueCash};
use pythia_core::engine::maker::MakerSettings;
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
    /// Typed operator alerts to `PYTHIA_ALERT_WEBHOOK` (off when unset). The
    /// sender runs on its own task: queuing never waits on the network.
    alert_sink: Option<alerts::AlertSink>,
    /// What the alert sender posted, today's counts and the mute. Kept even
    /// when alerts are off, so the API can say so.
    alert_log: alerts::AlertLog,
    /// Where the alert API reads and writes its files.
    alert_files: Arc<AlertFiles>,
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
    credentials_from(&env_str)
}

/// [`credentials_from_env`] over any variable source, for tests.
fn credentials_from(get: &dyn Fn(&str) -> Option<String>) -> Credentials {
    let alpaca = match (get("APCA_API_KEY_ID"), get("APCA_API_SECRET_KEY")) {
        (Some(k), Some(s)) => Some((k, s)),
        _ => None,
    };
    let alpaca_live = match (get("APCA_LIVE_API_KEY_ID"), get("APCA_LIVE_API_SECRET_KEY")) {
        (Some(k), Some(s)) => Some((k, s)),
        _ => alpaca.clone(),
    };
    // One exchange at a time — `PYTHIA_EXCHANGE` picks which.
    let exchange = get("PYTHIA_EXCHANGE")
        .as_deref()
        .and_then(Exchange::parse)
        .and_then(|ex| {
            let k = get("PYTHIA_EXCHANGE_KEY")?;
            let s = get("PYTHIA_EXCHANGE_SECRET")?;
            Some((ex, k, s, get("PYTHIA_EXCHANGE_PASSPHRASE").unwrap_or_default()))
        });
    // The demo route's exchange and its DEMO keys, separate variables from
    // the live ones (see docs/DEMO.md). Never filled from PYTHIA_EXCHANGE_KEY.
    // `alpaca` needs no keys of its own: crypto demo orders go to the Alpaca
    // paper account with the APCA_API_* paper pair.
    let crypto_demo_alpaca = get("PYTHIA_DEMO_EXCHANGE").is_some_and(|v| v.eq_ignore_ascii_case("alpaca"));
    let exchange_demo = get("PYTHIA_DEMO_EXCHANGE")
        .as_deref()
        .and_then(Exchange::parse)
        .and_then(|ex| {
            let k = get("PYTHIA_DEMO_EXCHANGE_KEY")?;
            let s = get("PYTHIA_DEMO_EXCHANGE_SECRET")?;
            Some((ex, k, s, get("PYTHIA_DEMO_EXCHANGE_PASSPHRASE").unwrap_or_default()))
        });
    let perps_demo = perps_demo_from(get);
    Credentials {
        alpaca,
        alpaca_live,
        exchange,
        exchange_demo,
        perps_demo,
        crypto_demo_alpaca,
        // Marketable-limit band for Alpaca market orders; 25bps when unset.
        alpaca_slippage_bps: get("PYTHIA_SLIPPAGE_BPS").and_then(|v| v.parse().ok()),
        alpaca_allow_shorts: matches!(get("PYTHIA_ALLOW_SHORTS").as_deref(), Some("1" | "true" | "TRUE" | "yes" | "on")),
    }
}

/// The perps DEMO route's venue and demo keys (docs/KRAKEN-FUTURES-DEMO.md).
/// `PYTHIA_PERPS_DEMO` picks the venue (`kraken_futures` or `bybit`); unset,
/// the venue whose keys are present, Kraken Futures first. Kraken Futures
/// keys: `KRAKEN_FUTURES_DEMO_KEY` / `KRAKEN_FUTURES_DEMO_SECRET`. Bybit:
/// `BYBIT_DEMO_KEY` / `BYBIT_DEMO_SECRET`, else the crypto demo pair when
/// `PYTHIA_DEMO_EXCHANGE=bybit` (one Bybit demo account trades spot and
/// perps). There is no live perps key: real-money perps are refused.
fn perps_demo_from(get: &dyn Fn(&str) -> Option<String>) -> Option<(PerpExchange, String, String)> {
    let kraken = || Some((get("KRAKEN_FUTURES_DEMO_KEY")?, get("KRAKEN_FUTURES_DEMO_SECRET")?));
    let bybit = || {
        let own = get("BYBIT_DEMO_KEY").zip(get("BYBIT_DEMO_SECRET"));
        let shared = || {
            let ex = get("PYTHIA_DEMO_EXCHANGE")?;
            (Exchange::parse(&ex) == Some(Exchange::Bybit))
                .then(|| get("PYTHIA_DEMO_EXCHANGE_KEY").zip(get("PYTHIA_DEMO_EXCHANGE_SECRET")))
                .flatten()
        };
        own.or_else(shared)
    };
    let with = |ex: PerpExchange, keys: Option<(String, String)>| keys.map(|(k, s)| (ex, k, s));
    match get("PYTHIA_PERPS_DEMO").as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        Some(s) if s.eq_ignore_ascii_case("off") || s.eq_ignore_ascii_case("none") => None,
        Some(s) => match PerpExchange::parse(s) {
            Some(PerpExchange::KrakenFutures) => with(PerpExchange::KrakenFutures, kraken()),
            Some(PerpExchange::Bybit) => with(PerpExchange::Bybit, bybit()),
            None => {
                tracing::warn!("PYTHIA_PERPS_DEMO={s} is not a perps venue (kraken_futures or bybit); perps demo off");
                None
            }
        },
        None => with(PerpExchange::KrakenFutures, kraken()).or_else(|| with(PerpExchange::Bybit, bybit())),
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
/// engine, which rebalances each lab book once per new signal. The forward
/// report's summary (`reports/forward/evidence.json`) comes along with them:
/// the autopilot's auto pick and its status line read it.
async fn lab_loop(state: AppState) {
    let dir = pythia_core::lab::signals_dir();
    if dir.is_none() {
        tracing::info!("lab strategies: PYTHIA_SIGNALS / PYTHIA_MODELS not set, none loaded");
    }
    if dir.is_none() && pythia_core::labview::data_dir().is_none() {
        return;
    }
    loop {
        let (signals, errors) = dir.as_deref().map(pythia_core::lab::read_all).unwrap_or_default();
        for e in errors {
            tracing::warn!("lab signal skipped: {e}");
        }
        let forward = pythia_core::labview::forward_evidence();
        {
            let mut e = state.engine.lock().unwrap();
            for s in signals {
                e.apply_lab_signal(s);
            }
            if let Some(f) = forward {
                e.apply_lab_forward(f);
            }
        }
        tokio::time::sleep(Duration::from_secs(300)).await;
    }
}

/// Reads the crypto pairs the Alpaca paper account lists, at startup and then
/// once a day, while crypto demo orders go there. A failed read is retried
/// after ten minutes; the engine keeps the last list it had meanwhile, and the
/// connector's own asset check still refuses an unlisted pair.
async fn crypto_demo_listing_loop(state: AppState, mut wait: Duration) {
    loop {
        tokio::time::sleep(wait).await;
        wait = read_crypto_demo_listing(&state).await;
    }
}

/// One read of the Alpaca crypto list; returns how long until the next one.
async fn read_crypto_demo_listing(state: &AppState) -> Duration {
    match execution::refresh_crypto_demo_listing(&state.engine, &state.creds).await {
        Ok(n) => {
            tracing::info!("Crypto demo route: Alpaca paper lists {n} tradable USD crypto pairs");
            Duration::from_secs(24 * 3600)
        }
        Err(e) => {
            tracing::warn!("Crypto demo route: Alpaca crypto list not read ({e}), retrying in 10 minutes");
            Duration::from_secs(600)
        }
    }
}

/// Reconciles the Alpaca paper account against the demo book shortly after
/// startup (once the first ticks have polled the orders restored from the
/// save) and then every ten minutes, while demo orders go there. See
/// `pythia_core::engine::demo_reconcile`.
async fn demo_reconcile_loop(state: AppState) {
    tokio::time::sleep(Duration::from_secs(15)).await;
    let every = Duration::from_millis(pythia_core::engine::demo_reconcile::DEMO_RECONCILE_EVERY_MS as u64);
    loop {
        execution::reconcile_demo(&state.engine, &state.creds).await;
        tokio::time::sleep(every).await;
    }
}

/// Perps marks every 15 seconds while perps are held or a perps autopilot
/// runs (inside the risk manager's 30-second staleness limit), every five
/// minutes otherwise, the contract list once a day, and the settled funding
/// of what is held whenever the engine says it is due. Public data only.
async fn perps_market_loop(state: AppState) {
    let http = pythia_core::connectors::perps::data_client();
    let mut every = tokio::time::interval(Duration::from_secs(15));
    let mut failing = false;
    let mut n: u64 = 0;
    let mut marks_at: i64 = 0;
    loop {
        every.tick().await;
        let gap = state.engine.lock().unwrap().perp_marks_every_ms();
        let now = now_ms();
        let marks = gap.is_some_and(|g| now - marks_at >= g - 1_000);
        if marks {
            marks_at = now;
        }
        match execution::perps::refresh_perps_market(&state.engine, &http, marks).await {
            Ok(k) => {
                if failing || n == 0 {
                    tracing::info!("perps: {k} marks read");
                }
                failing = false;
            }
            Err(e) => {
                if !failing {
                    tracing::warn!("perps market data not read ({e}); retrying every 15 s");
                }
                failing = true;
            }
        }
        // Funding: once a minute is plenty to notice a settlement.
        if n % 4 == 0 {
            execution::perps::book_perps_funding(&state.engine, &http).await;
        }
        n += 1;
    }
}

/// The perps demo account's margin, every minute (the margin check needs a
/// read under 30 minutes old).
async fn perps_account_loop(state: AppState) {
    let mut every = tokio::time::interval(Duration::from_secs(60));
    loop {
        every.tick().await;
        execution::perps::read_perps_account(&state.engine, &state.creds).await;
    }
}

/// The perps demo account against the books, shortly after startup and then
/// every ten minutes, like the Alpaca paper route.
async fn perps_reconcile_loop(state: AppState) {
    tokio::time::sleep(Duration::from_secs(20)).await;
    let every = Duration::from_millis(pythia_core::engine::perps::PERP_RECONCILE_EVERY_MS as u64);
    loop {
        execution::perps::reconcile_perps(&state.engine, &state.creds).await;
        tokio::time::sleep(every).await;
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

/// `PYTHIA_LAB_ONLY`: the built-in indicator strategies are paused, the lab
/// books run. Lab books restored from the state file are lab strategies too;
/// pausing them with the rest froze every lab book from its first restart on,
/// because a lab signal only creates a missing book and never resumes one.
fn lab_only(e: &mut Engine) {
    use pythia_core::engine::StrategyKind;
    for s in e.state().strategies {
        if s.kind != StrategyKind::LabTargets {
            let _ = e.set_strategy_state(&s.id, StrategyState::Paused);
        } else if s.state == StrategyState::Paused {
            // Refused for a book that trades only inside an autopilot; one
            // restored before its signal says so is paused again by the signal.
            let _ = e.set_strategy_state(&s.id, StrategyState::Paper);
        }
    }
}

/// `PYTHIA_LAB_BOOKS=idle`: lab books wait, paused and holding nothing, until
/// an autopilot claims them. Anything else (or unset) keeps the default: a
/// lab book trades on its own from its first signal.
fn lab_books_idle() -> bool {
    std::env::var("PYTHIA_LAB_BOOKS").map(|v| v.trim().eq_ignore_ascii_case("idle")).unwrap_or(false)
}

/// Big moves for the operator alerts: every minute, each active autopilot's
/// equity and the price of every coin they hold (see `alerts::MoveWatch`).
async fn move_alert_loop(state: AppState) {
    let mut watch = alerts::MoveWatch::default();
    let mut every = tokio::time::interval(Duration::from_secs(60));
    loop {
        every.tick().await;
        let inputs = state.engine.lock().unwrap().move_inputs();
        let s = state.alert_log.settings();
        if let Some(sink) = &state.alert_sink {
            for ev in watch.check(&inputs, s.big_moves.hour_pct, s.big_moves.day_pct, now_ms()) {
                sink.send(ev);
            }
        }
    }
}

/// Model drift for the operator alerts: every five minutes, whether a shadow
/// model has inputs outside its trained range (see `alerts::DriftWatch`).
async fn drift_alert_loop(state: AppState) {
    let mut watch = alerts::DriftWatch::default();
    let mut every = tokio::time::interval(Duration::from_secs(300));
    loop {
        every.tick().await;
        let Some(status) = ML.get().and_then(|ml| ml.read().ok().map(|s| s.clone())) else { continue };
        if let Some(sink) = &state.alert_sink {
            for ev in watch.check(&status) {
                sink.send(ev);
            }
        }
    }
}

// ── operator alerts API ──────────────────────────────────────────────────────

/// Files behind the alert API.
#[derive(Debug, Clone, Default)]
struct AlertFiles {
    /// `<PYTHIA_DATA>/reports/notify`: the lab's `latest.json` (the last
    /// digest) and the `request.json` this API writes for a digest now.
    notify_dir: Option<std::path::PathBuf>,
    /// The engine state file, saved right away when the mute or the settings change.
    state_file: Option<std::path::PathBuf>,
    /// Besides 127.0.0.1 and ::1, who may post `POST /api/alerts/event`:
    /// exact addresses, or prefixes ending in `.` or `:` (a Docker bridge such
    /// as `172.17.`). From `PYTHIA_ALERT_EVENT_FROM`, comma separated.
    event_from: Vec<String>,
    /// Folders a posted event's image may come from: the data folder and
    /// `PYTHIA_ALERT_IMAGE_DIR`.
    image_roots: Vec<std::path::PathBuf>,
}

fn alert_routes() -> Router<AppState> {
    Router::new()
        .route("/api/alerts", get(get_alerts))
        .route("/api/alerts/test", post(post_alerts_test))
        .route("/api/alerts/mute", post(post_alerts_mute))
        .route("/api/alerts/digest", post(post_alerts_digest))
        .route("/api/alerts/settings", get(get_alert_settings).post(post_alert_settings))
        .route("/api/alerts/event", post(post_alert_event))
}

/// The settings as `GET /api/alerts/settings` answers them.
async fn get_alert_settings(State(st): State<AppState>) -> impl IntoResponse {
    Json(st.alert_log.settings().view(now_ms()))
}

/// Writes `<data>/reports/notify/settings.json`, which the lab's notify jobs
/// read so the daily digest, the weekly report and every lab post follow the
/// same switches and quiet hours as the engine.
fn write_settings_file(files: &AlertFiles, s: &alerts::AlertSettings) {
    let Some(dir) = &files.notify_dir else { return };
    let body = serde_json::to_vec_pretty(&s.view(now_ms())).unwrap_or_default();
    let write = || -> std::io::Result<()> {
        std::fs::create_dir_all(dir)?;
        let tmp = dir.join("settings.json.tmp");
        std::fs::write(&tmp, &body)?;
        std::fs::rename(&tmp, dir.join("settings.json"))
    };
    if let Err(e) = write() {
        tracing::warn!("alert settings not written for the lab: {e}");
    }
}

/// Save the engine state now, if there is a state file.
fn save_now(st: &AppState) {
    let Some(path) = &st.alert_files.state_file else { return };
    let snapshot = st.engine.lock().unwrap().to_persisted();
    if let Err(e) = pythia_core::persist::save(path, &snapshot) {
        tracing::warn!("state not saved to {}: {e}", path.display());
    }
}

/// Change the switches, quiet hours or big-move sizes: all or nothing,
/// saved with the engine state at once and written for the lab.
async fn post_alert_settings(
    State(st): State<AppState>,
    Json(patch): Json<alerts::AlertSettingsPatch>,
) -> axum::response::Response {
    let mut s = st.alert_log.settings();
    if let Err(why) = s.apply(patch) {
        return api_error(StatusCode::BAD_REQUEST, why);
    }
    st.alert_log.set_settings(s.clone());
    st.engine.lock().unwrap().set_alert_settings(s.clone());
    save_now(&st);
    write_settings_file(&st.alert_files, &s);
    Json(s.view(now_ms())).into_response()
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReadinessPatch {
    risk_step: u8,
}

/// `GET /api/lab/pumpfun`: the pump.fun lab from the same root as `/api/lab/feeds`
/// (the study's `latest.json`, `execution.json` and the pipeline strategies' paper
/// books of the last seven days). Read only; `null` fields without a data folder.
fn lab_pumpfun_routes(root: Option<std::path::PathBuf>) -> Router<AppState> {
    Router::new().route(
        "/api/lab/pumpfun",
        get(move || {
            let root = root.clone();
            async move { Json(root.map(|r| pythia_core::labview::pumpfun_lab_in(&r, now_ms())).unwrap_or_default()) }
        }),
    )
}

// ── the pump.fun wallet page (docs/PUMPFUN-LIVE.md) ─────────────────────────

/// The pump.fun wallet page's routes over the lab's data folder `root`
/// (`PYTHIA_DATA`). Reads: what the owner's live service writes (status,
/// trades, measured execution) and the wallet tool's public address. Writes:
/// lower limits (only ever below the confirmation file and the code's maxima),
/// the owner's controls (Stop and the stake's share, set and cleared from the
/// app; the share only down to 10 % without limits=wallet in the confirmation
/// file) and the kill file. Nothing reads a key, signs, sends or moves money,
/// and nothing here removes the kill file: that is done on the server by hand.
fn pumpfun_routes(root: Option<std::path::PathBuf>) -> Router<AppState> {
    use pythia_core::pumpfun_live as pf;
    let (r1, r2, r3, r4, r5, r6) = (root.clone(), root.clone(), root.clone(), root.clone(), root.clone(), root.clone());
    let (r7, r8, r9) = (root.clone(), root.clone(), root.clone());
    let (r10, r11) = (root.clone(), root);
    Router::new()
        .route(
            // The owner's block list (<data>/pumpfun_rt/blocked-mints.txt): coins the live bot and its paper twin
            // never buy. One entry added or removed per call, validated, the file written atomically.
            "/api/pumpfun/live/blocked",
            get(move || {
                let root = r10.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    Json(blocked_view(&r)).into_response()
                }
            })
            .post(move |Json(patch): Json<BlockPatch>| {
                let root = r11.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    match write_blocked(&r, patch) {
                        Ok((what, v)) => {
                            tracing::warn!("pump.fun block list changed from the app: {what}");
                            Json(v).into_response()
                        }
                        Err(why) => api_error(StatusCode::BAD_REQUEST, why),
                    }
                }
            }),
        )
        .route(
            // The owner's controls: Stop (paused), the stake's share, the brake and the floor (floor_sol), with what the service applies.
            "/api/pumpfun/live/control",
            get(move || {
                let root = r8.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    Json(pf::control_in(&r)).into_response()
                }
            })
            .post(move |Json(patch): Json<pf::ControlPatch>| {
                let root = r9.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    let what = patch.what();
                    match pf::write_control_in(&r, patch, now_ms()) {
                        Ok(c) => {
                            tracing::warn!("pump.fun live control set from the app: {what}");
                            Json(c).into_response()
                        }
                        Err(why) => api_error(StatusCode::BAD_REQUEST, why),
                    }
                }
            }),
        )
        .route(
            // The Trends page (read only): what the paper engine sees hot right now, and DexScreener's list.
            "/api/pumpfun/trends",
            get(move || {
                let root = r7.clone();
                async move {
                    Json(root.map(|r| pf::trends_in(&r)).unwrap_or_else(|| serde_json::json!({"trends": null, "dexscreener": null})))
                }
            }),
        )
        .route(
            // The feed for a page that cannot hold the socket open (behind a proxy that passes no upgrade).
            "/api/pumpfun/live/feed",
            get(move || {
                let root = r6.clone();
                async move { Json(root.and_then(|r| pf::feed_in(&r))) }
            }),
        )
        .route(
            "/api/pumpfun/live/ws",
            get(move |ws: WebSocketUpgrade| {
                let root = r5.clone();
                async move { ws.on_upgrade(move |socket| pumpfun_live_ws(socket, root)) }
            }),
        )
        .route(
            "/api/pumpfun/live",
            get(move || {
                let root = r1.clone();
                async move {
                    let mut v = match root {
                        Some(r) => pf::view_in(&r, now_ms()),
                        None => pf::view(),
                    };
                    v.sol_eur = pf::sol_eur(now_ms()).await;
                    v.eur_usd = pf::eur_usd(now_ms()).await;
                    Json(v).into_response()
                }
            }),
        )
        .route(
            "/api/pumpfun/live/trades",
            get(move || {
                let root = r2.clone();
                async move { Json(root.map(|r| pf::view_in(&r, now_ms()).trades).unwrap_or_default()) }
            }),
        )
        .route(
            "/api/pumpfun/live/settings",
            post(move |Json(patch): Json<pf::SettingsPatch>| {
                let root = r3.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    match pf::write_settings_in(&r, patch, now_ms()) {
                        Ok(s) => Json(s).into_response(),
                        Err(why) => api_error(StatusCode::BAD_REQUEST, why),
                    }
                }
            }),
        )
        .route(
            "/api/pumpfun/live/kill",
            post(move || {
                let root = r4.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    match pf::kill_in(&r, now_ms()) {
                        Ok(k) => {
                            tracing::warn!("pump.fun live kill switch set from the app");
                            Json(k).into_response()
                        }
                        Err(why) => api_error(StatusCode::INTERNAL_SERVER_ERROR, why),
                    }
                }
            }),
        )
}

// ── the owner's block list (research/lab/lab/pumpfun_rt/blocklist.py reads the same file) ──

/// The block list's file under the lab's data folder, the one the live bot, the paper twin,
/// trends.py and the meme module read.
fn blocked_path(root: &std::path::Path) -> std::path::PathBuf {
    root.join("pumpfun_rt").join("blocked-mints.txt")
}

/// The longest symbol, name or match entry, as written (blocklist.TEXT_MAX).
const BLOCK_TEXT_MAX: usize = 64;

/// The fewest letters and digits of a match entry (blocklist.MATCH_MIN).
const BLOCK_MATCH_MIN: usize = 3;

/// Letters and digits only, lower case: "$SHEKEL", "shekel " and "SHEKEL" are one (blocklist.norm).
fn block_norm(s: &str) -> String {
    s.chars().filter(|c| c.is_alphanumeric()).flat_map(|c| c.to_lowercase()).collect()
}

fn is_address(s: &str) -> bool {
    (32..=44).contains(&s.len())
        && s.chars().all(|c| c.is_ascii_alphanumeric() && !matches!(c, '0' | 'O' | 'I' | 'l'))
}

/// One entry: (kind, value) as the bot reads it, or why it is not one. A mint bare,
/// `creator:<wallet>`, `symbol:<SYMBOL>`, `name:<text>` or `match:<text>` (every coin whose
/// name or symbol contains the text); `#` and line breaks never.
fn block_entry(raw: &str) -> Result<(String, String), String> {
    let v = raw.trim();
    if v.is_empty() {
        return Err("Empty entry.".into());
    }
    let Some((kind, rest)) = v.split_once(':') else {
        return if is_address(v) {
            Ok(("mint".into(), v.into()))
        } else {
            Err("Not a mint address (base58, 32 to 44 characters).".into())
        };
    };
    let (kind, rest) = (kind.trim().to_lowercase(), rest.trim());
    match kind.as_str() {
        "creator" if is_address(rest) => Ok((kind.clone(), rest.into())),
        "creator" => Err("Not a wallet address (base58, 32 to 44 characters).".into()),
        "symbol" | "name" if block_norm(rest).is_empty() => Err(format!("A {kind} needs at least one letter or digit.")),
        "symbol" | "name" if rest.chars().count() > BLOCK_TEXT_MAX => {
            Err(format!("A {kind} has at most {BLOCK_TEXT_MAX} characters."))
        }
        "symbol" | "name" => Ok((kind.clone(), rest.into())),
        "match" if block_norm(rest).chars().count() < BLOCK_MATCH_MIN => {
            Err(format!("A match needs at least {BLOCK_MATCH_MIN} letters or digits."))
        }
        "match" if rest.chars().count() > BLOCK_TEXT_MAX => Err(format!("A match has at most {BLOCK_TEXT_MAX} characters.")),
        "match" => Ok((kind.clone(), rest.into())),
        _ => Err("Use a mint, creator:<wallet>, symbol:<SYMBOL>, name:<text> or match:<text>.".into()),
    }
}

/// The line an entry is written as.
fn block_line(kind: &str, value: &str) -> String {
    if kind == "mint" {
        value.to_string()
    } else {
        format!("{kind}:{value}")
    }
}

/// Two entries block the same coins (symbols, names and match texts after block_norm).
fn block_same(a: &(String, String), b: &(String, String)) -> bool {
    a.0 == b.0
        && match a.0.as_str() {
            "symbol" | "name" | "match" => block_norm(&a.1) == block_norm(&b.1),
            _ => a.1 == b.1,
        }
}

/// The entries of the file in order and the lines the bot ignores; an empty list without the file.
fn blocked_view(root: &std::path::Path) -> serde_json::Value {
    let text = std::fs::read_to_string(blocked_path(root)).unwrap_or_default();
    let (mut entries, mut ignored): (Vec<serde_json::Value>, Vec<serde_json::Value>) = (Vec::new(), Vec::new());
    for line in text.lines() {
        let v = line.split('#').next().unwrap_or("").trim();
        if v.is_empty() {
            continue;
        }
        match block_entry(v) {
            Ok((kind, value)) => {
                let entry = block_line(&kind, &value);
                if !entries.iter().any(|e| e["entry"] == entry.as_str()) {
                    entries.push(serde_json::json!({"entry": entry, "kind": kind, "value": value}));
                }
            }
            Err(_) => ignored.push(serde_json::Value::from(line.trim())),
        }
    }
    serde_json::json!({"path": "pumpfun_rt/blocked-mints.txt", "entries": entries, "ignored": ignored})
}

/// `POST /api/pumpfun/live/blocked`: `{"add": "symbol:SHEKEL"}`, `{"add": "match:spacex"}` or `{"remove": "..."}`.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct BlockPatch {
    add: Option<String>,
    remove: Option<String>,
}

/// Add or remove one entry; every other line (comments included) stays as it is. The file is
/// written to a temporary file next to it and renamed over it, so the bot never reads half of it.
fn write_blocked(root: &std::path::Path, patch: BlockPatch) -> Result<(String, serde_json::Value), String> {
    let (add, raw) = match (&patch.add, &patch.remove) {
        (Some(a), None) => (true, a.as_str()),
        (None, Some(r)) => (false, r.as_str()),
        _ => return Err("Send either add or remove.".into()),
    };
    if raw.chars().any(|c| c == '#' || c.is_control()) {
        return Err("An entry has no # and no line break.".into());
    }
    let e = block_entry(raw)?;
    let path = blocked_path(root);
    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => String::new(),
        Err(err) => return Err(format!("Block list not read: {err}")),
    };
    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
    let is_it = |line: &str| {
        let v = line.split('#').next().unwrap_or("").trim();
        block_entry(v).is_ok_and(|x| block_same(&x, &e))
    };
    let had = lines.iter().any(|l| is_it(l.as_str()));
    if add && !had {
        lines.push(block_line(&e.0, &e.1));
    } else if !add {
        if !had {
            return Err("That entry is not on the list.".into());
        }
        lines.retain(|l| !is_it(l.as_str()));
    }
    if add != had {
        let dir = path.parent().ok_or("No folder for the block list.")?;
        std::fs::create_dir_all(dir).map_err(|err| format!("Block list not written: {err}"))?;
        let tmp = dir.join("blocked-mints.txt.tmp");
        let mut body = lines.join("\n");
        body.push('\n');
        std::fs::write(&tmp, body).map_err(|err| format!("Block list not written: {err}"))?;
        std::fs::rename(&tmp, &path).map_err(|err| format!("Block list not written: {err}"))?;
    }
    let what = format!("{} {}", if add { "added" } else { "removed" }, block_line(&e.0, &e.1));
    Ok((what, blocked_view(root)))
}

// ── the on-chain wallet on the Real money page (docs/ONCHAIN-STAGE2.md) ──────

/// The on-chain wallet's routes over the lab's data folder `root`
/// (`PYTHIA_DATA`). Reads: what the owner's locked on-chain trader writes
/// (status, trades, its proposals and results for conversions) and the wallet
/// tool's public address. Writes: a conversion request, the confirm of a fresh
/// proposal, the owner's controls (Stop and the share of the wallet the books
/// may use, set and cleared from the app) and the kill file. Nothing here reads
/// a key, signs, sends or moves money: the trader on the server quotes, guards
/// and signs, and only what the owner confirmed. Nothing here removes the kill
/// file: that is done on the server by hand.
fn onchain_routes(root: Option<std::path::PathBuf>) -> Router<AppState> {
    use pythia_core::onchain_live as oc;
    let (r1, r2, r3, r4) = (root.clone(), root.clone(), root.clone(), root.clone());
    let (r5, r6) = (root.clone(), root);
    Router::new()
        .route(
            // The owner's controls: Stop (paused) and the books' share, with what the trader applies.
            "/api/onchain/live/control",
            get(move || {
                let root = r5.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    Json(oc::control_in(&r)).into_response()
                }
            })
            .post(move |Json(patch): Json<pythia_core::pumpfun_live::ControlPatch>| {
                let root = r6.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    let what = patch.what();
                    match oc::write_control_in(&r, patch, now_ms()) {
                        Ok(c) => {
                            tracing::warn!("on-chain control set from the app: {what}");
                            Json(c).into_response()
                        }
                        Err(why) => api_error(StatusCode::BAD_REQUEST, why),
                    }
                }
            }),
        )
        .route(
            "/api/onchain/live",
            get(move || {
                let root = r1.clone();
                async move {
                    let mut v = match root {
                        Some(r) => oc::view_in(&r, now_ms()),
                        None => oc::view(),
                    };
                    v.eur_usd = pythia_core::pumpfun_live::eur_usd(now_ms()).await;
                    Json(v).into_response()
                }
            }),
        )
        .route(
            "/api/onchain/live/convert",
            post(move |Json(ask): Json<oc::ConvertAsk>| {
                let root = r2.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    match oc::convert_in(&r, &ask.from, &ask.to, ask.amount, now_ms()) {
                        Ok(id) => Json(serde_json::json!({ "id": id })).into_response(),
                        Err(why) => api_error(StatusCode::BAD_REQUEST, why),
                    }
                }
            }),
        )
        .route(
            "/api/onchain/live/convert/confirm",
            post(move |Json(ask): Json<oc::ConfirmAsk>| {
                let root = r3.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    match oc::confirm_in(&r, &ask.id, now_ms()) {
                        Ok(()) => {
                            tracing::warn!("on-chain conversion confirmed from the app");
                            Json(serde_json::json!({ "id": ask.id, "confirmed": true })).into_response()
                        }
                        Err(why) => api_error(StatusCode::BAD_REQUEST, why),
                    }
                }
            }),
        )
        .route(
            "/api/onchain/live/kill",
            post(move || {
                let root = r4.clone();
                async move {
                    let Some(r) = root else {
                        return api_error(StatusCode::SERVICE_UNAVAILABLE, "No lab data folder is set (PYTHIA_DATA).");
                    };
                    match oc::kill_in(&r, now_ms()) {
                        Ok(k) => {
                            tracing::warn!("on-chain kill switch set from the app");
                            Json(k).into_response()
                        }
                        Err(why) => api_error(StatusCode::INTERNAL_SERVER_ERROR, why),
                    }
                }
            }),
        )
}

/// How often the live socket looks at the live service's files, and how often it sends
/// the view anyway (the euro price and the running flag move without a file changing).
const PUMPFUN_WS_POLL: Duration = Duration::from_millis(500);
const PUMPFUN_WS_VIEW_EVERY: Duration = Duration::from_secs(15);

/// `GET /api/pumpfun/live/ws`: the pump.fun page without reloading. Sends
/// `{"kind": "view", "data": <the /api/pumpfun/live view>}` and
/// `{"kind": "feed", "data": <live_feed.json>}` at once, then again whenever the
/// live service rewrites one of their files. Read only, like the GET routes.
async fn pumpfun_live_ws(mut socket: WebSocket, root: Option<std::path::PathBuf>) {
    use pythia_core::pumpfun_live as pf;
    let Some(root) = root else {
        let _ = socket
            .send(Message::Text(
                serde_json::json!({"kind": "error", "data": "No lab data folder is set (PYTHIA_DATA)."}).to_string(),
            ))
            .await;
        return;
    };
    let mut tick = tokio::time::interval(PUMPFUN_WS_POLL);
    let mut seen: Option<(Vec<Option<std::time::SystemTime>>, Option<std::time::SystemTime>)> = None;
    let mut view_sent = std::time::Instant::now();
    loop {
        tokio::select! {
            _ = tick.tick() => {
                let (view_st, feed_st) = pf::stamps_in(&root);
                let first = seen.is_none();
                let view_moved = first
                    || seen.as_ref().is_some_and(|s| s.0 != view_st)
                    || view_sent.elapsed() >= PUMPFUN_WS_VIEW_EVERY;
                let feed_moved = first || seen.as_ref().is_some_and(|s| s.1 != feed_st);
                seen = Some((view_st, feed_st));
                if view_moved {
                    let mut v = pf::view_in(&root, now_ms());
                    v.sol_eur = pf::sol_eur(now_ms()).await;
                    v.eur_usd = pf::eur_usd(now_ms()).await;
                    view_sent = std::time::Instant::now();
                    let msg = serde_json::json!({"kind": "view", "data": v}).to_string();
                    if socket.send(Message::Text(msg)).await.is_err() {
                        break;
                    }
                }
                if feed_moved {
                    let msg = serde_json::json!({"kind": "feed", "data": pf::feed_in(&root)}).to_string();
                    if socket.send(Message::Text(msg)).await.is_err() {
                        break;
                    }
                }
            }
            inbound = socket.recv() => match inbound {
                Some(Ok(_)) => {}
                _ => break,
            },
        }
    }
}

/// `POST /api/readiness/settings`: the risk step of the real money readiness
/// check (docs/LIVE-READINESS.md), written for the lab. It changes what the
/// daily check reports and nothing else; nothing is armed or traded.
async fn post_readiness_settings(Json(patch): Json<ReadinessPatch>) -> axum::response::Response {
    match pythia_core::readiness::set_settings(patch.risk_step) {
        Ok(s) => Json(s).into_response(),
        Err(why) => api_error(StatusCode::BAD_REQUEST, why),
    }
}

/// One row of a posted event: `["Equity", "$1,234"]`, or with a sign for the
/// circle: `{"label": "P&L", "value": "+$12", "sign": 12}`.
#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum EventRow {
    Pair(String, String),
    Full { label: String, value: String, #[serde(default)] sign: Option<f64> },
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EventTable {
    #[serde(default)]
    header: Vec<String>,
    rows: Vec<Vec<String>>,
}

/// `POST /api/alerts/event`: what a lab job posts.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EventReq {
    category: String,
    title: String,
    #[serde(default)]
    text: String,
    #[serde(default)]
    rows: Vec<EventRow>,
    #[serde(default)]
    table: Option<EventTable>,
    #[serde(default)]
    footer: Option<String>,
    /// A PNG or JPEG under the data folder (or `PYTHIA_ALERT_IMAGE_DIR`),
    /// sent as a photo with the card as its caption.
    #[serde(default)]
    image: Option<String>,
    #[serde(default)]
    urgent: bool,
    #[serde(default)]
    emoji: Option<String>,
    /// Two events with the same key inside the dedup window send once.
    #[serde(default)]
    key: Option<String>,
}

/// The largest image an event may carry (Telegram takes 10 MB for a photo).
const EVENT_IMAGE_MAX: u64 = 10 * 1024 * 1024;

/// Whether this address may post events: loopback, or listed.
fn event_source_allowed(ip: std::net::IpAddr, from: &[String]) -> bool {
    let ip = ip.to_canonical();
    if ip.is_loopback() {
        return true;
    }
    let s = ip.to_string();
    from.iter().any(|f| {
        let f = f.trim();
        !f.is_empty() && (s == f || ((f.ends_with('.') || f.ends_with(':')) && s.starts_with(f)))
    })
}

/// Read an event's image: a PNG or JPEG under one of `roots`, at most
/// [`EVENT_IMAGE_MAX`]. The error is for the caller and names no folder.
fn read_event_image(path: &str, roots: &[std::path::PathBuf]) -> Result<Vec<u8>, String> {
    let p = std::path::PathBuf::from(path);
    let p = if p.is_relative() {
        roots.first().map(|r| r.join(&p)).ok_or("a relative image path needs PYTHIA_DATA")?
    } else {
        p
    };
    let ext = p.extension().and_then(|e| e.to_str()).unwrap_or_default().to_ascii_lowercase();
    if !["png", "jpg", "jpeg"].contains(&ext.as_str()) {
        return Err("image must be a .png or .jpg file".into());
    }
    let real = p.canonicalize().map_err(|_| "image not found".to_string())?;
    let inside = roots.iter().filter_map(|r| r.canonicalize().ok()).any(|r| real.starts_with(r));
    if !inside {
        return Err("image must be inside the data folder or PYTHIA_ALERT_IMAGE_DIR".into());
    }
    let len = std::fs::metadata(&real).map_err(|_| "image not readable".to_string())?.len();
    if len == 0 || len > EVENT_IMAGE_MAX {
        return Err("image must be 1 byte to 10 MB".into());
    }
    let bytes = std::fs::read(&real).map_err(|_| "image not readable".to_string())?;
    if !(bytes.starts_with(b"\x89PNG") || bytes.starts_with(&[0xFF, 0xD8])) {
        return Err("image is not a PNG or JPEG".into());
    }
    Ok(bytes)
}

/// A lab job posts an alert into the engine's sender: same card design, same
/// switches, quiet hours, mute and limits as the engine's own. Localhost only
/// (and `PYTHIA_ALERT_EVENT_FROM`). 202 queued; 200 with `queued` false when
/// its category is switched off; 400 for a bad event; 403 from elsewhere;
/// 409 when alerts are off.
async fn post_alert_event(
    State(st): State<AppState>,
    axum::extract::ConnectInfo(addr): axum::extract::ConnectInfo<std::net::SocketAddr>,
    headers: axum::http::HeaderMap,
    Json(req): Json<EventReq>,
) -> axum::response::Response {
    // Behind a reverse proxy every caller looks like 127.0.0.1: a proxied
    // request is not from this machine, whatever its peer address says.
    if guard::proxied(&headers) || !event_source_allowed(addr.ip(), &st.alert_files.event_from) {
        return api_error(StatusCode::FORBIDDEN, "events are taken from this machine only (see PYTHIA_ALERT_EVENT_FROM)");
    }
    let Some(sink) = &st.alert_sink else {
        return api_error(StatusCode::CONFLICT, ALERTS_OFF);
    };
    let Some(category) = alerts::AlertCategory::parse(&req.category) else {
        let ids: Vec<&str> = alerts::AlertCategory::ALL.iter().map(|c| c.id()).collect();
        return api_error(StatusCode::BAD_REQUEST, format!("unknown category {}; one of {}", req.category, ids.join(", ")));
    };
    let title = req.title.trim();
    if title.is_empty() || title.chars().count() > 120 {
        return api_error(StatusCode::BAD_REQUEST, "title must be 1 to 120 characters");
    }
    if req.text.chars().count() > 1500 {
        return api_error(StatusCode::BAD_REQUEST, "text must be at most 1500 characters");
    }
    if req.rows.len() > 20 || req.table.as_ref().is_some_and(|t| t.rows.len() > 60 || t.header.len() > 6) {
        return api_error(StatusCode::BAD_REQUEST, "at most 20 rows and a table of 60 rows by 6 columns");
    }
    let image = match req.image.as_deref().filter(|p| !p.trim().is_empty()) {
        Some(p) => match read_event_image(p, &st.alert_files.image_roots) {
            Ok(b) => Some(b),
            Err(why) => return api_error(StatusCode::BAD_REQUEST, why),
        },
        None => None,
    };
    let settings = st.alert_log.settings();
    if !req.urgent && !settings.enabled(category) {
        return Json(serde_json::json!({ "queued": false, "reason": "off" })).into_response();
    }
    let now = now_ms();
    let key = req.key.clone().unwrap_or_else(|| format!("event:{}:{title}:{now}", category.id()));
    let rows: Vec<alerts::Row> = req
        .rows
        .into_iter()
        .map(|r| match r {
            EventRow::Pair(l, v) => alerts::Row::new(l, v),
            EventRow::Full { label, value, sign: Some(s) } => alerts::Row::toned(label, value, s),
            EventRow::Full { label, value, sign: None } => alerts::Row::new(label, value),
        })
        .collect();
    let mut ev = alerts::AlertEvent::new(alerts::AlertKind::Event, key, if req.text.is_empty() { title.to_string() } else { req.text.clone() })
        .titled(title)
        .with_rows(rows)
        .in_category(category);
    ev.summary = (!req.text.trim().is_empty()).then(|| req.text.clone());
    if let Some(t) = req.table {
        ev = ev.with_table(alerts::Table { header: t.header, rows: t.rows, more: 0 });
    }
    if let Some(f) = req.footer {
        ev = ev.with_footer(f);
    }
    if let Some(e) = req.emoji.filter(|e| !e.trim().is_empty() && e.chars().count() <= 4) {
        ev = ev.with_emoji(e);
    }
    if req.urgent {
        ev = ev.urgent();
    }
    if let Some(b) = image {
        ev = ev.with_image(b);
    }
    sink.send(ev);
    (
        StatusCode::ACCEPTED,
        Json(serde_json::json!({ "queued": true, "quietNow": settings.quiet_hours.contains(now) && !req.urgent })),
    )
        .into_response()
}

fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

/// The reason given when alerts are not configured.
const ALERTS_OFF: &str = "alerts are not configured: set PYTHIA_ALERT_WEBHOOK (Discord or Slack), \
     or PYTHIA_TELEGRAM_BOT_TOKEN and PYTHIA_TELEGRAM_CHAT_ID, and restart the server";

fn api_error(code: StatusCode, msg: impl Into<String>) -> axum::response::Response {
    (code, Json(serde_json::json!({ "error": msg.into() }))).into_response()
}

/// The last digest the lab's notify job wrote, `{ts, text}`, if any.
fn last_digest(files: &AlertFiles) -> Option<serde_json::Value> {
    let path = files.notify_dir.as_ref()?.join("latest.json");
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(path).ok()?).ok()?;
    Some(serde_json::json!({ "ts": v.get("ts")?, "text": v.get("text")? }))
}

/// Destination, mute, today's counts, the last 100 posts and the last digest.
async fn get_alerts(State(st): State<AppState>) -> impl IntoResponse {
    let view = st.alert_log.view(now_ms());
    Json(serde_json::json!({
        "enabled": st.alert_sink.is_some(),
        "destination": st.alert_sink.as_ref().map(|s| s.format().name()),
        "mutedUntilMs": view.muted_until_ms,
        "counts": view.counts,
        "recent": view.recent,
        "lastDigest": last_digest(&st.alert_files),
    }))
}

/// One test message through the configured destination, now. 200 when it
/// went through, 502 when the destination did not take it, 409 when alerts
/// are off.
async fn post_alerts_test(State(st): State<AppState>) -> impl IntoResponse {
    let Some(sink) = &st.alert_sink else {
        return api_error(StatusCode::CONFLICT, ALERTS_OFF);
    };
    let rec = sink.test().await;
    let code = if rec.delivered { StatusCode::OK } else { StatusCode::BAD_GATEWAY };
    (code, Json(rec)).into_response()
}

#[derive(Debug, Deserialize)]
struct MuteReq {
    minutes: u64,
}

/// Mute for `minutes` (0 unmutes, at most seven days). Saved with the engine
/// state right away, so a restart keeps it.
async fn post_alerts_mute(State(st): State<AppState>, Json(req): Json<MuteReq>) -> impl IntoResponse {
    if req.minutes > alerts::MAX_MUTE_MINUTES {
        return api_error(
            StatusCode::BAD_REQUEST,
            format!("minutes must be 0 to {} (seven days)", alerts::MAX_MUTE_MINUTES),
        );
    }
    let until = if req.minutes == 0 { 0 } else { now_ms() + req.minutes as i64 * 60_000 };
    st.alert_log.set_muted_until(until);
    let snapshot = {
        let mut e = st.engine.lock().unwrap();
        e.set_alerts_muted_until(until);
        st.alert_files.state_file.as_ref().map(|_| e.to_persisted())
    };
    if let (Some(path), Some(snapshot)) = (&st.alert_files.state_file, snapshot) {
        if let Err(e) = pythia_core::persist::save(path, &snapshot) {
            tracing::warn!("state not saved to {}: {e}", path.display());
        }
    }
    if until > 0 {
        tracing::info!("operator alerts muted for {} min", req.minutes);
    } else {
        tracing::info!("operator alerts unmuted");
    }
    Json(serde_json::json!({ "mutedUntilMs": until })).into_response()
}

/// Ask for a digest now: writes `reports/notify/request.json`, which the
/// lab's `notify.py --pending` (every five minutes) turns into a digest.
async fn post_alerts_digest(State(st): State<AppState>) -> impl IntoResponse {
    let Some(dir) = &st.alert_files.notify_dir else {
        return api_error(StatusCode::CONFLICT, "no data folder: set PYTHIA_DATA to the lab's data root");
    };
    let ts = now_ms();
    let body = serde_json::json!({ "ts": ts, "source": "api" });
    let write = || -> std::io::Result<()> {
        std::fs::create_dir_all(dir)?;
        let tmp = dir.join("request.json.tmp");
        std::fs::write(&tmp, serde_json::to_vec_pretty(&body).unwrap_or_default())?;
        std::fs::rename(&tmp, dir.join("request.json"))
    };
    match write() {
        Ok(()) => (StatusCode::ACCEPTED, Json(serde_json::json!({ "requestedAt": ts }))).into_response(),
        Err(e) => {
            tracing::warn!("digest request not written: {e}");
            api_error(StatusCode::INTERNAL_SERVER_ERROR, format!("digest request not written: {}", e.kind()))
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
        // The cap of a capped live test autopilot (SAFETY.md, "Capped live test").
        tracing::info!(
            "capped live test: at most ${:.2} ({}, never above ${:.2})",
            e.live_test_cap_usd(),
            pythia_core::engine::autopilot::LIVE_TEST_CAP_ENV,
            pythia_core::engine::autopilot::LIVE_TEST_CEILING_USD
        );
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
        e.set_demo_venues(creds.demo_venues(), creds.crypto_demo_venue(), creds.crypto_demo_real_prices());
        // Perps: the venue whose marks and funding the perps markets follow,
        // and whether its demo account can take orders. Never live.
        let perps_ex = execution::perps::perps_exchange_from(env_str("PYTHIA_PERPS_DEMO").as_deref(), &creds);
        e.set_perps_route(perps_ex, perps_ex.is_some() && creds.perps_exchange() == perps_ex);
        // A headless instance that only runs lab books (the VPS) pauses the
        // built-in indicator strategies, which would otherwise hold the same
        // coins and block the lab book from running its portfolio.
        let lab_only_on = std::env::var("PYTHIA_LAB_ONLY").map(|v| v == "1").unwrap_or(false);
        if lab_only_on {
            lab_only(&mut e);
            tracing::info!("PYTHIA_LAB_ONLY: built-in strategies paused, lab strategies only");
        }
        // An instance that runs autopilots (the second engine on the VPS)
        // reads the same signals but keeps every lab book idle until an
        // autopilot claims it, so a book never fills up on its own and is
        // then locked out of every autopilot.
        if lab_books_idle() {
            if lab_only_on {
                tracing::warn!("PYTHIA_LAB_BOOKS=idle and PYTHIA_LAB_ONLY are both set: lab books stay idle, so nothing trades on its own here");
            }
            e.set_lab_books_idle(true);
            tracing::info!("PYTHIA_LAB_BOOKS=idle: lab books trade only inside an autopilot");
        }
        // Maker execution on the Alpaca crypto demo route (on by default):
        // PYTHIA_ALPACA_MAKER=off sends its orders as market orders again.
        if let Some(on) = env_str("PYTHIA_ALPACA_MAKER").as_deref().and_then(parse_switch) {
            let key = pythia_core::engine::maker::ALPACA_CRYPTO_DEMO;
            let cur = e.maker_routes().get(key).copied().unwrap_or_default();
            if let Err(err) = e.set_maker_route(key, MakerSettings { enabled: on, ..cur }) {
                tracing::warn!("PYTHIA_ALPACA_MAKER not applied: {err}");
            }
        }
        // Costs follow the selected exchange even before its keys are set.
        e.set_crypto_cost_venue(
            env_str("PYTHIA_EXCHANGE").as_deref().and_then(Exchange::parse).map(CostVenue::for_exchange),
        );
    }
    // A mute set through the API holds across the restart.
    let alert_log = alerts::AlertLog::default();
    alert_log.set_muted_until(engine.lock().unwrap().alerts_muted_until());
    // So are the category switches, quiet hours and big-move sizes.
    alert_log.set_settings(engine.lock().unwrap().alert_settings().clone());
    let state = AppState {
        engine,
        tx: tx.clone(),
        webhook: Arc::new(Mutex::new(std::env::var("PYTHIA_WEBHOOK_URL").ok())),
        alert_sink: alerts::AlertConfig::from_env().map(|cfg| {
            // The URL is a secret: only that it is set and the format are logged.
            tracing::info!("operator alerts on ({:?} format)", cfg.format);
            alerts::AlertSink::spawn_with_log(cfg, alert_log.clone())
        }),
        alert_log,
        alert_files: Arc::new(AlertFiles {
            notify_dir: pythia_core::labview::data_dir().map(|d| d.join("reports").join("notify")),
            state_file: state_file(),
            event_from: env_str("PYTHIA_ALERT_EVENT_FROM")
                .map(|v| v.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect())
                .unwrap_or_default(),
            image_roots: pythia_core::labview::data_dir()
                .into_iter()
                .chain(env_str("PYTHIA_ALERT_IMAGE_DIR").map(std::path::PathBuf::from))
                .collect(),
        }),
        creds,
    };
    // The lab reads the same switches and quiet hours.
    write_settings_file(&state.alert_files, &state.alert_log.settings());
    init_ai_budget(&state);
    if let Some(n) = env_str("PYTHIA_ALERT_REJECTS").and_then(|v| v.parse::<u32>().ok()) {
        state.engine.lock().unwrap().set_alert_reject_threshold(n);
    }

    // Crypto demo on the Alpaca paper account: which coins Alpaca lists, read
    // before the first tick (at most 20 s) so no demo order goes out for a
    // coin Alpaca does not have, then once a day.
    if state.creds.crypto_demo_on_alpaca() {
        let wait = tokio::time::timeout(Duration::from_secs(20), read_crypto_demo_listing(&state))
            .await
            .unwrap_or(Duration::from_secs(600));
        tokio::spawn(crypto_demo_listing_loop(state.clone(), wait));
    }
    // The Alpaca paper account against the demo book, at startup and every
    // ten minutes, while demo orders go there.
    if state.creds.crypto_demo_on_alpaca() || state.creds.demo_venues().contains(&Venue::Alpaca) {
        tokio::spawn(demo_reconcile_loop(state.clone()));
    }
    // Perps (the lab's market-neutral M4 book): marks and funding from the
    // perps venue's public data, the demo account's margin, and the demo
    // account reconciled every ten minutes. Demo or paper only.
    if state.engine.lock().unwrap().perps_exchange().is_some() {
        tokio::spawn(perps_market_loop(state.clone()));
        if state.creds.perps_demo.is_some() {
            tokio::spawn(perps_account_loop(state.clone()));
            tokio::spawn(perps_reconcile_loop(state.clone()));
        }
    }
    // The engine daemon — the network analog of the desktop tick loop.
    tokio::spawn(tick_loop(state.clone()));
    // Crypto quotes, candles and books with failover across venues, on their
    // own tasks so a slow venue never delays a tick (see pythia_core::feeds).
    tokio::spawn(pythia_core::feeds::runner::run(
        state.engine.clone(),
        pythia_core::feeds::FeedConfig::from_env(),
        std::sync::Arc::new(|| bar_timeframe().1),
    ));
    // The AI overlay runs on its own clock so a slow model call can never
    // delay a tick, a stop check, or an order.
    tokio::spawn(ai_loop(state.clone()));
    // Model forecasts in shadow mode (scored, never traded). Idles with a
    // status message when PYTHIA_MODELS is unset.
    let _ = ML.set(pythia_core::ml::spawn());
    if state.alert_sink.is_some() {
        tokio::spawn(drift_alert_loop(state.clone()));
        tokio::spawn(move_alert_loop(state.clone()));
    }
    // Lab strategies: pick up the research lab's daily target weights.
    tokio::spawn(lab_loop(state.clone()));
    if state_file().is_some() {
        tokio::spawn(save_loop(state.clone()));
    }

    let guard_cfg = Arc::new(guard::GuardConfig::from_env());
    if !guard_cfg.origins.is_empty() {
        tracing::info!("browser origins allowed besides loopback: {}", guard_cfg.origins.join(", "));
    }
    let app = app(state.clone(), guard_cfg);

    // Loopback by default: the API has no login of its own (SECURITY.md).
    let addr = std::env::var("PYTHIA_BIND").unwrap_or_else(|_| DEFAULT_BIND.into());
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
    if !addr.starts_with("127.") && !addr.starts_with("[::1]") && !addr.starts_with("localhost") {
        tracing::warn!(
            "{addr} is not a loopback address: the API has no login of its own, so only expose it behind \
             an authenticating reverse proxy or inside a container published on 127.0.0.1 (see SECURITY.md)"
        );
    }
    log_venue_preflight(&state);

    // With the peer address: `POST /api/alerts/event` takes events from this machine only.
    axum::serve(listener, app.into_make_service_with_connect_info::<std::net::SocketAddr>()).await.unwrap();
}

/// Where the API listens when `PYTHIA_BIND` is unset: this machine only.
const DEFAULT_BIND: &str = "127.0.0.1:8787";

/// The whole HTTP API over `state`, behind the request guards.
fn app(state: AppState, guard_cfg: Arc<guard::GuardConfig>) -> Router {
    Router::new()
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
        .merge(ai_routes())
        .route("/api/live/config", post(post_live_config))
        .route("/api/live/maker", post(post_live_maker))
        .route("/api/execution/stats", get(get_execution_stats))
        .route("/api/live/account", get(get_live_account))
        .route("/api/live/verify", get(get_live_verify))
        .route("/api/live/diagnostics", get(get_live_diagnostics))
        .route("/api/live/test-order", post(post_test_order))
        .route("/api/exchanges", get(get_exchanges))
        .route("/api/wallets", get(get_wallets))
        .route("/api/ml/status", get(get_ml_status))
        .route(
            "/api/ml/picks/run",
            post(|| async {
                // M2 ranks the latest complete day now. Shadow mode: it records, it never trades.
                pythia_core::ml_picks::request_run();
                axum::http::StatusCode::ACCEPTED
            }),
        )
        // The model zoo's daily report from the lab (null until it has run). Read-only.
        .route("/api/ml/zoo", get(|| async { Json(pythia_core::labview::model_zoo()) }))
        .route("/api/tax", get(get_tax))
        .route("/api/lab", get(|| async { Json(pythia_core::labview::status()) }))
        .route("/api/cs2", get(|| async { Json(pythia_core::labview::cs2_board()) }))
        // Pokemon cards from the lab: prices, forecasts, the paper collection. Read-only.
        .route("/api/pokemon", get(|| async { Json(pythia_core::labview::pokemon()) }))
        .route("/api/lab/feeds", get(|| async { Json(pythia_core::labview::feeds()) }))
        .route("/api/lab/studies", get(|| async { Json(pythia_core::labview::studies()) }))
        // The pump.fun lab for the Lab page: the study's report, execution and paper books. Read-only.
        .merge(lab_pumpfun_routes(pythia_core::labview::data_dir()))
        .route(
            "/api/readiness/settings",
            get(|| async { Json(pythia_core::readiness::settings()) }).post(post_readiness_settings),
        )
        .route("/api/forecast/ensemble", post(post_ensemble))
        .route("/api/forecast/config", post(post_forecast_config))
        .merge(alert_routes())
        // The pump.fun wallet page: the live service's status, lower limits, the kill switch.
        .merge(pumpfun_routes(pythia_core::labview::data_dir()))
        // The on-chain wallet on the Real money page: the locked trader's status, conversions, the kill switch.
        .merge(onchain_routes(pythia_core::labview::data_dir()))
        // The dashboards run on another port in development: CORS for the
        // allowed origins only, never any web page (see guard.rs).
        .layer(guard::cors(guard_cfg.clone()))
        .layer(axum::middleware::from_fn_with_state(guard_cfg, guard::guard))
        .with_state(state)
}

/// Which providers and venues this server has keys for, in the journal at
/// startup. Names and the last four characters of a key id at most, never a secret.
fn log_venue_preflight(state: &AppState) {
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
    match state.creds.connector_env(Venue::Crypto, Environment::Demo, true, false) {
        Ok(c) => tracing::info!("Crypto demo route: {} (virtual money, no live arm needed)", c.label()),
        Err(why) => tracing::info!("Crypto demo route: off ({why})"),
    }
    let watched = watched_addresses().len();
    if watched > 0 {
        tracing::info!("Wallets: watching {watched} on-chain address(es), read-only");
    }
}

/// Tick the engine ~every 1.5s, refresh real read-only feeds periodically, and
/// broadcast the fresh state + flush any queued alerts. Mirrors the desktop
/// daemon in `src-tauri/src/lib.rs`.
async fn tick_loop(state: AppState) {
    const TICK_MS: u64 = 1500;
    // Cadences, in ticks. Equity and prediction quotes move their marks;
    // equity candles move their signals; the broker check gates live routing
    // and must stay well inside the engine's five-minute staleness window.
    // Crypto quotes, candles and books are not polled here any more: the feed
    // runner (spawned in `main`) owns them, with failover.
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
            let poly = marketdata::fetch_polymarket().await;
            let mut alpaca = marketdata::fetch_alpaca(&key, &secret, &feed).await;
            // Alpaca's crypto data is public, so these are real even without keys.
            alpaca.extend(marketdata::fetch_alpaca_crypto().await);
            let mut e = state.engine.lock().unwrap();
            e.apply_polymarket(&poly);
            e.apply_alpaca(&alpaca);
        }

        // Candle history for the Alpaca markets; crypto candles come from the feed runner.
        if n % BARS_EVERY == 1 {
            let (tf, _) = bar_timeframe();
            let (key, secret, feed) = alpaca_data_keys(&state.creds);
            let mut series = marketdata::fetch_alpaca_bars(&key, &secret, &feed, &tf, 10).await;
            // Three days, not ten: crypto never closes, so ten days of small
            // bars would overrun the single page the fetch asks for.
            series.extend(marketdata::fetch_alpaca_crypto_bars(&tf, 3).await);
            if !series.is_empty() {
                state.engine.lock().unwrap().apply_bars(&series);
            }
        }

        // Session + account state. Without a recent answer here the engine
        // refuses to route live equity entries at all.
        if n % BROKER_EVERY == 1 && has_alpaca_keys(&state.creds) {
            refresh_broker_status(&state).await;
        }

        let (json, queued, events) = {
            let mut e = state.engine.lock().unwrap();
            e.tick();
            (serde_json::to_string(&e.state()).unwrap_or_default(), e.drain_alerts(), e.drain_alert_events())
        };
        if let Some(sink) = &state.alert_sink {
            for ev in events {
                sink.send(ev);
            }
        }
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

/// Which Alpaca endpoint the broker status is read from: the live one only
/// when Alpaca itself is armed for live routing on the live endpoint. Live
/// armed for crypto alone (or not at all) leaves Alpaca on its paper account,
/// so the status comes from there; asking the live endpoint without live keys
/// failed every minute and held every US-share rebalance on the demo route.
/// With no paper keys and live keys only, the live account answers the same
/// read-only questions (clock and account), and nothing is sent there.
fn broker_status_paper(live: &LiveConfig, has_paper_keys: bool, has_live_keys: bool) -> bool {
    let alpaca_live = live.armed && !live.paper && live.venues.contains(&Venue::Alpaca);
    if alpaca_live {
        return false;
    }
    has_paper_keys || !has_live_keys
}

/// Ask Alpaca whether the market is open and whether the account may trade.
/// Uses the keys of the endpoint [`broker_status_paper`] picks.
async fn refresh_broker_status(state: &AppState) {
    let live = { state.engine.lock().unwrap().live_config() };
    let paper = broker_status_paper(&live, state.creds.alpaca_keys(true).is_some(), state.creds.alpaca_keys(false).is_some());
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
    let mut last_budget_note: Option<std::time::Instant> = None;

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
            .with_job("overlay")
            .with_timeout(Duration::from_secs(45));

        match llm::signal(&cfg, &context).await {
            // The budget said no: nothing was sent. Said once an hour in the
            // journal, not on every tick.
            Err(llm::LlmError::Budget(r)) => {
                if last_budget_note.is_none_or(|t: std::time::Instant| t.elapsed() >= Duration::from_secs(3_600)) {
                    last_budget_note = Some(std::time::Instant::now());
                    state.engine.lock().unwrap().record_ai_error(&r.to_string());
                }
            }
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
    let dto = st.engine.lock().unwrap().state_with_events();
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
    /// Give an amount to an autopilot. `confirm` is the owner's typed
    /// confirmation, which live requires.
    AutopilotStart {
        config: AutopilotConfig,
        #[serde(default)]
        confirm: bool,
    },
    /// `flatten` overrides the autopilot's own `flattenOnStop`.
    AutopilotStop {
        id: String,
        #[serde(default)]
        flatten: Option<bool>,
    },
    AutopilotPause { id: String },
    AutopilotResume { id: String },
    /// Change a running or paused autopilot in place (name, strategies,
    /// amount, stop rules). A live one needs `confirm`, and so does a looser
    /// max-loss rule.
    AutopilotUpdate {
        id: String,
        update: AutopilotUpdate,
        #[serde(default)]
        confirm: bool,
    },
}

/// Apply a command and return the fresh state so the caller updates instantly
/// (WebSocket clients also get it on the next tick).
async fn post_command(
    State(st): State<AppState>,
    Json(cmd): Json<Command>,
) -> axum::response::Response {
    // A live autopilot may not get more than the venue holds: read its free
    // cash first, with no engine lock held across the network call.
    // A higher amount for a running live autopilot is read the same way.
    let live_venue = match &cmd {
        Command::AutopilotStart { config, .. } if config.mode == AutopilotMode::Live => Some(config.venue.clone()),
        Command::AutopilotUpdate { id, update, .. } if update.capital_usd.is_some() => st
            .engine
            .lock()
            .unwrap()
            .autopilot_config(id)
            .filter(|c| c.mode == AutopilotMode::Live)
            .map(|c| c.venue),
        _ => None,
    };
    // Demo autopilots on the Alpaca paper account share it: a start, or a
    // higher amount, is checked against the account's equity.
    let paper_account = match &cmd {
        Command::AutopilotStart { config, .. } => st.engine.lock().unwrap().autopilot_needs_paper_equity(Some(config), None),
        Command::AutopilotUpdate { id, update, .. } if update.capital_usd.is_some() => {
            st.engine.lock().unwrap().autopilot_needs_paper_equity(None, Some(id))
        }
        _ => false,
    };
    let cash = match live_venue {
        Some(venue) => {
            let paper = st.engine.lock().unwrap().live_config().paper;
            match wallets::available_cash(&st.creds, &venue, paper).await {
                Ok(c) => VenueCash::Read(c),
                Err(why) => VenueCash::Failed(why),
            }
        }
        None if paper_account => match wallets::paper_account_equity(&st.creds).await {
            Ok(c) => VenueCash::Read(c),
            Err(why) => VenueCash::Failed(why),
        },
        None => VenueCash::NotRead,
    };
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
            // Refusals (why live was refused, a conflict, a bad amount) go
            // back as a 409 with the sentence.
            Command::AutopilotStart { config, confirm } => {
                refused = e.autopilot_start(config, confirm, cash).err()
            }
            Command::AutopilotStop { id, flatten } => refused = e.autopilot_stop(&id, flatten).err(),
            Command::AutopilotPause { id } => refused = e.autopilot_pause(&id).err(),
            Command::AutopilotResume { id } => refused = e.autopilot_resume(&id).err(),
            Command::AutopilotUpdate { id, update, confirm } => {
                refused = e.autopilot_update(&id, update, confirm, cash).err()
            }
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

/// `on`/`off` and the usual spellings; anything else is not a switch.
fn parse_switch(v: &str) -> Option<bool> {
    match v.trim().to_ascii_lowercase().as_str() {
        "1" | "on" | "true" | "yes" => Some(true),
        "0" | "off" | "false" | "no" => Some(false),
        _ => None,
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MakerRouteReq {
    route: String,
    settings: MakerSettings,
}

/// Change how one route works its orders: maker limits at the touch, or
/// market orders (`docs/DEMO.md`). Orders already working keep theirs.
async fn post_live_maker(State(st): State<AppState>, Json(req): Json<MakerRouteReq>) -> impl IntoResponse {
    let dto = {
        let mut e = st.engine.lock().unwrap();
        if let Err(err) = e.set_maker_route(&req.route, req.settings) {
            return (StatusCode::BAD_REQUEST, err).into_response();
        }
        e.state()
    };
    let _ = st.tx.send(serde_json::to_string(&dto).unwrap_or_default());
    Json(dto).into_response()
}

/// Maker execution per route over the last 7 and 30 days: fill rate by
/// quantity and by order, resting time, realised against modelled cost,
/// fallbacks. The same numbers are in `/api/state` as `live.makerStats`.
async fn get_execution_stats(State(st): State<AppState>) -> Json<serde_json::Value> {
    Json(execution_stats(&st.engine.lock().unwrap()))
}

fn execution_stats(e: &Engine) -> serde_json::Value {
    serde_json::json!({ "routes": e.maker_stats() })
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
    /// Send the test to the venue's demo environment instead (virtual money,
    /// needs demo keys, not the live arm).
    #[serde(default)]
    demo: bool,
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
        } else if req.demo {
            e.demo_test_notional(&req.market_id)
        } else {
            e.connection_test_notional(&req.market_id)
        };
        let sent = if req.demo {
            e.demo_connection_test_order(&req.market_id, notional)
        } else {
            e.connection_test_order(&req.market_id, notional)
        };
        if let Err(why) = sent {
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
    /// Check the venue's demo account with the demo keys instead.
    #[serde(default)]
    demo: bool,
}

/// Read-only credential check for any venue. Never places an order.
async fn get_live_verify(
    State(st): State<AppState>,
    axum::extract::Query(q): axum::extract::Query<VerifyQuery>,
) -> impl IntoResponse {
    let env = if q.demo { Environment::Demo } else { Environment::Live };
    match execution::verify_env(&st.creds, q.venue, env, q.paper).await {
        Ok(summary) => (StatusCode::OK, Json(serde_json::json!({ "ok": true, "summary": summary }))).into_response(),
        Err(e) => (StatusCode::SERVICE_UNAVAILABLE, e).into_response(),
    }
}

/// Every exchange Pythia can route to, and whether this server has keys for it.
async fn get_exchanges(State(st): State<AppState>) -> impl IntoResponse {
    let selected = st.creds.exchange.as_ref().map(|(e, ..)| *e);
    let demo = st.creds.demo_exchange();
    Json(cex::exchanges_with_demo(|e| selected == Some(e), |e| demo == Some(e)))
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

    let cfg = LlmConfig::new(provider, req.model.unwrap_or_default(), key).with_job("signal");
    match llm::signal(&cfg, &req.context).await {
        Ok(sig) => (StatusCode::OK, Json(sig)).into_response(),
        Err(e @ llm::LlmError::Budget(_)) => (StatusCode::PAYMENT_REQUIRED, e.to_string()).into_response(),
        Err(e) => {
            tracing::warn!("llm signal failed: {e}");
            (StatusCode::BAD_GATEWAY, format!("llm error: {e}")).into_response()
        }
    }
}

// ── the Claude API budget ───────────────────────────────────────────────────

fn ai_routes() -> Router<AppState> {
    Router::new()
        .route("/api/ai/budget", get(get_ai_budget).post(post_ai_budget))
        .route("/api/ai/complete", post(post_ai_complete))
        .route("/api/ai/report", get(|| async { Json(pythia_core::labview::ai_report()) }))
}

/// The process-wide budget over `<data>/ai` (or `PYTHIA_AI_DIR`), with its
/// 50/80/100 % alerts going out through the operator alerts.
fn init_ai_budget(state: &AppState) {
    let budget = pythia_core::ai_budget::Budget::open(pythia_core::ai_budget::default_dir(), "server");
    if let Some(sink) = state.alert_sink.clone() {
        budget.set_alert_hook(move |a| {
            let mut ev = alerts::AlertEvent::new(alerts::AlertKind::Event, format!("ai-budget:{}", a.percent), a.text())
                .titled(if a.percent >= 100 { "Claude API budget used up" } else { "Claude API budget" })
                .with_emoji("💳")
                .with_rows(vec![
                    alerts::Row::new("Spent", format!("${:.2}", a.spent_usd)),
                    alerts::Row::new("Lifetime cap", format!("${:.2}", a.cap_usd)),
                ]);
            if a.percent >= 100 {
                ev = ev.urgent();
            }
            sink.send(ev);
        });
    }
    match budget.dir() {
        Some(d) => tracing::info!("AI budget: ledger in {} ({:?})", d.display(), budget.caps()),
        None => tracing::warn!("AI budget: no data folder, the ledger is kept in memory only (set PYTHIA_AI_DIR)"),
    }
    if !pythia_core::ai_budget::init(budget) {
        tracing::warn!("AI budget was already in use before it was set up");
    }
}

async fn get_ai_budget() -> impl IntoResponse {
    let mut v = serde_json::to_value(pythia_core::ai_budget::global().view(now_ms())).unwrap_or_default();
    // Whether a key is there, never the key.
    v["keyConfigured"] = serde_json::json!(Provider::Anthropic.configured_in_env());
    v["models"] = serde_json::json!({
        "routine": llm::CLAUDE_ROUTINE,
        "review": llm::CLAUDE_REVIEW,
        "deep": llm::CLAUDE_DEEP,
    });
    Json(v)
}

/// Change the caps. Missing fields keep their value.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AiBudgetReq {
    #[serde(default)]
    lifetime_usd: Option<f64>,
    #[serde(default)]
    monthly_usd: Option<f64>,
    #[serde(default)]
    daily_usd: Option<f64>,
}

async fn post_ai_budget(Json(req): Json<AiBudgetReq>) -> axum::response::Response {
    let b = pythia_core::ai_budget::global();
    let cur = b.caps();
    for v in [req.lifetime_usd, req.monthly_usd, req.daily_usd].into_iter().flatten() {
        if !v.is_finite() || !(0.0..=pythia_core::ai_budget::MAX_CAP_USD).contains(&v) {
            return api_error(
                StatusCode::BAD_REQUEST,
                format!("a cap must be 0 to {} USD", pythia_core::ai_budget::MAX_CAP_USD),
            );
        }
    }
    let next = pythia_core::ai_budget::Caps {
        lifetime_usd: req.lifetime_usd.unwrap_or(cur.lifetime_usd),
        monthly_usd: req.monthly_usd.unwrap_or(cur.monthly_usd),
        daily_usd: req.daily_usd.unwrap_or(cur.daily_usd),
    };
    match b.set_caps(next) {
        Ok(c) => {
            tracing::info!("AI budget caps set: {c:?}");
            get_ai_budget().await.into_response()
        }
        Err(e) => api_error(StatusCode::INTERNAL_SERVER_ERROR, format!("caps not saved: {e}")),
    }
}

/// A lab job's Claude call (the daily brief, the weekly review). The engine
/// holds the key and the budget, so every paid call in Pythia goes through
/// one gate and one ledger.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AiCompleteReq {
    job: String,
    #[serde(default)]
    model: Option<String>,
    system: String,
    user: String,
    #[serde(default)]
    schema: Option<serde_json::Value>,
    max_tokens: u64,
    #[serde(default)]
    effort: Option<String>,
    #[serde(default)]
    batch: bool,
    #[serde(default)]
    batch_wait_sec: Option<u64>,
}

/// The largest answer a lab job may ask for. The research director (Opus,
/// adaptive thinking at effort high, through a batch) needs room for its
/// thinking and three to five pre-registration drafts.
const AI_MAX_TOKENS: u64 = 32_000;
/// The longest prompt a lab job may send, in characters (about 200K tokens):
/// the research director reads every study summary and the trial ledger.
const AI_MAX_PROMPT_CHARS: usize = 800_000;

/// 200 with the completion (its `json` is null and `parseError` says why when
/// the answer did not parse; it was billed all the same); 400 bad request;
/// 402 the budget refused; 403 not from this machine or without the key's
/// token; 503 no key; 502/504 the API failed or a batch did not finish.
async fn post_ai_complete(
    State(st): State<AppState>,
    axum::extract::ConnectInfo(addr): axum::extract::ConnectInfo<std::net::SocketAddr>,
    headers: axum::http::HeaderMap,
    Json(req): Json<AiCompleteReq>,
) -> axum::response::Response {
    // This machine, or the addresses `PYTHIA_ALERT_EVENT_FROM` allows (an
    // engine in a container sees the host's jobs from its bridge network).
    // The key token below is checked either way. A proxied request is never
    // from this machine (see `guard::proxied`).
    if guard::proxied(&headers) || !event_source_allowed(addr.ip(), &st.alert_files.event_from) {
        return api_error(StatusCode::FORBIDDEN, "AI calls are taken from this machine only (see PYTHIA_ALERT_EVENT_FROM)");
    }
    let key = std::env::var(Provider::Anthropic.env_key()).unwrap_or_default();
    if key.trim().is_empty() {
        return api_error(StatusCode::SERVICE_UNAVAILABLE, "no Claude API key on this server (ANTHROPIC_API_KEY)");
    }
    let token = headers.get("x-pythia-ai-token").and_then(|v| v.to_str().ok()).unwrap_or_default();
    if token.is_empty() || !guard::same_secret(token, &pythia_core::ai_budget::caller_token(&key)) {
        return api_error(StatusCode::FORBIDDEN, "the caller does not hold this server's Claude API key");
    }
    if let Err(why) = check_ai_request(&req) {
        return api_error(StatusCode::BAD_REQUEST, why);
    }
    let model = req.model.clone().filter(|m| !m.trim().is_empty()).unwrap_or_else(|| llm::CLAUDE_ROUTINE.into());
    let effort = match req.effort.as_deref().unwrap_or("low") {
        "medium" => Effort::Medium,
        "high" => Effort::High,
        "xhigh" => Effort::Xhigh,
        "max" => Effort::Max,
        _ => Effort::Low,
    };
    let cfg = LlmConfig::new(Provider::Anthropic, model, key)
        .with_effort(effort)
        .with_job(req.job.clone())
        .with_timeout(Duration::from_secs(240));
    let mut creq = llm::CompleteRequest::new(req.system, req.user, req.max_tokens);
    creq.schema = req.schema;
    creq.batch = req.batch;
    if let Some(s) = req.batch_wait_sec {
        creq.batch_wait = Duration::from_secs(s.clamp(10, 3_600));
    }
    match llm::complete(&cfg, &creq).await {
        Ok(c) => {
            tracing::info!(
                "AI {}: {} in / {} out tokens, ${:.4}{}",
                req.job,
                c.usage.input_tokens + c.usage.cache_read_tokens + c.usage.cache_write_tokens,
                c.usage.output_tokens,
                c.cost_usd,
                if c.batch_id.is_some() { " (batch)" } else { "" }
            );
            Json(c).into_response()
        }
        Err(llm::LlmError::Budget(r)) => (
            StatusCode::PAYMENT_REQUIRED,
            Json(serde_json::json!({ "error": r.to_string(), "refusal": r })),
        )
            .into_response(),
        Err(e @ llm::LlmError::BatchTimeout(_)) | Err(e @ llm::LlmError::Timeout(_)) => {
            api_error(StatusCode::GATEWAY_TIMEOUT, e.to_string())
        }
        Err(e) => {
            tracing::warn!("AI {} failed: {e}", req.job);
            api_error(StatusCode::BAD_GATEWAY, e.to_string())
        }
    }
}

/// The request as the endpoint accepts it: a short job name, a Claude model
/// with a price, a bounded answer.
fn check_ai_request(req: &AiCompleteReq) -> Result<(), String> {
    let job_ok = !req.job.is_empty()
        && req.job.len() <= 40
        && req.job.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-');
    if !job_ok {
        return Err("job must be 1 to 40 lower case letters, digits or dashes".into());
    }
    if let Some(m) = req.model.as_deref().filter(|m| !m.trim().is_empty()) {
        if !pythia_core::ai_budget::prices().price(m).1 {
            return Err(format!("unknown model {m}: only priced Claude models are called"));
        }
    }
    if req.max_tokens == 0 || req.max_tokens > AI_MAX_TOKENS {
        return Err(format!("maxTokens must be 1 to {AI_MAX_TOKENS}"));
    }
    if req.system.trim().is_empty() || req.user.trim().is_empty() {
        return Err("system and user must not be empty".into());
    }
    if req.system.len() + req.user.len() > AI_MAX_PROMPT_CHARS {
        return Err(format!("the prompt is too long (at most {AI_MAX_PROMPT_CHARS} characters)"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pythia_core::engine::StrategyKind;

    fn creds(vars: &[(&str, &str)]) -> Credentials {
        let map: std::collections::HashMap<String, String> =
            vars.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
        credentials_from(&move |k: &str| map.get(k).cloned())
    }

    /// Live armed for crypto alone leaves Alpaca on its paper account: the
    /// broker status (and with it the session check every US-share lab
    /// rebalance waits for) is read there, not from the live endpoint.
    #[test]
    fn the_broker_status_reads_the_live_endpoint_only_when_alpaca_is_armed_live() {
        let base = LiveConfig { armed: true, paper: false, dry_run: false, venues: vec![Venue::Crypto], timeout_sec: 120, extended_hours: false };
        assert!(broker_status_paper(&base, true, true), "live armed for crypto only: Alpaca stays paper");
        assert!(broker_status_paper(&LiveConfig { armed: false, ..base.clone() }, true, true), "disarmed: paper");
        let alpaca = LiveConfig { venues: vec![Venue::Crypto, Venue::Alpaca], ..base.clone() };
        assert!(!broker_status_paper(&alpaca, true, true), "Alpaca itself armed live: the live endpoint");
        assert!(broker_status_paper(&LiveConfig { paper: true, ..alpaca.clone() }, true, true), "armed on the paper endpoint: paper");
        assert!(broker_status_paper(&LiveConfig { armed: false, ..alpaca }, true, false));
        // Only live keys and Alpaca not armed: the read-only status still
        // comes from the account that has keys.
        assert!(!broker_status_paper(&base, false, true));
        assert!(broker_status_paper(&base, false, false), "no keys at all: paper, as before");
    }

    #[test]
    fn demo_exchange_alpaca_routes_crypto_demo_to_the_alpaca_paper_account() {
        let paper = [("APCA_API_KEY_ID", "PK"), ("APCA_API_SECRET_KEY", "PS")];
        let c = creds(&[paper[0], paper[1], ("PYTHIA_DEMO_EXCHANGE", "alpaca")]);
        assert!(c.crypto_demo_on_alpaca());
        assert_eq!(c.crypto_demo_venue(), Some(CostVenue::Alpaca));
        assert!(c.demo_venues().contains(&Venue::Crypto));
        let conn = c.connector_env(Venue::Crypto, Environment::Demo, false, false).unwrap();
        assert_eq!(conn.label(), "Alpaca (paper)");
        // What the engine is told at startup: crypto demo shown as Alpaca.
        let mut e = Engine::new();
        e.set_demo_venues(c.demo_venues(), c.crypto_demo_venue(), c.crypto_demo_real_prices());
        let live = e.state().live;
        assert!(live.demo_venues.contains(&Venue::Crypto));
        assert_eq!(live.demo_exchange, Some(CostVenue::Alpaca));

        // Only the live pair: no crypto demo route, never the live keys.
        let c = creds(&[("APCA_LIVE_API_KEY_ID", "LK"), ("APCA_LIVE_API_SECRET_KEY", "LS"), ("PYTHIA_DEMO_EXCHANGE", "alpaca")]);
        assert!(c.connector_env(Venue::Crypto, Environment::Demo, false, false).is_err());
        assert!(!c.demo_venues().contains(&Venue::Crypto));

        // A real demo exchange with its keys: behaviour as before.
        let c = creds(&[
            paper[0],
            paper[1],
            ("PYTHIA_DEMO_EXCHANGE", "bybit"),
            ("PYTHIA_DEMO_EXCHANGE_KEY", "DK"),
            ("PYTHIA_DEMO_EXCHANGE_SECRET", "DS"),
        ]);
        assert!(!c.crypto_demo_on_alpaca());
        assert_eq!(c.crypto_demo_venue(), Some(CostVenue::Bybit));
        assert_eq!(c.connector_env(Venue::Crypto, Environment::Demo, false, false).unwrap().label(), "Bybit (demo)");

        // Unset: no crypto demo route at all.
        assert!(!creds(&paper).demo_venues().contains(&Venue::Crypto));
    }

    #[test]
    fn perps_demo_keys_come_from_their_own_variables_and_never_make_a_live_connector() {
        let kf = [("KRAKEN_FUTURES_DEMO_KEY", "KK"), ("KRAKEN_FUTURES_DEMO_SECRET", "KS")];
        let by = [("BYBIT_DEMO_KEY", "BK"), ("BYBIT_DEMO_SECRET", "BS")];
        // Kraken Futures keys alone: the Kraken Futures demo route.
        let c = creds(&kf);
        assert_eq!(c.perps_exchange(), Some(PerpExchange::KrakenFutures));
        assert_eq!(c.connector_env(Venue::Perps, Environment::Demo, false, false).unwrap().label(), "Kraken Futures (demo)");
        assert!(c.connector_env(Venue::Perps, Environment::Live, false, false).err().unwrap().contains("switched off"));
        // Both, with Bybit chosen: Bybit, with its own keys.
        let c = creds(&[kf[0], kf[1], by[0], by[1], ("PYTHIA_PERPS_DEMO", "bybit")]);
        assert_eq!(c.perps_demo.as_ref().map(|p| (p.0, p.1.as_str())), Some((PerpExchange::Bybit, "BK")));
        // Bybit chosen without its own pair: the crypto demo pair of the same Bybit demo account.
        let c = creds(&[
            ("PYTHIA_PERPS_DEMO", "bybit"),
            ("PYTHIA_DEMO_EXCHANGE", "bybit"),
            ("PYTHIA_DEMO_EXCHANGE_KEY", "DK"),
            ("PYTHIA_DEMO_EXCHANGE_SECRET", "DS"),
        ]);
        assert_eq!(c.perps_demo.as_ref().map(|p| p.1.as_str()), Some("DK"));
        // A venue chosen without its keys, or switched off: no demo route.
        assert!(creds(&[("PYTHIA_PERPS_DEMO", "kraken_futures"), by[0], by[1]]).perps_demo.is_none());
        assert!(creds(&[("PYTHIA_PERPS_DEMO", "off"), kf[0], kf[1]]).perps_demo.is_none());
        // Without keys the engine still follows Kraken Futures for paper perps.
        let none = creds(&[]);
        assert_eq!(execution::perps::perps_exchange_from(None, &none), Some(PerpExchange::KrakenFutures));
        assert_eq!(execution::perps::perps_exchange_from(Some("off"), &none), None);
        assert!(!none.demo_venues().contains(&Venue::Perps));
    }

    fn with_lab_book() -> Engine {
        let mut e = Engine::new();
        let now = chrono::Utc::now().timestamp_millis();
        e.apply_lab_signal(pythia_core::lab::LabSignal {
            strategy: "tsmom_regime".into(),
            variant: "28d".into(),
            as_of_ms: now,
            generated_ms: now,
            valid_until_ms: now + 3_600_000,
            quote: "USD".into(),
            weights: [("BTC".to_string(), 0.1)].into_iter().collect(),
            regime_on: Some(true),
            evidence: Default::default(),
            autopilot_only: false,
            dropped: vec![],
            asset_class: None,
            experimental: false,
        });
        e
    }

    fn states(e: &Engine, lab: bool) -> Vec<StrategyState> {
        e.state()
            .strategies
            .iter()
            .filter(|s| (s.kind == StrategyKind::LabTargets) == lab)
            .map(|s| s.state)
            .collect()
    }

    #[test]
    fn lab_only_keeps_a_restored_lab_book_running() {
        let saved = with_lab_book().to_persisted();
        let mut e = Engine::new();
        e.apply_persisted(saved);
        lab_only(&mut e);
        assert_eq!(states(&e, true), vec![StrategyState::Paper]);
        assert!(states(&e, false).iter().all(|s| *s == StrategyState::Paused));
    }

    #[test]
    fn lab_only_resumes_a_lab_book_an_earlier_restart_paused() {
        let mut e = with_lab_book();
        e.set_strategy_state("lab:tsmom_regime", StrategyState::Paused).unwrap();
        lab_only(&mut e);
        assert_eq!(states(&e, true), vec![StrategyState::Paper]);
    }

    fn autopilot_only_signal(e: &mut Engine) {
        let now = chrono::Utc::now().timestamp_millis();
        e.apply_lab_signal(pythia_core::lab::LabSignal {
            strategy: "breakout_top10".into(),
            variant: "Donchian 20/10".into(),
            as_of_ms: now,
            generated_ms: now,
            valid_until_ms: now + 3_600_000,
            quote: "USD".into(),
            weights: [("ETH".to_string(), 0.1)].into_iter().collect(),
            regime_on: None,
            evidence: Default::default(),
            autopilot_only: true,
            dropped: vec![],
            asset_class: None,
            experimental: false,
        });
    }

    #[test]
    fn lab_only_runs_the_standalone_book_and_leaves_an_autopilot_only_book_idle() {
        let mut e = with_lab_book();
        autopilot_only_signal(&mut e);
        lab_only(&mut e);
        let lab: Vec<(String, StrategyState)> = e
            .state()
            .strategies
            .iter()
            .filter(|s| s.kind == StrategyKind::LabTargets)
            .map(|s| (s.id.clone(), s.state))
            .collect();
        assert_eq!(
            lab,
            vec![
                ("lab:tsmom_regime".to_string(), StrategyState::Paper),
                ("lab:breakout_top10".to_string(), StrategyState::Paused)
            ]
        );
    }

    #[test]
    fn idle_lab_books_stay_paused_whatever_lab_only_did() {
        let saved = with_lab_book().to_persisted();
        let mut e = Engine::new();
        e.apply_persisted(saved);
        lab_only(&mut e);
        e.set_lab_books_idle(true);
        assert_eq!(states(&e, true), vec![StrategyState::Paused]);
        autopilot_only_signal(&mut e);
        assert_eq!(states(&e, true), vec![StrategyState::Paused, StrategyState::Paused]);
    }

    #[test]
    fn execution_stats_report_each_maker_route_over_7_and_30_days_and_survive_a_restart() {
        let e = Engine::new();
        let v = execution_stats(&e);
        let routes = v["routes"].as_array().unwrap();
        assert_eq!(routes.len(), 1, "the Alpaca crypto demo route, on by default: {v}");
        assert_eq!(routes[0]["route"], "demo:alpaca:crypto");
        assert_eq!(routes[0]["d7"]["orders"], 0);
        assert!(routes[0]["d7"].get("makerFillRateQty").is_none(), "no orders, no rate");

        // Two finished orders, one 10 days ago: in the 30-day window only.
        let mut saved = serde_json::to_value(e.to_persisted()).unwrap();
        let now = chrono::Utc::now().timestamp_millis();
        let rec = |at: i64, maker: f64, fallback: bool| {
            serde_json::json!({
                "at": at, "route": "demo:alpaca:crypto", "symbol": "BTC/USD", "qty": 1.0, "filled": 1.0,
                "notional": 60000.0, "makerQty": maker, "restMs": 30000, "fallback": fallback,
                "realisedBps": if fallback { 30.0 } else { 15.0 }, "modelledBps": 27.0
            })
        };
        saved["maker_records"] = serde_json::json!([rec(now - 3_600_000, 1.0, false), rec(now - 10 * 86_400_000, 0.0, true)]);
        let mut back = Engine::new();
        back.apply_persisted(serde_json::from_value(saved).unwrap());
        let v = execution_stats(&back);
        let r = &v["routes"][0];
        assert_eq!((r["d7"]["orders"].as_u64(), r["d30"]["orders"].as_u64()), (Some(1), Some(2)));
        assert_eq!(r["d7"]["makerFillRateQty"], 1.0);
        assert_eq!(r["d30"]["makerFillRateOrders"], 0.5);
        assert_eq!(r["d30"]["fallbacks"], 1);
        assert_eq!(r["d30"]["realisedBps"], 22.5);
        assert_eq!(r["d30"]["avgRestSec"], 30.0);
        let state = serde_json::to_value(back.state()).unwrap();
        assert_eq!(state["live"]["makerStats"][0]["d30"]["orders"], 2, "and in /api/state");
    }

    #[test]
    fn the_maker_switch_reads_the_usual_spellings_and_nothing_else() {
        assert_eq!(parse_switch("off"), Some(false));
        assert_eq!(parse_switch(" ON "), Some(true));
        assert_eq!(parse_switch("0"), Some(false));
        assert_eq!(parse_switch("maybe"), None);
        let req: MakerRouteReq = serde_json::from_value(serde_json::json!({
            "route": "demo:alpaca:crypto",
            "settings": { "enabled": true, "restSec": 30, "maxTries": 2, "fallbackBandBps": 40 }
        }))
        .unwrap();
        let mut e = Engine::new();
        e.set_maker_route(&req.route, req.settings).unwrap();
        assert_eq!(e.maker_routes()["demo:alpaca:crypto"].max_tries, 2);
    }

    #[test]
    fn the_autopilot_update_command_reads_the_wire_shape_the_ui_sends() {
        let cmd: Command = serde_json::from_str(
            r#"{"cmd":"autopilotUpdate","id":"ap_1","confirm":true,"update":{"name":"Momentum","capitalUsd":5000,"sleeves":[{"strategyId":"lab:tsmom_tranches","weight":1}],"stop":{"maxLossPct":10}}}"#,
        )
        .unwrap();
        let Command::AutopilotUpdate { id, update, confirm } = cmd else { panic!("not an update") };
        assert_eq!(id, "ap_1");
        assert!(confirm);
        assert_eq!(update.capital_usd, Some(5000.0));
        assert_eq!(update.sleeves.unwrap()[0].strategy_id, "lab:tsmom_tranches");
        assert_eq!(update.stop.unwrap().max_loss_pct, Some(10.0));
        assert_eq!(update.repick_every_hours, None, "left out: unchanged");
        let cmd: Command = serde_json::from_str(r#"{"cmd":"autopilotUpdate","id":"ap_1","update":{"sleeves":[]}}"#).unwrap();
        let Command::AutopilotUpdate { update, confirm, .. } = cmd else { panic!("not an update") };
        assert!(!confirm && update.sleeves.unwrap().is_empty(), "an empty list is the auto pick");
    }

    #[test]
    fn the_autopilot_start_command_carries_a_capped_live_test_and_the_engine_holds_it_to_its_caps() {
        let cmd: Command = serde_json::from_str(
            r#"{"cmd":"autopilotStart","confirm":true,"config":{"id":"ap_t","name":"Test","mode":"live","venue":"kraken","capitalUsd":500,"liveTest":true,"sleeves":[{"strategyId":"ema-cross-1","weight":1}],"stop":{"maxLossPct":20,"onTakeProfit":"stop"},"flattenOnStop":true}}"#,
        )
        .unwrap();
        let Command::AutopilotStart { config, confirm } = cmd else { panic!("not a start") };
        assert!(confirm && config.live_test && config.is_live_test());
        // The engine refuses it above the cap, whatever the venue holds.
        let mut e = Engine::new();
        e.set_live_test_cap_usd(120.0);
        e.set_live(LiveConfig {
            armed: true,
            paper: false,
            dry_run: false,
            venues: vec![Venue::Crypto],
            timeout_sec: 120,
            extended_hours: false,
        });
        let err = e.autopilot_start(config, confirm, VenueCash::Read(10_000.0)).unwrap_err();
        assert!(err.starts_with("A capped live test may trade at most $120.00"), "{err}");
        assert_eq!(e.state().live.live_test_cap_usd, 120.0, "the app reads the cap from the state");
        // Without the flag it is a plain start: no liveTest on the wire.
        let cmd: Command = serde_json::from_str(
            r#"{"cmd":"autopilotStart","config":{"mode":"paper","venue":"kraken","capitalUsd":100}}"#,
        )
        .unwrap();
        let Command::AutopilotStart { config, confirm } = cmd else { panic!("not a start") };
        assert!(!confirm && !config.live_test);
    }
}

#[cfg(test)]
#[path = "alerts_api_tests.rs"]
mod alerts_api_tests;

#[cfg(test)]
#[path = "ai_api_tests.rs"]
mod ai_api_tests;

#[cfg(test)]
#[path = "pumpfun_api_tests.rs"]
mod pumpfun_api_tests;

#[cfg(test)]
#[path = "lab_pumpfun_api_tests.rs"]
mod lab_pumpfun_api_tests;

#[cfg(test)]
#[path = "onchain_api_tests.rs"]
mod onchain_api_tests;

#[cfg(test)]
#[path = "guard_tests.rs"]
mod guard_tests;
