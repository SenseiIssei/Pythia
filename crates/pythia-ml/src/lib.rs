//! Model inference for Pythia.
//!
//! The research lab (research/lab) trains and validates; this crate runs what
//! survived. It never fetches data and never trades: pythia-core feeds it bars
//! and decides what, if anything, to do with the answers. Every model starts in
//! shadow mode, scored live against its baseline, before it may move money.

pub mod card;
pub mod drift;
pub mod gbdt;
pub mod picks;
pub mod picks_shadow;
pub mod shadow;
pub mod vol;

pub use card::Card;
pub use gbdt::Gbdt;
pub use vol::{features, hourly_from_minutes, HourBar, MinuteBar, VolModel, FEATURES};

#[derive(Debug, thiserror::Error)]
pub enum MlError {
    #[error("cannot read model: {0}")]
    Io(String),
    #[error("model file is not usable: {0}")]
    Format(String),
    #[error("model does not match the engine: {0}")]
    Mismatch(String),
}

/// The newest version directory under `<models>/<name>/` that holds a card and a model.
pub fn latest_version(models_dir: &std::path::Path, name: &str) -> Option<std::path::PathBuf> {
    let mut dirs: Vec<_> = std::fs::read_dir(models_dir.join(name))
        .ok()?
        .filter_map(Result::ok)
        .map(|e| e.path())
        .filter(|p| p.join("card.json").is_file() && p.join("model.json").is_file())
        .collect();
    dirs.sort();
    dirs.pop()
}
