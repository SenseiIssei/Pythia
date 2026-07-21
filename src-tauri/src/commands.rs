//! Tauri command surface. The frontend's `TauriEngineClient` calls these; each
//! mutation applies to the engine and immediately pushes fresh state so the UI
//! updates without waiting for the next tick.

use crate::connectors::Side;
use crate::engine::{EngineState, RiskLimits, StrategyState};
use crate::state::AppState;
use tauri::{AppHandle, Emitter, Manager, State};

fn push_state(app: &AppHandle) {
    if let Some(state) = app.try_state::<AppState>() {
        let dto = state.engine.lock().unwrap().state();
        let _ = app.emit("engine://state", dto);
    }
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
pub fn manual_order(app: AppHandle, app_state: State<AppState>, market_id: String, side: Side, notional: f64) {
    app_state.engine.lock().unwrap().manual_order(&market_id, side, notional);
    push_state(&app);
}

#[tauri::command]
pub fn flatten(app: AppHandle, app_state: State<AppState>, market_id: String) {
    app_state.engine.lock().unwrap().flatten(&market_id);
    push_state(&app);
}
