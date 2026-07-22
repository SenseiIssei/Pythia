//! App-wide shared state. The engine lives behind a Mutex; the tick task and
//! the command handlers both lock it briefly (never across an await).

use pythia_core::engine::Engine;
use std::sync::Mutex;

pub struct AppState {
    pub engine: Mutex<Engine>,
    /// Cached Discord/webhook URL (from the vault) so the tick loop needn't hit
    /// the keychain every tick.
    pub webhook: Mutex<Option<String>>,
}

impl Default for AppState {
    fn default() -> Self {
        Self { engine: Mutex::new(Engine::new()), webhook: Mutex::new(None) }
    }
}
