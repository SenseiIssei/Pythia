//! State persistence. Saves the engine to `state.json` in the OS app-data dir
//! so the daemon resumes exactly where it left off. Best-effort: any I/O error
//! is swallowed (a fresh engine is a fine fallback).

use crate::state::AppState;
use std::fs;
use std::path::PathBuf;
use tauri::{AppHandle, Manager};

fn state_file(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_data_dir().ok()?;
    let _ = fs::create_dir_all(&dir);
    Some(dir.join("state.json"))
}

/// Atomic: a crash mid-save leaves the previous file, not a truncated one
/// (see `pythia_core::persist`).
pub fn save(app: &AppHandle) {
    let Some(path) = state_file(app) else { return };
    let Some(st) = app.try_state::<AppState>() else { return };
    let data = st.engine.lock().unwrap().to_persisted();
    let _ = pythia_core::persist::save(&path, &data);
}

/// A file that does not parse is moved aside (`state.json.unreadable-<time>`)
/// before the app starts fresh, so the next save cannot overwrite it.
pub fn load(app: &AppHandle) {
    let Some(path) = state_file(app) else { return };
    let pythia_core::persist::Loaded::Restored(data) = pythia_core::persist::load(&path) else { return };
    if let Some(st) = app.try_state::<AppState>() {
        st.engine.lock().unwrap().apply_persisted(*data);
    }
}
