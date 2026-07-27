//! Tauri command surface. The frontend's `TauriEngineClient` calls these; each
//! mutation applies to the engine and immediately pushes fresh state so the UI
//! updates without waiting for the next tick.

use crate::state::AppState;
use pythia_core::connectors::alpaca::{AlpacaAccount, AlpacaConnector};
use pythia_core::connectors::cex::{self, Exchange, ExchangeInfo};
use pythia_core::connectors::{Side, Venue};
use pythia_core::engine::{EngineState, LiveConfig, RiskLimits, StrategyConfig, StrategyState};
use pythia_core::execution::{self, Credentials};
use pythia_core::forecast::ForecastConfig;
use pythia_core::llm::{self, LlmConfig, Provider, ProviderInfo, Signal};
use pythia_core::predict::{self, EnsembleKeys, EnsembleRun};
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
/// Alpaca lives under the `alpaca` slot; the crypto exchange's *choice* lives
/// under `crypto` (field `exchange`) while its keys live in a per-exchange slot,
/// so switching exchanges cannot send one venue's key to another.
fn credentials_from_vault() -> Credentials {
    let alpaca = vault::get("alpaca").and_then(|f| {
        let k = f.get("keyId")?.trim().to_string();
        let s = f.get("secret")?.trim().to_string();
        (!k.is_empty() && !s.is_empty()).then_some((k, s))
    });

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
    let alpaca_fields = vault::get("alpaca").unwrap_or_default();
    Credentials {
        alpaca,
        exchange,
        alpaca_extended_hours: flag(&alpaca_fields, "extendedHours"),
        alpaca_allow_shorts: flag(&alpaca_fields, "allowShorts"),
    }
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
/// venues are actually reachable. Call after any key change.
pub fn refresh_connected(st: &AppState) {
    let creds = Arc::new(credentials_from_vault());
    let mut connected = creds.connected_venues();
    // Polymarket has no order path, but its odds are keyless — show the badge
    // if the user stored something there.
    if vault::has_keys("polymarket") {
        connected.insert(Venue::Polymarket);
    }
    st.engine.lock().unwrap().set_connected(connected);
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

#[tauri::command]
pub fn set_strategy_state(app: AppHandle, app_state: State<AppState>, id: String, state: StrategyState) {
    app_state.engine.lock().unwrap().set_strategy_state(&id, state);
    push_state(&app);
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
    // Pick up anything that filled while we were disarmed.
    execution::reconcile(&engine, &creds).await;
    push_state(&app);
    Ok(())
}

/// Read-only credential check for any venue. Places no order.
#[tauri::command]
pub async fn live_verify(app: AppHandle, venue: Venue, paper: bool) -> Result<String, String> {
    let creds = credentials(app.state::<AppState>().inner());
    execution::verify(&creds, venue, paper).await
}

/// Read-only Alpaca account check (buying power, status) for the connection test.
#[tauri::command]
pub async fn alpaca_account(app: AppHandle, paper: bool) -> Result<AlpacaAccount, String> {
    let creds = credentials(app.state::<AppState>().inner());
    let (key, secret) = creds
        .alpaca
        .clone()
        .ok_or("Alpaca keys not in vault — add them in Settings")?;
    AlpacaConnector::new(Some(key), Some(secret), paper)
        .account()
        .await
        .map_err(|e| e.to_string())
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
        alpaca: creds.alpaca.clone().map(|(k, s)| (k, s, paper)),
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
