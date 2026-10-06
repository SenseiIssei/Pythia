//! Tauri command surface. The frontend's `TauriEngineClient` calls these; each
//! mutation applies to the engine and immediately pushes fresh state so the UI
//! updates without waiting for the next tick.

use crate::state::AppState;
use pythia_core::connectors::cex::{self, Exchange, ExchangeInfo};
use pythia_core::connectors::alpaca::AlpacaAccount;
use pythia_core::connectors::{Side, Venue};
use pythia_core::costs::CostVenue;
use pythia_core::engine::{
    AiPolicy, AiView, BrokerStatus, EngineState, LiveConfig, MarketDiag, RiskLimits, StrategyConfig,
    StrategyState,
};
use pythia_core::execution::{self, Credentials};
use pythia_core::forecast::ForecastConfig;
use pythia_core::llm::{self, LlmConfig, Provider, ProviderInfo, Signal};
use pythia_core::predict::{self, EnsembleKeys, EnsembleRun};
use pythia_core::prefs::{self, Prefs};
use pythia_core::research::{self, backtest::BacktestConfig, SweepReport, WalkForwardConfig};
use pythia_core::validation::{self, Passport};
use pythia_core::vault;
use pythia_core::wallets::{self, WalletSources, WalletsSnapshot, WatchedAddress};
use std::collections::BTreeMap;
use std::sync::Arc;
use tauri::{AppHandle, Emitter, Manager, State};

fn push_state(app: &AppHandle) {
    if let Some(state) = app.try_state::<AppState>() {
        let dto = state.engine.lock().unwrap().state();
        let _ = app.emit("engine://state", dto);
    }
}

/// Assemble venue credentials from the OS keychain.
///
/// Alpaca paper keys live under the `alpaca` slot and live keys under
/// `alpaca-live` (see `vault::alpaca_slot`): each pair only authenticates
/// against its own endpoint, so they are never merged or swapped. The crypto
/// exchange's *choice* lives under `crypto` (field `exchange`) while its keys
/// live in a per-exchange slot, so switching exchanges cannot send one venue's
/// key to another.
fn credentials_from_vault() -> Credentials {
    let alpaca_pair = |slot: &str| {
        vault::get(slot).and_then(|f| {
            let k = f.get("keyId")?.trim().to_string();
            let s = f.get("secret")?.trim().to_string();
            (!k.is_empty() && !s.is_empty()).then_some((k, s))
        })
    };
    let alpaca = alpaca_pair(vault::alpaca_slot(true));
    let alpaca_live = alpaca_pair(vault::alpaca_slot(false));

    let crypto = vault::get("crypto").unwrap_or_default();
    let exchange = crypto
        .get("exchange")
        .and_then(|id| Exchange::parse(id))
        .and_then(|ex| {
            let f = vault::get(&vault::exchange_slot(ex.id()))?;
            let k = f.get("key")?.trim().to_string();
            let s = f.get("secret")?.trim().to_string();
            (!k.is_empty() && !s.is_empty())
                .then(|| (ex, k, s, f.get("passphrase").cloned().unwrap_or_default()))
        });

    let flag = |m: &BTreeMap<String, String>, k: &str| {
        matches!(m.get(k).map(String::as_str), Some("1" | "true" | "on"))
    };
    // Extended hours is an arm-time choice on the Live page (it lives in the
    // engine's LiveConfig), not a stored key flag. Shorts stay a stored flag.
    let alpaca_fields = vault::get(vault::alpaca_slot(true)).unwrap_or_default();
    Credentials {
        alpaca,
        alpaca_live,
        exchange,
        alpaca_slippage_bps: None,
        alpaca_allow_shorts: flag(&alpaca_fields, "allowShorts"),
    }
}

