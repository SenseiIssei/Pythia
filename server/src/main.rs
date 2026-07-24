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

use pythia_core::connectors::alpaca::{AlpacaAccount, AlpacaConnector, AlpacaOrder, Sizing};
use pythia_core::connectors::{MarketConnector, Side};
use pythia_core::engine::{
    AiPolicy, AiView, BrokerStatus, Engine, EngineState, LiveOrderOut, RiskLimits, StrategyConfig,
    StrategyState,
};
use pythia_core::llm::{self, Effort, LlmConfig, Provider};
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

/// Alpaca credentials from the process environment. Read fresh each time so a
/// key added to `.env` mid-session is picked up on the next refresh.
fn alpaca_env() -> (String, String, String) {
    (
        std::env::var("APCA_API_KEY_ID").unwrap_or_default(),
        std::env::var("APCA_API_SECRET_KEY").unwrap_or_default(),
        std::env::var("APCA_FEED").unwrap_or_else(|_| "iex".into()),
    )
}

fn has_alpaca_keys() -> bool {
    let (k, s, _) = alpaca_env();
    !k.trim().is_empty() && !s.trim().is_empty()
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
    let state = AppState {
        engine: Arc::new(Mutex::new(Engine::new())),
        tx: tx.clone(),
        webhook: Arc::new(Mutex::new(std::env::var("PYTHIA_WEBHOOK_URL").ok())),
    };

    // The engine daemon — the network analog of the desktop tick loop.
    tokio::spawn(tick_loop(state.clone()));
    // The AI overlay runs on its own clock so a slow model call can never
    // delay a tick, a stop check, or an order.
    tokio::spawn(ai_loop(state.clone()));

    let app = Router::new()
        .route("/api/health", get(health))
        .route("/api/preflight", get(get_preflight))
        .route("/api/state", get(get_state))
        .route("/api/stream", get(ws_stream))
        .route("/api/command", post(post_command))
        .route("/api/llm/providers", get(get_llm_providers))
        .route("/api/llm/signal", post(post_llm_signal))
        .route("/api/ai/config", post(post_ai_config))
        .route("/api/live/config", post(post_live_config))
        .route("/api/live/account", get(get_live_account))
        // The dashboards are served from a different origin in dev; allow them.
        .layer(CorsLayer::permissive())
        .with_state(state);

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
    // Alpaca preflight — the one thing a live run depends on.
    let has_alpaca = std::env::var("APCA_API_KEY_ID").map(|k| !k.trim().is_empty()).unwrap_or(false)
        && std::env::var("APCA_API_SECRET_KEY").map(|k| !k.trim().is_empty()).unwrap_or(false);
    if has_alpaca {
        tracing::info!(
            "Alpaca: keys present → real equity quotes ({} feed) + live execution available",
            std::env::var("APCA_FEED").unwrap_or_else(|_| "iex".into())
        );
    } else {
        tracing::info!("Alpaca: no keys (APCA_API_KEY_ID / APCA_API_SECRET_KEY) — equities stay simulated, live orders will be rejected");
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
    const RECONCILE_EVERY: u64 = 200; // ~5min

    let mut interval = tokio::time::interval(Duration::from_millis(TICK_MS));
    let mut n: u64 = 0;
    loop {
        interval.tick().await;
        n += 1;

        // Every network refresh happens here, with NO lock held — the engine
        // mutex is only ever taken for the synchronous apply.
        if n % QUOTES_EVERY == 1 {
            let (key, secret, feed) = alpaca_env();
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
            let (key, secret, feed) = alpaca_env();
            let mut series = marketdata::fetch_kraken_bars(kraken_min).await;
            series.extend(marketdata::fetch_alpaca_bars(&key, &secret, &feed, &tf, 10).await);
            if !series.is_empty() {
                state.engine.lock().unwrap().apply_bars(&series);
            }
        }

        // Session + account state. Without a recent answer here the engine
        // refuses to route live equity entries at all.
        if n % BROKER_EVERY == 1 && has_alpaca_keys() {
            refresh_broker_status(&state).await;
        }

        // Periodic reconciliation against the broker's position book.
        if n % RECONCILE_EVERY == 1 && has_alpaca_keys() {
            reconcile(&state).await;
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

        // Submit armed live orders off the tick loop. Resolving an order can
        // take ten seconds of polling; doing that inline would freeze price
        // updates, stop checks and every other order behind it.
        let live_orders = { state.engine.lock().unwrap().drain_live_orders() };
        for o in live_orders {
            let st = state.clone();
            tokio::spawn(async move { submit_live_order(&st, o).await });
        }
    }
}

/// Ask Alpaca whether the market is open and whether the account may trade.
async fn refresh_broker_status(state: &AppState) {
    let paper = { state.engine.lock().unwrap().state().live.paper };
    let conn = AlpacaConnector::from_fields(|k| std::env::var(k).ok(), paper);
    let (clock, account) = tokio::join!(conn.clock(), conn.account());

    let (Ok(clock), Ok(account)) = (clock, account) else {
        // Leave the previous status in place; it ages out on its own and the
        // engine blocks live entries once it does. Failing to reach the broker
        // must never look like "the market is open".
        tracing::warn!("broker status refresh failed — live entries will block once the last check goes stale");
        return;
    };

    let status = BrokerStatus {
        market_open: clock.is_open,
        next_open: Some(clock.next_open.clone()),
        day_trade_limit_reached: account.day_trade_limit_reached(),
        restricted: account.is_restricted(),
        equity: account.equity_f64(),
        buying_power: account.buying_power_f64(),
        checked_at: chrono::Utc::now().timestamp_millis(),
    };
    state.engine.lock().unwrap().set_broker_status(status);
}

/// Pull the broker's positions and make the engine's ledger match.
async fn reconcile(state: &AppState) {
    let paper = { state.engine.lock().unwrap().state().live.paper };
    let conn = AlpacaConnector::from_fields(|k| std::env::var(k).ok(), paper);
    let Ok(positions) = conn.positions().await else {
        tracing::warn!("could not fetch Alpaca positions — skipping reconciliation");
        return;
    };
    let rows: Vec<(String, f64, f64)> = positions
        .iter()
        .map(|p| (p.symbol.clone(), p.qty_f64(), p.avg_price_f64()))
        .collect();
    let diffs = state.engine.lock().unwrap().reconcile_alpaca(&rows);
    if !diffs.is_empty() {
        tracing::warn!("reconciled {} position difference(s) with Alpaca", diffs.len());
    }
}

/// Submit one live order to Alpaca (keys from env) and apply the result back to
/// the engine. Dry-run and missing-key cases resolve without any network call.
async fn submit_live_order(state: &AppState, o: LiveOrderOut) {
    if o.dry_run {
        state.engine.lock().unwrap().apply_live_reject(&o.order_id, "dry-run: not submitted");
    } else {
        let slippage_bps: f64 = std::env::var("PYTHIA_SLIPPAGE_BPS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(25.0);
        let conn = AlpacaConnector::from_fields(|k| std::env::var(k).ok(), o.paper)
            .with_slippage_bps(slippage_bps);
        if !conn.is_live_ready() {
            state.engine.lock().unwrap().apply_live_reject(
                &o.order_id,
                "Alpaca keys not set (APCA_API_KEY_ID / APCA_API_SECRET_KEY)",
            );
        } else {
            // Entries go out as dollars — no client-side share rounding, no
            // over-spend. Exits go out as shares, because "sell exactly what I
            // hold" cannot be expressed in dollars.
            let sizing = if o.reduce_only {
                Sizing::Shares(o.qty)
            } else {
                Sizing::Notional((o.qty * o.ref_price * 100.0).round() / 100.0)
            };
            let order = AlpacaOrder {
                symbol: o.symbol.clone(),
                side: o.side,
                sizing,
                ref_price: o.ref_price,
                // Deterministic: a retry of the same engine order can never
                // become a second position at the broker.
                client_order_id: format!("pythia-{}", o.order_id),
                reduce_only: o.reduce_only,
            };
            match conn.submit(&order).await {
                Ok(fill) => state.engine.lock().unwrap().apply_live_fill(&o.order_id, fill.qty, fill.price),
                Err(e) => state.engine.lock().unwrap().apply_live_reject(&o.order_id, &e.to_string()),
            }
        }
    }
    // Push the updated state so listeners see the fill/rejection promptly.
    let s = serde_json::to_string(&state.engine.lock().unwrap().state()).unwrap_or_default();
    let _ = state.tx.send(s);
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

    let (key, secret, feed) = alpaca_env();
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

    let paper = { st.engine.lock().unwrap().state().live.paper };
    if keys_set {
        let conn = AlpacaConnector::from_fields(|k| std::env::var(k).ok(), paper);
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
