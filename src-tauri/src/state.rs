//! App-wide shared state. The engine lives behind a Mutex; the tick task and
//! the command handlers both lock it briefly (never across an await).

use crate::engine::Engine;
use std::sync::Mutex;

pub struct AppState {
    pub engine: Mutex<Engine>,
}

impl Default for AppState {
    fn default() -> Self {
        Self { engine: Mutex::new(Engine::new()) }
    }
}
