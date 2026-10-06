//! The model card the lab writes next to every model (`card.json`).

use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Card {
    pub name: String,
    pub created: String,
    pub target: String,
    /// Variance of the training residuals in log space, for the log-normal bias correction.
    pub residual_var: f64,
    pub features: Vec<String>,
    pub train_from_us: i64,
    pub train_to_us: i64,
    /// Out-of-sample summary per model ("naive", "har", "lgbm") as the lab reported it.
    #[serde(default)]
    pub out_of_sample: Value,
    #[serde(default)]
    pub qlike_gain_vs_har: f64,
    #[serde(default)]
    pub dm_p_vs_har: f64,
    pub har: Har,
    /// Deciles (10 % .. 90 %) of every feature in the training data, for drift checks.
    #[serde(default)]
    pub feature_deciles: HashMap<String, Vec<f64>>,
    pub probe: Probe,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Har {
    pub features: Vec<String>,
    pub intercept: f64,
    pub coef: Vec<f64>,
    pub residual_var: f64,
}

/// Rows with the exact outputs LightGBM produced; the engine must reproduce them.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Probe {
    pub x: Vec<Vec<Option<f64>>>,
    pub raw: Vec<f64>,
}
