//! The model zoo's status, as the research lab writes it.
//!
//! `python -m lab.models.train` writes `reports/models/latest.json` every
//! day: each model with its spec, its score against its baseline (walk-forward
//! per quarter, each retrain decision, live shadow per week), its last retrain,
//! drift and who uses it. This module only reads that file: it parses
//! tolerantly (a field the lab adds later is ignored, one it drops is a
//! default) and serves it in camelCase for the Models page.

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct ZooStatus {
    pub generated_ms: i64,
    pub generated: String,
    /// The lab feed header's one sentence (docs/LAB-FEEDS.md).
    pub headline: String,
    pub models: Vec<ZooModel>,
    /// What this run posted: promotions and models that drifted.
    pub alerts: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct ZooModel {
    pub code: String,
    pub name: String,
    pub title: String,
    pub target: String,
    pub horizon: String,
    pub universe: String,
    pub metric: String,
    pub higher_better: bool,
    pub baseline: String,
    /// zoo (retrained by lab.models.train), learn (by the nightly loop) or retired.
    pub managed_by: String,
    /// Where it is scored live: lab, engine or none.
    pub shadow_where: String,
    /// in use · shadow · failed its gate · waiting for data · never trained · retired · not on this machine
    pub status: String,
    pub status_detail: String,
    pub every_days: u32,
    pub used_by: Vec<String>,
    pub use_rule: String,
    pub notes: String,
    pub results: String,
    pub last_retrain_ms: Option<i64>,
    /// ok or failed: how the last retrain attempt went.
    pub last_status: Option<String>,
    pub next_due: Option<String>,
    pub champion: Option<Champion>,
    pub gate: Option<Gate>,
    pub model_score: Option<f64>,
    pub baseline_score: Option<f64>,
    /// Percent better than the baseline (lower loss), out of sample.
    pub gain_pct: Option<f64>,
    pub dm_p: Option<f64>,
    pub folds_won: Option<u32>,
    pub folds_total: Option<u32>,
    /// Model against baseline over time: walk-forward quarters for zoo
    /// models, retrain decisions for the learning loop's models.
    pub history: Vec<ScorePoint>,
    pub decisions: Vec<Decision>,
    pub live: Option<Live>,
    pub drift: Option<Drift>,
    /// Secondary numbers per model (calibration, quantiles, today's regime), as written.
    pub extra: Value,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct Champion {
    pub version: String,
    pub promoted_ms: Option<i64>,
    pub train_to: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Gate {
    pub passed: bool,
    pub why: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct ScorePoint {
    pub label: Option<String>,
    pub from: Option<String>,
    pub model: Option<f64>,
    pub baseline: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct Decision {
    pub date: Option<String>,
    pub candidate: Option<String>,
    pub decision: String,
    pub challenger_score: Option<f64>,
    pub champion_score: Option<f64>,
    pub why: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct Live {
    /// Forecasts written down before the outcome and scored since.
    pub rows: u32,
    /// Forecasts still waiting for their outcome.
    pub open: u32,
    pub model: Option<f64>,
    pub baseline: Option<f64>,
    pub gain_pct: Option<f64>,
    pub win_rate: Option<f64>,
    pub since: Option<String>,
    pub weeks: Vec<LiveWeek>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct LiveWeek {
    pub from: Option<String>,
    pub model: Option<f64>,
    pub baseline: Option<f64>,
    pub rows: u32,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Drift {
    /// stable · shift · drift · unknown
    pub level: String,
    pub why: String,
    pub features: Vec<DriftFeature>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct DriftFeature {
    pub feature: String,
    pub psi: f64,
    pub outside_pct: f64,
    pub level: String,
}

/// `None` when the text is not the zoo's report. Models without a code are dropped.
pub fn parse(text: &str) -> Option<ZooStatus> {
    let v: Value = serde_json::from_str(text).ok()?;
    if !v.get("models").is_some_and(Value::is_array) {
        return None;
    }
    let mut s: ZooStatus = serde_json::from_value(v.clone()).unwrap_or_else(|_| ZooStatus {
        generated_ms: v.get("generated_ms").and_then(Value::as_i64).unwrap_or(0),
        generated: v.get("generated").and_then(Value::as_str).unwrap_or_default().to_string(),
        headline: v.get("headline").and_then(Value::as_str).unwrap_or_default().to_string(),
        // One malformed model must not hide the others.
        models: v["models"]
            .as_array()
            .map(|a| a.iter().filter_map(|m| serde_json::from_value(m.clone()).ok()).collect())
            .unwrap_or_default(),
        alerts: vec![],
    });
    s.models.retain(|m| !m.code.is_empty());
    Some(s)
}

impl ZooModel {
    /// Something the owner should look at: inputs outside the trained range,
    /// a failed retrain or a shadow score that went wrong.
    pub fn needs_attention(&self) -> bool {
        self.drift.as_ref().is_some_and(|d| d.level == "drift")
            || self.status == "error"
            || self.last_status.as_deref() == Some("failed")
            || self.live.as_ref().is_some_and(|l| l.error.is_some())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = r#"{
      "generated_ms": 1760770800000, "generated": "2026-10-18 07:00 UTC", "alerts": ["M11 promoted"],
      "title": "Models", "status": "ok", "headline": "1 of 1 zoo models beat their baseline out of sample (M11).",
      "items": [{"label": "M11 Slippage", "value": "+69.4 %"}],
      "models": [
        {"code": "M11", "name": "m11_slippage", "title": "Slippage", "status": "shadow", "metric": "mae",
         "managed_by": "zoo", "every_days": 7, "used_by": [], "gain_pct": 69.4, "dm_p": 1e-70,
         "gate": {"passed": true, "why": "lower"}, "champion": {"version": "20261018T0700", "promoted_ms": 1, "train_to": "2026-10-01"},
         "history": [{"label": "block1", "from": "2026-06-01", "model": 0.7, "baseline": 2.2, "rows": 60}],
         "live": {"rows": 3, "open": 1, "model": 0.5, "baseline": 2.0, "gain_pct": 75.0, "weeks": [{"from": "2026-10-12", "model": 0.5, "baseline": 2.0, "rows": 3}]},
         "drift": {"level": "drift", "why": "1 of 7 inputs", "features": [{"feature": "log_notional", "psi": 2.1, "outside_pct": 40.0, "level": "drift"}]},
         "extra": {"fills": 400}, "a_field_from_the_future": 1},
        {"code": "M7", "status": "retired", "drift": null, "live": null, "champion": null},
        {"title": "no code: dropped"}
      ]}"#;

    #[test]
    fn parses_the_report_and_serves_camel_case() {
        let s = parse(SAMPLE).unwrap();
        assert_eq!(s.models.len(), 2);
        let m = &s.models[0];
        assert_eq!(m.champion.as_ref().unwrap().version, "20261018T0700");
        assert_eq!(m.live.as_ref().unwrap().weeks.len(), 1);
        assert!(m.gate.as_ref().unwrap().passed);
        assert!(m.needs_attention());
        assert!(!s.models[1].needs_attention());
        let out = serde_json::to_value(&s).unwrap();
        assert_eq!(out["models"][0]["gainPct"], 69.4);
        assert_eq!(out["models"][0]["drift"]["features"][0]["outsidePct"], 40.0);
        assert_eq!(out["models"][0]["usedBy"], serde_json::json!([]));
        assert_eq!(out["generatedMs"], 1760770800000i64);
        assert_eq!(out["headline"], "1 of 1 zoo models beat their baseline out of sample (M11).");
    }

    #[test]
    fn one_broken_model_does_not_hide_the_others() {
        let text = r#"{"generated_ms": 1, "models": [{"code": "M8", "history": "not a list"}, {"code": "M12"}]}"#;
        let s = parse(text).unwrap();
        assert_eq!(s.models.len(), 1);
        assert_eq!(s.models[0].code, "M12");
    }

    #[test]
    fn something_else_is_none() {
        assert!(parse("{}").is_none());
        assert!(parse("not json").is_none());
    }
}