/// Market-data credentials: the key pair for whichever endpoint is selected,
/// falling back to the other if that slot is empty.
///
/// The fallback is safe *here* and only here — `data.alpaca.markets` is
/// read-only and shared by both accounts, so borrowing the other pair fetches
/// quotes rather than touching an account. The order path deliberately has no
/// such fallback.
pub fn alpaca_data_keys(creds: &Credentials, paper: bool) -> (String, String) {
    creds
        .alpaca_keys(paper)
        .or_else(|| creds.alpaca_keys(!paper))
        .cloned()
        .unwrap_or_default()
}

/// Watch-only on-chain addresses, stored as a JSON array under the `wallets`
/// slot. Never contains a private key — see `pythia_core::wallets`.
fn watched_addresses() -> Vec<WatchedAddress> {
    vault::get(vault::WALLETS)
        .and_then(|f| f.get("addresses").cloned())
        .and_then(|raw| serde_json::from_str::<Vec<WatchedAddress>>(&raw).ok())
        .unwrap_or_default()
}

/// Re-read credentials from the keychain, cache them, and tell the engine which
/// venues are actually reachable. Call after any key change. Either Alpaca
/// slot counts as connected, otherwise someone who saved only live keys would
/// see "not connected" and a readiness checklist stuck on step one.
pub fn refresh_connected(st: &AppState) {
    let creds = Arc::new(credentials_from_vault());
    let mut connected = creds.connected_venues();
    // Polymarket has no order path, but its odds are keyless — show the badge
    // if the user stored something there.
    if vault::has_keys("polymarket") {
        connected.insert(Venue::Polymarket);
    }
    // Costs follow the exchange the user selected, keys or not: a paper fill
    // should pay what that venue would charge.
    let selected = vault::get("crypto")
        .and_then(|f| f.get("exchange").and_then(|id| Exchange::parse(id)))
        .map(CostVenue::for_exchange);
    {
        let mut e = st.engine.lock().unwrap();
        e.set_connected(connected);
        e.set_crypto_cost_venue(selected);
    }
    *st.creds.lock().unwrap() = creds;
}

/// The cached credential set, for the daemon.
pub fn credentials(st: &AppState) -> Arc<Credentials> {
    st.creds.lock().unwrap().clone()
}

/// Reload the cached webhook URL from the vault.
pub fn refresh_webhook(st: &AppState) {
    *st.webhook.lock().unwrap() = vault::get("alerts").and_then(|m| m.get("webhook").cloned());
}

#[tauri::command]
pub fn get_state(state: State<AppState>) -> EngineState {
    state.engine.lock().unwrap().state()
}

#[tauri::command]
pub fn toggle_kill(app: AppHandle, app_state: State<AppState>) {
    app_state.engine.lock().unwrap().toggle_kill();
    push_state(&app);
}

#[tauri::command]
pub fn set_limits(app: AppHandle, app_state: State<AppState>, patch: RiskLimits) {
    app_state.engine.lock().unwrap().set_limits(patch);
    push_state(&app);
}

/// Live is refused until the strategy's passport shows gates 1 to 7 green; the
/// error is the plain-language reason, for the UI to show.
#[tauri::command]
pub fn set_strategy_state(
    app: AppHandle,
    app_state: State<AppState>,
    id: String,
    state: StrategyState,
) -> Result<(), String> {
    let result = app_state.engine.lock().unwrap().set_strategy_state(&id, state);
    push_state(&app);
    result
}

#[tauri::command]
pub fn set_strategy_param(app: AppHandle, app_state: State<AppState>, id: String, key: String, value: f64) {
    app_state.engine.lock().unwrap().set_strategy_param(&id, &key, value);
    push_state(&app);
}

#[tauri::command]
pub fn add_strategy(app: AppHandle, app_state: State<AppState>, cfg: StrategyConfig) {
    app_state.engine.lock().unwrap().add_strategy(cfg);
    push_state(&app);
}

#[tauri::command]
pub fn manual_order(app: AppHandle, app_state: State<AppState>, market_id: String, side: Side, notional: f64) {
    app_state.engine.lock().unwrap().manual_order(&market_id, side, notional);
    push_state(&app);
}

