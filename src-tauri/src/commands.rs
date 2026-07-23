//! Tauri command surface. The frontend's `TauriEngineClient` calls these; each
//! mutation applies to the engine and immediately pushes fresh state so the UI
//! updates without waiting for the next tick.

use crate::state::AppState;
use pythia_core::connectors::alpaca::{AlpacaAccount, AlpacaConnector};
use pythia_core::connectors::{MarketConnector, OrderRequest, OrderType, Side, Venue};
use pythia_core::engine::{EngineState, LiveOrderOut, RiskLimits, StrategyConfig, StrategyState};
use pythia_core::llm::{self, LlmConfig, Provider, ProviderInfo, Signal};
use pythia_core::vault;
use std::collections::{BTreeMap, HashSet};
use tauri::{AppHandle, Emitter, Manager, State};

fn push_state(app: &AppHandle) {
    if let Some(state) = app.try_state::<AppState>() {
        let dto = state.engine.lock().unwrap().state();
        let _ = app.emit("engine://state", dto);
    }
}

fn venue_enum(name: &str) -> Option<Venue> {
    match name {
        "polymarket" => Some(Venue::Polymarket),
        "crypto" => Some(Venue::Crypto),
        "alpaca" => Some(Venue::Alpaca),
        _ => None,
    }
}

/// Recompute which venues have keys and push it into the engine.
pub fn refresh_connected(st: &AppState) {
    let mut set = HashSet::new();
    for v in vault::VENUES {
        if vault::has_keys(v) {
            if let Some(e) = venue_enum(v) {
                set.insert(e);
            }
        }
    }
    st.engine.lock().unwrap().set_connected(set);
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

#[tauri::command]
pub fn venue_status() -> Vec<(String, bool)> {
    vault::VENUES.iter().map(|v| (v.to_string(), vault::has_keys(v))).collect()
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

// ── live execution (Alpaca) ──────────────────────────────────────────────────

/// Arm/disarm real order routing. Guarded on the frontend by a typed
/// confirmation; the risk manager + kill switch still gate every order.
#[tauri::command]
pub fn set_live(app: AppHandle, app_state: State<AppState>, armed: bool, paper: bool, dry_run: bool) {
    app_state.engine.lock().unwrap().set_live(armed, paper, dry_run);
    push_state(&app);
}

/// Read-only Alpaca account check (buying power, status) for the connection test.
#[tauri::command]
pub async fn alpaca_account(paper: bool) -> Result<AlpacaAccount, String> {
    let keys = vault::get("alpaca").unwrap_or_default();
    let conn = AlpacaConnector::from_fields(|k| keys.get(k).cloned(), paper);
    if !conn.is_live_ready() {
        return Err("Alpaca keys not in vault — add them in Settings".into());
    }
    conn.account().await.map_err(|e| e.to_string())
}

/// Submit one drained live order to Alpaca (keys from the vault) and apply the
/// result. Called from the daemon tick loop; not a Tauri command.
pub async fn submit_live_order(app: &AppHandle, o: LiveOrderOut) {
    if o.dry_run {
        if let Some(st) = app.try_state::<AppState>() {
            st.engine.lock().unwrap().apply_live_reject(&o.order_id, "dry-run: not submitted");
        }
    } else {
        let keys = vault::get("alpaca").unwrap_or_default();
        let conn = AlpacaConnector::from_fields(|k| keys.get(k).cloned(), o.paper);
        if !conn.is_live_ready() {
            if let Some(st) = app.try_state::<AppState>() {
                st.engine
                    .lock()
                    .unwrap()
                    .apply_live_reject(&o.order_id, "Alpaca keys not in vault — add them in Settings");
            }
        } else {
            let req = OrderRequest {
                market_id: o.symbol.clone(),
                side: o.side,
                order_type: OrderType::Market,
                qty: o.qty,
                limit_price: None,
            };
            let res = conn.place_order(req).await;
            if let Some(st) = app.try_state::<AppState>() {
                let mut e = st.engine.lock().unwrap();
                match res {
                    Ok(fill) => e.apply_live_fill(&o.order_id, fill.qty, fill.price),
                    Err(err) => e.apply_live_reject(&o.order_id, &err.to_string()),
                }
            }
        }
    }
    push_state(app);
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
