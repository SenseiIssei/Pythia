//! App-wide shared state. The engine lives behind a Mutex; the tick task and
//! the command handlers both lock it briefly (never across an await).

use pythia_core::engine::Engine;
use pythia_core::execution::Credentials;
use std::sync::{Arc, Mutex};

pub struct AppState {
    /// `Arc` so the daemon can clone a handle and do network work without
    /// holding a Tauri state guard across an await.
    pub engine: Arc<Mutex<Engine>>,
    /// Cached Discord/webhook URL (from the vault) so the tick loop needn't hit
    /// the keychain every tick.
    pub webhook: Mutex<Option<String>>,
    /// Venue credentials, read from the OS keychain and cached. Refreshed
    /// whenever keys are saved or cleared — reading the keychain on every tick
    /// would prompt and stall on some platforms.
    pub creds: Mutex<Arc<Credentials>>,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            engine: Arc::new(Mutex::new(Engine::new())),
            webhook: Mutex::new(None),
            creds: Mutex::new(Arc::new(Credentials::default())),
        }
    }
}