#[tauri::command]
pub fn flatten(app: AppHandle, app_state: State<AppState>, market_id: String) {
    app_state.engine.lock().unwrap().flatten(&market_id);
    push_state(&app);
}

/// Let the execution policy rest orders inside the spread and learn from what
/// they cost. Off by default — a passive order that does not fill is a signal
/// acted on late or not at all, and that trade-off is the operator's to make.
#[tauri::command]
pub fn set_adaptive_execution(app: AppHandle, app_state: State<AppState>, on: bool) {
    app_state.engine.lock().unwrap().set_adaptive_execution(on);
    push_state(&app);
}

// ── secrets vault ───────────────────────────────────────────────────────────
// Keys go into the OS keychain and are never read back to the UI. `venue_status`
// only reports whether each venue *has* keys, not what they are.

#[tauri::command]
pub fn save_venue_keys(
    app: AppHandle,
    app_state: State<AppState>,
    venue: String,
    fields: BTreeMap<String, String>,
) -> Result<(), String> {
    // ignore empty fields so a blank save can't "connect" a venue
    let fields: BTreeMap<String, String> =
        fields.into_iter().filter(|(_, v)| !v.trim().is_empty()).collect();
    if fields.is_empty() {
        return Err("no values provided".into());
    }
    vault::save(&venue, &fields)?;
    refresh_connected(app_state.inner());
    if venue == "alerts" {
        refresh_webhook(app_state.inner());
    }
    push_state(&app);
    Ok(())
}

#[tauri::command]
pub fn clear_venue_keys(app: AppHandle, app_state: State<AppState>, venue: String) -> Result<(), String> {
    vault::clear(&venue)?;
    refresh_connected(app_state.inner());
    if venue == "alerts" {
        refresh_webhook(app_state.inner());
    }
    push_state(&app);
    Ok(())
}

/// Send a test message to the configured webhook.
#[tauri::command]
pub async fn test_alert(app_state: State<'_, AppState>) -> Result<(), String> {
    let url = app_state.webhook.lock().unwrap().clone();
    match url {
        Some(u) if !u.is_empty() => {
            pythia_core::alerts::post(&u, "Pythia test alert ✅ — webhook connected. You'll get fills, exits & risk trips here.").await;
            Ok(())
        }
        _ => Err("no webhook configured".into()),
    }
}

/// Which credential slots are populated — venues, exchanges and the wallet
/// address list. Values are never returned, only presence.
#[tauri::command]
pub fn venue_status() -> Vec<(String, bool)> {
    let ids: Vec<&str> = Exchange::ALL.iter().map(|e| e.id()).collect();
    vault::status(&ids)
}

// ── LLM providers (multi-provider AI signals) ────────────────────────────────
// Every provider's key lives in ONE vault blob under the "ai" pseudo-venue,
// keyed by provider id. Keys are merged/removed individually and, like all
// vault entries, never read back to the UI.

fn ai_keys() -> BTreeMap<String, String> {
    vault::get("ai").unwrap_or_default()
}

/// List providers with a `configured` flag reflecting which keys are in the vault.
#[tauri::command]
pub fn llm_providers() -> Vec<ProviderInfo> {
    let keys = ai_keys();
    llm::providers_with(|p| {
        !p.needs_key() || keys.get(p.id()).map(|k| !k.trim().is_empty()).unwrap_or(false)
    })
}

/// Store (or, on empty, remove) one provider's key, merging into the "ai" blob.
#[tauri::command]
pub fn save_llm_key(provider: String, key: String) -> Result<(), String> {
    let p = Provider::parse(&provider).ok_or_else(|| format!("unknown provider: {provider}"))?;
    let mut keys = ai_keys();
    let k = key.trim();
    if k.is_empty() {
        keys.remove(p.id());
    } else {
        keys.insert(p.id().to_string(), k.to_string());
    }
    if keys.is_empty() {
        vault::clear("ai")
    } else {
        vault::save("ai", &keys)
    }
}

