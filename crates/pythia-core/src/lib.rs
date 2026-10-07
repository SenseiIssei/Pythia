//! Pythia engine core — the shared brain used by both the desktop app
//! (`src-tauri`) and the standalone backend server (`server`). Contains the
//! strategy engine, risk manager, connectors, real market data, the secrets
//! vault, webhook alerts and the (optional) Claude signal provider.
//!
//! Nothing here depends on Tauri or any UI, so it can run anywhere.

#![allow(dead_code)]

pub mod alerts;
pub mod connectors;
pub mod costs;
pub mod engine;
pub mod execution;
pub mod feeds;
pub mod forecast;
pub mod lab;
pub mod labview;
pub mod llm;
pub mod marketdata;
pub mod ml;
pub mod ml_picks;
pub mod orderbook;
pub mod persist;
pub mod predict;
pub mod prefs;
pub mod research;
pub mod tax;
pub mod validation;
pub mod vault;
pub mod wallets;
