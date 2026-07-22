//! Pythia engine core — the shared brain used by both the desktop app
//! (`src-tauri`) and the standalone backend server (`server`). Contains the
//! strategy engine, risk manager, connectors, real market data, the secrets
//! vault, webhook alerts and the (optional) Claude signal provider.
//!
//! Nothing here depends on Tauri or any UI, so it can run anywhere.

#![allow(dead_code)]

pub mod alerts;
pub mod connectors;
pub mod engine;
pub mod llm;
pub mod marketdata;
pub mod vault;