/// Forget one provider's key.
#[tauri::command]
pub fn clear_llm_key(provider: String) -> Result<(), String> {
    let p = Provider::parse(&provider).ok_or_else(|| format!("unknown provider: {provider}"))?;
    let mut keys = ai_keys();
    keys.remove(p.id());
    if keys.is_empty() {
        vault::clear("ai")
    } else {
        vault::save("ai", &keys)
    }
}

// ── live execution ───────────────────────────────────────────────────────────

/// Arm/disarm real order routing. Guarded on the frontend by a typed
/// confirmation; the risk manager + kill switch still gate every order.
///
/// Arming refuses unless every requested venue passes a read-only credential
/// check. Finding out a key is wrong when the first signal fires — with the
/// order already gone — is the failure this exists to prevent.
///
/// `cfg.extendedHours` is the opt-in for the pre/post-market session; the
/// engine still only uses it when the broker reports that session running.
#[tauri::command]
pub async fn set_live(app: AppHandle, cfg: LiveConfig) -> Result<(), String> {
    let (engine, creds) = {
        let st = app.state::<AppState>();
        (st.engine.clone(), credentials(st.inner()))
    };

    if cfg.armed && !cfg.dry_run {
        for venue in &cfg.venues {
            execution::verify(&creds, *venue, cfg.paper)
                .await
                .map_err(|e| format!("cannot arm {venue:?}: {e}"))?;
        }
    }

    engine.lock().unwrap().set_live(cfg);
    push_state(&app);
    // Pick up anything that filled while we were disarmed, and fetch a fresh
    // session check for the endpoint just selected: live Alpaca entries are
    // refused until one arrives.
    execution::reconcile(&engine, &creds).await;
    refresh_broker_status(&app).await;
    push_state(&app);
    Ok(())
}

/// Read-only credential check for any venue. Places no order.
#[tauri::command]
pub async fn live_verify(app: AppHandle, venue: Venue, paper: bool) -> Result<String, String> {
    let creds = credentials(app.state::<AppState>().inner());
    execution::verify(&creds, venue, paper).await
}

/// Which endpoint the engine is set to right now.
pub fn current_endpoint_is_paper(app: &AppHandle) -> bool {
    app.try_state::<AppState>()
        .map(|st| st.engine.lock().unwrap().live_config().paper)
        .unwrap_or(true)
}

/// Per-market answer to "why hasn't this traded?".
#[tauri::command]
pub fn live_diagnostics(state: State<AppState>) -> Vec<MarketDiag> {
    state.engine.lock().unwrap().live_diagnostics()
}

/// Send one small, deliberate order through the real path.
///
/// Exists because every other route to a first live order runs through a
/// strategy signal that may not fire for hours. This proves the pipeline —
/// risk manager, connector, broker, fill, reconciliation — with a single click
/// and a known outcome, and it is the fastest way to find out that a key or an
/// endpoint is wrong. Still fully gated: the kill switch, every risk limit and
/// the session check all apply, exactly as they would to a strategy order.
#[tauri::command]
pub fn send_test_order(
    app: AppHandle,
    app_state: State<AppState>,
    market_id: String,
    notional: f64,
) -> Result<String, String> {
    let mut e = app_state.engine.lock().unwrap();
    // 0 (what the UI sends) means "the venue's minimum size": this is a
    // connection test, not a strategy, and it should risk as little as it can.
    let notional = if notional > 0.0 { notional.clamp(1.0, 5_000.0) } else { e.connection_test_notional(&market_id) };
    // Armed, venue enabled, nothing in flight, and (for Alpaca) a fresh open
    // session. Otherwise this would only paper-fill, which proves nothing.
    if let Some(why) = e.test_order_block(&market_id) {
        return Err(why);
    }
    e.manual_order(&market_id, Side::Buy, notional);
    // The engine journals what happened synchronously; surface the newest entry
    // for this market so the caller sees submit-or-reject rather than silence.
    let msg = e
        .state()
        .journal
        .iter()
        .find(|j| j.market_id.as_deref() == Some(market_id.as_str()))
        .map(|j| j.message.clone())
        .unwrap_or_else(|| "order queued".into());
    drop(e);
    push_state(&app);
    Ok(msg)
}

