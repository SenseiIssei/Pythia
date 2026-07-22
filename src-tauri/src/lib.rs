//! Pythia native shell (Tauri v2). Hosts the persistent engine daemon: a Tokio
//! task ticks the engine ~every 1.5s, periodically refreshes real read-only
//! market data (Kraken + Polymarket), and pushes a full `EngineState` to the UI
//! over the `engine://state` event. Mutations arrive as commands (see commands.rs).
//!
//! The `connectors` module is the Phase-2 live-execution scaffold; it compiles
//! but is not yet driven, hence the crate-level dead_code allowance.
#![allow(dead_code)]

mod commands;
mod persist;
mod state;
mod tray;

use pythia_core::{alerts, marketdata};
use state::AppState;
use std::time::Duration;
use tauri::{Emitter, Manager};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState::default())
        .on_window_event(|window, event| {
            // Closing the window hides it to the tray so the engine keeps
            // running; the tray's Quit item is the real exit.
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                persist::save(window.app_handle());
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .setup(|app| {
            tray::build_tray(&app.handle().clone())?;
            // Resume any previously saved daemon state.
            persist::load(app.handle());
            // Reflect which venues already have keys in the vault.
            commands::refresh_connected(app.state::<AppState>().inner());
            commands::refresh_webhook(app.state::<AppState>().inner());
            let handle = app.handle().clone();
            // The engine daemon. Runs for the app's lifetime, independent of
            // whether any window is focused.
            tauri::async_runtime::spawn(async move {
                let mut interval = tokio::time::interval(Duration::from_millis(1500));
                let mut n: u64 = 0;
                loop {
                    interval.tick().await;
                    n += 1;

                    // Refresh real read-only feeds periodically (and on first tick).
                    // Awaits happen here, with no engine lock held.
                    if n % 8 == 1 {
                        let kraken = marketdata::fetch_kraken().await;
                        let poly = marketdata::fetch_polymarket().await;
                        if let Some(st) = handle.try_state::<AppState>() {
                            let mut e = st.engine.lock().unwrap();
                            e.apply_kraken(&kraken);
                            e.apply_polymarket(&poly);
                        }
                    }

                    let (dto, queued) = {
                        let st = handle.state::<AppState>();
                        let mut e = st.engine.lock().unwrap();
                        e.tick();
                        (e.state(), e.drain_alerts())
                    };
                    let _ = handle.emit("engine://state", dto);

                    // Push any queued alerts to the webhook (batched, one POST).
                    if !queued.is_empty() {
                        let url = handle.state::<AppState>().webhook.lock().unwrap().clone();
                        if let Some(url) = url {
                            if !url.is_empty() {
                                alerts::post(&url, &queued.join("\n")).await;
                            }
                        }
                    }

                    // Checkpoint to disk periodically (~every 60s).
                    if n % 40 == 0 {
                        persist::save(&handle);
                    }
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_state,
            commands::toggle_kill,
            commands::set_limits,
            commands::set_strategy_state,
            commands::set_strategy_param,
            commands::add_strategy,
            commands::manual_order,
            commands::flatten,
            commands::save_venue_keys,
            commands::clear_venue_keys,
            commands::venue_status,
            commands::test_alert,
            commands::llm_providers,
            commands::save_llm_key,
            commands::clear_llm_key,
            commands::llm_signal,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Pythia");
}
