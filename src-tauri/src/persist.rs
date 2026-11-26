//! State persistence. Saves the engine to `state.json` in the OS app-data dir
//! so the daemon resumes exactly where it left off: every minute, when the
//! window is closed to the tray, and when the app exits.

use crate::state::AppState;
use pythia_core::persist::Loaded;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{AppHandle, Manager};
use tauri_plugin_notification::NotificationExt;

/// Set once the state file was read, was missing, or was moved aside. Until
/// then nothing is saved: an exit during startup would otherwise write an empty
/// engine over the last good state.
static MAY_SAVE: AtomicBool = AtomicBool::new(false);

fn state_file(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_data_dir().ok()?;
    let _ = fs::create_dir_all(&dir);
    Some(dir.join("state.json"))
}

/// Atomic: a crash mid-save leaves the previous file, not a truncated one
/// (see `pythia_core::persist`).
pub fn save(app: &AppHandle) {
    if !MAY_SAVE.load(Ordering::Acquire) {
        return;
    }
    let Some(path) = state_file(app) else { return };
    let Some(st) = app.try_state::<AppState>() else { return };
    let data = st.engine.lock().unwrap().to_persisted();
    if let Err(e) = pythia_core::persist::save(&path, &data) {
        eprintln!("state not saved to {}: {e}", path.display());
    }
}

/// A file that does not parse is moved aside (`state.json.unreadable-<time>`)
/// before the app starts fresh, so the next save cannot overwrite it.
pub fn load(app: &AppHandle) {
    let Some(path) = state_file(app) else { return };
    let loaded = pythia_core::persist::load(&path);
    let may_save = loaded.may_save();
    if let Some(text) = loaded.notice() {
        eprintln!("{text}");
        let _ = app.notification().builder().title("Pythia").body(text).show();
    }
    if let Loaded::Restored(data) = loaded {
        if let Some(st) = app.try_state::<AppState>() {
            st.engine.lock().unwrap().apply_persisted(*data);
        }
    }
    MAY_SAVE.store(may_save, Ordering::Release);
}