/// A strategy's config, its research backtest settings and its daily candles,
/// fetched without holding the engine lock across the network.
async fn research_inputs(
    app: &AppHandle,
    strategy_id: &str,
) -> Result<(StrategyConfig, BacktestConfig, research::Universe), String> {
    let st = app.state::<AppState>();
    let (cfg, bt, paper) = {
        let e = st.engine.lock().unwrap();
        let cfg = e.strategy_config(strategy_id).ok_or_else(|| format!("unknown strategy {strategy_id}"))?;
        let bt = e.research_bt(&cfg);
        (cfg, bt, e.live_config().paper)
    };
    let creds = credentials(st.inner());
    let (key, secret) = alpaca_data_keys(&creds, paper);
    let alpaca = (!key.is_empty()).then(|| (key, secret, get_prefs().alpaca_feed));
    let universe = research::fetch_daily_universe(&cfg, alpaca).await?;
    Ok((cfg, bt, universe))
}

/// Sweep a strategy's parameter grid on real daily candles, with every
/// result's deflated Sharpe and out-of-sample/in-sample ratio. Backs the
/// Optimizer page.
#[tauri::command]
pub async fn research_sweep(app: AppHandle, strategy_id: String) -> Result<SweepReport, String> {
    let (cfg, bt, universe) = research_inputs(&app, &strategy_id).await?;
    tauri::async_runtime::spawn_blocking(move || research::sweep(&cfg, &universe, &bt, 0.6))
        .await
        .map_err(|e| format!("sweep failed: {e}"))
}

/// Run validation gates 1 to 6 for one strategy on real daily candles, keep
/// the result in the engine, and return the full Strategy Passport.
#[tauri::command]
pub async fn run_validation(app: AppHandle, strategy_id: String) -> Result<Passport, String> {
    let (cfg, bt, universe) = research_inputs(&app, &strategy_id).await?;
    let now = chrono::Utc::now().timestamp_millis();
    let verdict = tauri::async_runtime::spawn_blocking(move || {
        validation::research_gates(&cfg, &universe, &bt, &WalkForwardConfig { bt, ..Default::default() }, now)
    })
    .await
    .map_err(|e| format!("validation failed: {e}"))?;
    let passport = {
        let st = app.state::<AppState>();
        let mut e = st.engine.lock().unwrap();
        e.store_research(verdict);
        e.passport(&strategy_id).ok_or_else(|| format!("unknown strategy {strategy_id}"))?
    };
    push_state(&app);
    Ok(passport)
}

/// Read-only Alpaca account check (buying power, status) for the connection test.
///
/// Each endpoint is tested with its own slot's keys, so a 401 names the slot
/// that is wrong instead of blaming the other account.
#[tauri::command]
pub async fn alpaca_account(app: AppHandle, paper: bool) -> Result<AlpacaAccount, String> {
    let creds = credentials(app.state::<AppState>().inner());
    let conn = creds.alpaca_connector(paper, false).map_err(|_| {
        format!(
            "no {} keys saved: add them in Settings (paper and live accounts have separate keys)",
            if paper { "paper" } else { "live" }
        )
    })?;
    conn.account().await.map_err(|e| e.to_string())
}

// ── exchanges & wallets ──────────────────────────────────────────────────────

/// Every exchange Pythia can route to, with a `configured` flag from the vault.
#[tauri::command]
pub fn exchanges() -> Vec<ExchangeInfo> {
    cex::exchanges_with(|e| vault::has_keys(&vault::exchange_slot(e.id())))
}

