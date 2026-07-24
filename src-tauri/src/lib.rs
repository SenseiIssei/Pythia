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

                    // Market-data credentials for the selected endpoint, re-read
                    // each pass so keys added in Settings take effect without a
                    // restart.
                    let alpaca_keys = || commands::alpaca_data_keys(&handle);

                    // Refresh real read-only feeds periodically (and on first tick).
                    // Awaits happen here, with no engine lock held.
                    if n % 8 == 1 {
                        let kraken = marketdata::fetch_kraken().await;
                        let poly = marketdata::fetch_polymarket().await;
                        // Real equity quotes when Alpaca keys are in the vault
                        // (otherwise those markets stay on the simulator).
                        let (id, secret) = alpaca_keys();
                        let feed = commands::get_prefs().alpaca_feed;
                        let alpaca = marketdata::fetch_alpaca(&id, &secret, &feed).await;
                        if let Some(st) = handle.try_state::<AppState>() {
                            let mut e = st.engine.lock().unwrap();
                            e.apply_kraken(&kraken);
                            e.apply_polymarket(&poly);
                            e.apply_alpaca(&alpaca);
                        }
                    }

                    // Candle history — the series indicators actually run on.
                    // Without this every EMA and RSI is measuring the tick
                    // loop's own random walk rather than the market.
                    if n % 40 == 1 {
                        let (id, secret) = alpaca_keys();
                        let p = commands::get_prefs();
                        let mut series =
                            marketdata::fetch_kraken_bars(p.kraken_interval()).await;
                        series.extend(
                            marketdata::fetch_alpaca_bars(
                                &id,
                                &secret,
                                &p.alpaca_feed,
                                &p.bar_timeframe,
                                10,
                            )
                            .await,
                        );
                        if !series.is_empty() {
                            if let Some(st) = handle.try_state::<AppState>() {
                                st.engine.lock().unwrap().apply_bars(&series);
                            }
                        }
                    }

                    // Session + account state. Live equity entries are blocked
                    // until this is fresh, so it must beat the engine's
                    // five-minute staleness window comfortably.
                    if n % 40 == 1 {
                        commands::refresh_broker_status(&handle).await;
                    }

                    // Make the ledger match the broker's position book.
                    if n % 200 == 1 {
                        commands::reconcile_alpaca(&handle).await;
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

                    // Submit any armed live orders (Alpaca). Keys from the vault.
                    let live_orders = {
                        let st = handle.state::<AppState>();
                        let mut e = st.engine.lock().unwrap();
                        e.drain_live_orders()
                    };
                    // Off the tick loop: resolving one order can take ten
                    // seconds of polling, and freezing price updates and stop
                    // checks behind it is exactly the wrong trade-off.
                    for o in live_orders {
                        let h = handle.clone();
                        tauri::async_runtime::spawn(async move {
                            commands::submit_live_order(&h, o).await;
                        });
                    }

                    // Checkpoint to disk periodically (~every 60s).
                    if n % 40 == 0 {
                        persist::save(&handle);
                    }
                }
            });

            // The AI overlay, on its own clock so a slow model call can never
            // delay a tick, a stop check, or an order. Idle and free until the
            // overlay is switched on from the AI Signals page.
            let ai_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let mut cursor: usize = 0;
                loop {
                    // Re-read each pass so a changed interval takes effect
                    // without a restart.
                    let secs = commands::get_prefs().ai_interval_sec;
                    tokio::time::sleep(Duration::from_secs(secs)).await;
                    if commands::ai_overlay_pass(&ai_handle, cursor).await {
                        cursor = cursor.wrapping_add(1);
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
            commands::set_live,
            commands::set_ai_policy,
            commands::alpaca_account,
            commands::get_prefs,
            commands::save_prefs,
            commands::test_llm_key,
            commands::live_diagnostics,
            commands::send_test_order,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Pythia");
}
