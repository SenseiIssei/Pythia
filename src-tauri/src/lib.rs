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

use pythia_core::{alerts, execution, marketdata};
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
            // Recalibrated costs, if the user has any: `PYTHIA_COSTS_FILE`, or
            // `costs.json` in the app's data directory. Otherwise the defaults
            // compiled in from `config/costs.json` stand.
            let costs_file = std::env::var("PYTHIA_COSTS_FILE")
                .ok()
                .map(std::path::PathBuf::from)
                .or_else(|| app.path().app_data_dir().ok().map(|d| d.join("costs.json")))
                .filter(|p| p.exists());
            if let Some(path) = costs_file {
                if let Err(e) = pythia_core::costs::load_file(&path) {
                    eprintln!("ignoring cost file: {e}");
                }
            }
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

                    // Clone the shared handles out and drop the Tauri state
                    // guard immediately: nothing below may hold it across an
                    // await.
                    let (engine, creds, webhook) = {
                        let Some(st) = handle.try_state::<AppState>() else { continue };
                        let engine = st.engine.clone();
                        let creds = commands::credentials(st.inner());
                        let webhook = st.webhook.lock().unwrap().clone();
                        (engine, creds, webhook)
                    };

                    // Market-data credentials for the selected endpoint, from
                    // the cached set (refreshed whenever keys are saved), so
                    // keys added in Settings take effect without a restart.
                    let paper = engine.lock().unwrap().live_config().paper;
                    let alpaca_keys = || commands::alpaca_data_keys(&creds, paper);

                    // Refresh real read-only feeds periodically (and on first tick).
                    if n % 8 == 1 {
                        let kraken = marketdata::fetch_kraken().await;
                        let poly = marketdata::fetch_polymarket().await;
                        // Real equity quotes when Alpaca keys are in the vault
                        // (otherwise those markets stay on the simulator).
                        let (id, secret) = alpaca_keys();
                        let feed = commands::get_prefs().alpaca_feed;
                        let alpaca = marketdata::fetch_alpaca(&id, &secret, &feed).await;
                        let mut e = engine.lock().unwrap();
                        e.apply_kraken(&kraken);
                        e.apply_polymarket(&poly);
                        e.apply_alpaca(&alpaca);
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
                            engine.lock().unwrap().apply_bars(&series);
                        }
                    }

                    // Session + account state. Live equity entries are blocked
                    // until this is fresh, so it must beat the engine's
                    // five-minute staleness window comfortably.
                    if n % 40 == 1 {
                        commands::refresh_broker_status(&handle).await;
                    }

                    let (dto, queued) = {
                        let mut e = engine.lock().unwrap();
                        e.tick();
                        (e.state(), e.drain_alerts())
                    };
                    let _ = handle.emit("engine://state", dto);

                    // Push any queued alerts to the webhook (batched, one POST).
                    if !queued.is_empty() {
                        if let Some(url) = webhook.filter(|u| !u.is_empty()) {
                            alerts::post(&url, &queued.join("\n")).await;
                        }
                    }

                    // Submit new live orders and poll the ones already out.
                    // Submission returns on the venue's acknowledgement and a
                    // poll is one request per order, so this never stalls the
                    // tick loop the way a blocking wait-for-fill would.
                    execution::cycle(&engine, &creds).await;

                    // Reconcile against the broker every ~2 minutes — the only
                    // way to notice a fill that landed while we were restarting.
                    if n % 80 == 1 {
                        execution::reconcile(&engine, &creds).await;
                    }
                    let _ = handle.emit("engine://state", engine.lock().unwrap().state());

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
            commands::set_adaptive_execution,
            commands::save_venue_keys,
            commands::clear_venue_keys,
            commands::venue_status,
            commands::test_alert,
            commands::llm_providers,
            commands::save_llm_key,
            commands::clear_llm_key,
            commands::llm_signal,
            commands::set_live,
            commands::live_verify,
            commands::set_ai_policy,
            commands::alpaca_account,
            commands::live_diagnostics,
            commands::send_test_order,
            commands::research_sweep,
            commands::exchanges,
            commands::save_exchange_keys,
            commands::clear_exchange_keys,
            commands::wallet_addresses,
            commands::save_wallet_addresses,
            commands::wallet_snapshot,
            commands::run_ensemble,
            commands::forecast_config,
            commands::set_forecast_config,
            commands::get_prefs,
            commands::save_prefs,
            commands::test_llm_key,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Pythia");
}