/// Store one exchange's credentials and make it the active crypto venue.
#[tauri::command]
pub fn save_exchange_keys(
    app: AppHandle,
    app_state: State<AppState>,
    exchange: String,
    fields: BTreeMap<String, String>,
) -> Result<(), String> {
    let ex = Exchange::parse(&exchange).ok_or_else(|| format!("unknown exchange: {exchange}"))?;
    let fields: BTreeMap<String, String> =
        fields.into_iter().filter(|(_, v)| !v.trim().is_empty()).collect();
    if !fields.contains_key("key") || !fields.contains_key("secret") {
        return Err("both an API key and a secret are required".into());
    }
    if ex.needs_passphrase() && !fields.contains_key("passphrase") {
        return Err(format!("{} also needs the API passphrase you chose", ex.label()));
    }
    vault::save(&vault::exchange_slot(ex.id()), &fields)?;

    // Selecting an exchange is a separate slot so the choice survives a key wipe.
    let mut crypto = vault::get("crypto").unwrap_or_default();
    crypto.insert("exchange".into(), ex.id().into());
    vault::save("crypto", &crypto)?;

    refresh_connected(app_state.inner());
    push_state(&app);
    Ok(())
}

#[tauri::command]
pub fn clear_exchange_keys(app: AppHandle, app_state: State<AppState>, exchange: String) -> Result<(), String> {
    let ex = Exchange::parse(&exchange).ok_or_else(|| format!("unknown exchange: {exchange}"))?;
    vault::clear(&vault::exchange_slot(ex.id()))?;
    refresh_connected(app_state.inner());
    push_state(&app);
    Ok(())
}

/// Read the watch-only address list back (addresses are public data).
#[tauri::command]
pub fn wallet_addresses() -> Vec<WatchedAddress> {
    watched_addresses()
}

/// Replace the watch-only address list. Rejects anything that is not a
/// plausible address, and never accepts a key or seed phrase.
#[tauri::command]
pub fn save_wallet_addresses(list: Vec<WatchedAddress>) -> Result<(), String> {
    for w in &list {
        w.validate().map_err(|e| format!("{}: {e}", w.address))?;
    }
    if list.is_empty() {
        return vault::clear(vault::WALLETS);
    }
    let json = serde_json::to_string(&list).map_err(|e| e.to_string())?;
    let mut fields = BTreeMap::new();
    fields.insert("addresses".to_string(), json);
    vault::save(vault::WALLETS, &fields)
}

/// The unified balance sheet across broker, exchange and watched addresses.
/// Read-only: this command cannot move anything.
#[tauri::command]
pub async fn wallet_snapshot(app: AppHandle) -> WalletsSnapshot {
    let (creds, paper) = {
        let st = app.state::<AppState>();
        let creds = credentials(st.inner());
        let paper = st.engine.lock().unwrap().live_config().paper;
        (creds, paper)
    };
    let sources = WalletSources {
        // The account for the selected endpoint, with that endpoint's own keys.
        alpaca: creds.alpaca_keys(paper).cloned().map(|(k, s)| (k, s, paper)),
        exchanges: creds
            .exchange
            .clone()
            .map(|(ex, k, s, p)| vec![(ex, k, s, p)])
            .unwrap_or_default(),
        addresses: watched_addresses(),
    };
    wallets::snapshot(&sources).await
}

// ── forecasting ──────────────────────────────────────────────────────────────

/// Every provider with a key in the vault, ready for an ensemble run.
fn ensemble_keys() -> EnsembleKeys {
    let keys = ai_keys();
    EnsembleKeys::from_map(|k| keys.get(k).cloned())
}

/// Ask every configured provider about one market, independently, and fold the
/// answers into that market's forecast. One API call per provider — this is the
/// expensive operation in the whole app, so it is always explicit.
#[tauri::command]
pub async fn run_ensemble(app: AppHandle, market_id: String, notes: String) -> Result<EnsembleRun, String> {
    let engine = app.state::<AppState>().engine.clone();
    let run = predict::ensemble_for_market(&engine, &ensemble_keys(), &market_id, &notes).await?;
    push_state(&app);
    Ok(run)
}

