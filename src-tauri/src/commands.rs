//! Tauri command surface. The frontend's `TauriEngineClient` calls these; each
//! mutation applies to the engine and immediately pushes fresh state so the UI
//! updates without waiting for the next tick.

use crate::state::AppState;
use pythia_core::connectors::alpaca::{AlpacaAccount, AlpacaConnector, AlpacaOrder, Sizing};
use pythia_core::connectors::{MarketConnector, Side, Venue};
use pythia_core::engine::{
    AiPolicy, AiView, BrokerStatus, EngineState, LiveOrderOut, RiskLimits, StrategyConfig,
    StrategyState,
};
use pythia_core::llm::{self, LlmConfig, Provider, ProviderInfo, Signal};
use pythia_core::prefs::{self, Prefs};
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

/// Market-data credentials: the key pair for whichever endpoint is selected,
/// falling back to the other if that slot is empty.
///
/// The fallback is safe *here* and only here — `data.alpaca.markets` is
/// read-only and shared by both accounts, so borrowing the other pair fetches
/// quotes rather than touching an account. The order path deliberately has no
/// such fallback.
pub fn alpaca_data_keys(app: &AppHandle) -> (String, String) {
    let paper = current_endpoint_is_paper(app);
    for slot in [vault::alpaca_slot(paper), vault::alpaca_slot(!paper)] {
        let keys = vault::get(slot).unwrap_or_default();
        let id = keys.get("keyId").cloned().unwrap_or_default();
        let secret = keys.get("secret").cloned().unwrap_or_default();
        if !id.trim().is_empty() && !secret.trim().is_empty() {
            return (id, secret);
        }
    }
    (String::new(), String::new())
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

/// Credentials for one Alpaca endpoint.
///
/// No cross-endpoint fallback: sending live keys to the paper endpoint (or the
/// reverse) is a 401 at best, and at worst it would mean a request the user
/// believed was paper reaching the real account. An empty slot must fail as
/// "not configured", not quietly borrow the other one's keys.
fn alpaca_keys(paper: bool) -> BTreeMap<String, String> {
    vault::get(vault::alpaca_slot(paper)).unwrap_or_default()
}

/// A connector bound to the endpoint the engine currently has selected.
fn alpaca_connector(paper: bool) -> AlpacaConnector {
    let keys = alpaca_keys(paper);
    AlpacaConnector::from_fields(move |k| keys.get(k).cloned(), paper)
}

/// Which endpoint the engine is set to right now.
fn current_endpoint_is_paper(app: &AppHandle) -> bool {
    app.try_state::<AppState>()
        .map(|st| st.engine.lock().unwrap().state().live.paper)
        .unwrap_or(true)
}

/// Read-only Alpaca account check (buying power, status) for the connection test.
#[tauri::command]
pub async fn alpaca_account(paper: bool) -> Result<AlpacaAccount, String> {
    let conn = alpaca_connector(paper);
    if !conn.is_live_ready() {
        return Err(format!(
            "no {} keys saved — add them in Settings (paper and live accounts have separate keys)",
            if paper { "paper" } else { "live" }
        ));
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
        // `o.paper` is the endpoint snapshotted when the order was armed, so a
        // mid-flight endpoint change can never redirect an order.
        let conn = alpaca_connector(o.paper);
        if !conn.is_live_ready() {
            if let Some(st) = app.try_state::<AppState>() {
                st.engine.lock().unwrap().apply_live_reject(
                    &o.order_id,
                    &format!(
                        "no {} Alpaca keys saved — add them in Settings",
                        if o.paper { "paper" } else { "live" }
                    ),
                );
            }
        } else {
            // Entries in dollars (no share rounding, no over-spend), exits in
            // shares (only shares can say "close exactly what I hold").
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
                // Deterministic, so a resubmission after a dropped connection
                // resolves to the same broker order instead of a second one.
                client_order_id: format!("pythia-{}", o.order_id),
                reduce_only: o.reduce_only,
            };
            let res = conn.submit(&order).await;
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
    let conn = alpaca_connector(paper);
    if !conn.is_live_ready() {
        return;
    }
    let (clock, account) = tokio::join!(conn.clock(), conn.account());
    let (Ok(clock), Ok(account)) = (clock, account) else {
        // Deliberately leave the old status to age out — an unreachable broker
        // must never be read as "the market is open".
        return;
    };
    if let Some(st) = app.try_state::<AppState>() {
        st.engine.lock().unwrap().set_broker_status(BrokerStatus {
            market_open: clock.is_open,
            next_open: Some(clock.next_open.clone()),
            day_trade_limit_reached: account.day_trade_limit_reached(),
            restricted: account.is_restricted(),
            equity: account.equity_f64(),
            buying_power: account.buying_power_f64(),
            checked_at: chrono::Utc::now().timestamp_millis(),
        });
    }
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

/// Make the engine's position ledger match the broker's. Daemon-driven.
pub async fn reconcile_alpaca(app: &AppHandle) {
    let conn = alpaca_connector(current_endpoint_is_paper(app));
    if !conn.is_live_ready() {
        return;
    }
    let Ok(positions) = conn.positions().await else { return };
    let rows: Vec<(String, f64, f64)> =
        positions.iter().map(|p| (p.symbol.clone(), p.qty_f64(), p.avg_price_f64())).collect();
    if let Some(st) = app.try_state::<AppState>() {
        st.engine.lock().unwrap().reconcile_alpaca(&rows);
    }
    push_state(app);
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
