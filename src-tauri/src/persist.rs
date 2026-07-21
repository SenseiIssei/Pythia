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

pub fn save(app: &AppHandle) {
    let Some(path) = state_file(app) else { return };
    let Some(st) = app.try_state::<AppState>() else { return };
    let data = st.engine.lock().unwrap().to_persisted();
    if let Ok(json) = serde_json::to_string(&data) {
        let _ = fs::write(path, json);
    }
}

pub fn load(app: &AppHandle) {
    let Some(path) = state_file(app) else { return };
    let Ok(text) = fs::read_to_string(&path) else { return };
    let Ok(data) = serde_json::from_str(&text) else { return };
    if let Some(st) = app.try_state::<AppState>() {
        st.engine.lock().unwrap().apply_persisted(data);
    }
}