/// Update the forecasting tunables (horizon, costs, bootstrap trust, …).
#[tauri::command]
pub fn set_forecast_config(app: AppHandle, app_state: State<AppState>, cfg: ForecastConfig) {
    app_state.engine.lock().unwrap().set_forecast_config(cfg);
    push_state(&app);
}

#[tauri::command]
pub fn forecast_config(app_state: State<AppState>) -> ForecastConfig {
    app_state.engine.lock().unwrap().forecast_config()
}

/// Turn the AI overlay on/off from the cockpit.
#[tauri::command]
pub fn set_ai_policy(
    app: AppHandle,
    app_state: State<AppState>,
    enabled: bool,
    ttl_sec: Option<u64>,
    veto_confidence: Option<f64>,
    max_boost: Option<f64>,
) {
    let d = AiPolicy::default();
    let policy = AiPolicy {
        enabled,
        ttl_sec: ttl_sec.unwrap_or(d.ttl_sec).clamp(30, 86_400),
        veto_confidence: veto_confidence.unwrap_or(d.veto_confidence).clamp(0.0, 1.0),
        // Hard ceiling: an agreeing model may nudge size, never multiply it.
        max_boost: max_boost.unwrap_or(d.max_boost).clamp(1.0, 1.5),
    };
    app_state.engine.lock().unwrap().set_ai_policy(policy);
    push_state(&app);
}

/// Refresh the broker session/account snapshot the engine gates live entries on.
/// Called from the daemon loop; not a Tauri command.
pub async fn refresh_broker_status(app: &AppHandle) {
    let paper = current_endpoint_is_paper(app);
    let Some(st) = app.try_state::<AppState>() else { return };
    // The selected endpoint's own keys; no keys there means no check, and the
    // engine keeps refusing live Alpaca entries, which is the correct outcome.
    let Ok(conn) = credentials(st.inner()).alpaca_connector(paper, false) else { return };
    let (session, account) = tokio::join!(conn.session(), conn.account());
    let (Ok((clock, extended_open, session_end)), Ok(account)) = (session, account) else {
        // Deliberately leave the old status to age out — an unreachable broker
        // must never be read as "the market is open".
        return;
    };
    st.engine.lock().unwrap().set_broker_status(BrokerStatus {
        market_open: clock.is_open,
        extended_open,
        session_end,
        next_open: Some(clock.next_open.clone()),
        day_trade_limit_reached: account.day_trade_limit_reached(),
        restricted: account.is_restricted(),
        equity: account.equity_f64(),
        buying_power: account.buying_power_f64(),
        checked_at: chrono::Utc::now().timestamp_millis(),
    });
}

/// One pass of the AI overlay: pick the next market, ask the configured model,
/// feed the view back into the engine. Daemon-driven; not a Tauri command.
///
/// Runs on its own timer rather than inside the tick loop — a model call takes
/// seconds, and nothing about price updates, stop checks or order routing
/// should ever wait on one.
pub async fn ai_overlay_pass(app: &AppHandle, cursor: usize) -> bool {
    let Some(st) = app.try_state::<AppState>() else { return false };
    let (enabled, candidates) = {
        let e = st.engine.lock().unwrap();
        (e.ai_enabled(), e.ai_candidates())
    };
    if !enabled || candidates.is_empty() {
        return false;
    }

    let market_id = candidates[cursor % candidates.len()].clone();
    let Some(context) = ({
        let e = st.engine.lock().unwrap();
        e.ai_context(&market_id)
    }) else {
        return false;
    };

    let saved = get_prefs();
    let provider = saved.provider();
    let key = ai_keys().get(provider.id()).cloned().unwrap_or_default();
    if provider.needs_key() && key.trim().is_empty() {
        st.engine
            .lock()
            .unwrap()
            .record_ai_error(&format!("{} has no key — add one in Settings", provider.id()));
        return true;
    }

    let cfg = LlmConfig::new(provider, saved.ai_model.clone(), key)
        .with_effort(saved.effort())
        .with_timeout(std::time::Duration::from_secs(45));

    match llm::signal(&cfg, &context).await {
        Ok(sig) => {
            let view = AiView {
                market_id,
                direction: format!("{:?}", sig.direction).to_lowercase(),
                probability: sig.probability,
                confidence: sig.confidence,
                rationale: sig.rationale,
                model: if sig.served_by.is_empty() { sig.model } else { sig.served_by },
                ts: chrono::Utc::now().timestamp_millis(),
                latency_ms: sig.latency_ms,
            };
            st.engine.lock().unwrap().apply_ai_view(view, sig.input_tokens, sig.output_tokens);
        }
        // A failed call is "no opinion" — never a reason to stop trading.
        Err(e) => st.engine.lock().unwrap().record_ai_error(&e.to_string()),
    }
    push_state(app);
    true
}

// ── preferences ─────────────────────────────────────────────────────────────
// Non-secret settings, stored beside the keys. Unlike credentials these ARE
// returned to the UI — that's the point of a settings page.

/// Load saved preferences, falling back to defaults on a first run.
#[tauri::command]
pub fn get_prefs() -> Prefs {
    vault::get(prefs::VAULT_KEY).map(|m| Prefs::from_map(&m)).unwrap_or_default()
}

/// Persist preferences. Values are sanitized before storage, so a bad entry is
/// corrected once here rather than re-validated everywhere it's read.
#[tauri::command]
pub fn save_prefs(app: AppHandle, next: Prefs) -> Result<Prefs, String> {
    let clean = next.sanitized();
    vault::save(prefs::VAULT_KEY, &clean.to_map())?;
    push_state(&app);
    Ok(clean)
}

/// Verify a stored provider key by asking for one throwaway signal.
///
/// "Saved" and "works" are different claims, and the gap between them is where
/// a typo'd key hides: the Settings page shows a green badge, the overlay logs
/// a 401 nobody reads, and the model silently never has an opinion. This closes
/// it by actually spending one cheap call.
#[tauri::command]
pub async fn test_llm_key(provider: String) -> Result<String, String> {
    let p = Provider::parse(&provider).ok_or_else(|| format!("unknown provider: {provider}"))?;
    let key = ai_keys().get(p.id()).cloned().unwrap_or_default();
    if p.needs_key() && key.trim().is_empty() {
        return Err("no key saved for this provider".into());
    }
    let saved = get_prefs();
    let model = if p == saved.provider() { saved.ai_model.clone() } else { String::new() };
    let cfg = LlmConfig::new(p, model, key)
        .with_effort(pythia_core::llm::Effort::Low)
        .with_timeout(std::time::Duration::from_secs(30));

    let sig = llm::signal(
        &cfg,
        "Connectivity check only. Market: TEST. No data provided. \
         Reply with a neutral, zero-confidence signal.",
    )
    .await
    .map_err(|e| e.to_string())?;

    Ok(format!(
        "{} answered in {}ms ({} in / {} out tokens)",
        if sig.served_by.is_empty() { sig.model } else { sig.served_by },
        sig.latency_ms,
        sig.input_tokens,
        sig.output_tokens
    ))
}

/// Ask a provider for a signal on one market. Key comes from the vault; the
/// frontend only ever sends provider/model/context.
#[tauri::command]
pub async fn llm_signal(provider: String, model: String, context: String) -> Result<Signal, String> {
    let p = Provider::parse(&provider).ok_or_else(|| format!("unknown provider: {provider}"))?;
    let key = ai_keys().get(p.id()).cloned().unwrap_or_default();
    if p.needs_key() && key.trim().is_empty() {
        return Err(format!("{} not configured — add a key in Settings", p.id()));
    }
    let cfg = LlmConfig::new(p, model, key);
    llm::signal(&cfg, &context).await.map_err(|e| e.to_string())
}
