//! The real money readiness check's one setting: the risk step.
//!
//! The lab's daily check (`research/lab/lab/ops/readiness.py`, the rule in
//! `docs/LIVE-READINESS.md`) judges every autopilot on the Alpaca paper
//! account against a pre-registered rule. One slider on the Autopilot page,
//! careful (1) to bold (5), picks how strict it is: the drawdown limit, the
//! ETF hurdle, the positive weeks and the minimum days move together. The
//! mapping from step to numbers lives in the lab and comes back with every
//! report (`profiles`); this module only keeps the step.
//!
//! Saved as `<data>/reports/readiness/settings.json` (`risk_step`), the file
//! the lab reads. It changes what the check reports and nothing else: the
//! check never arms live, changes an autopilot or places an order.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::labview::data_dir;

pub const MIN_STEP: u8 = 1;
pub const MAX_STEP: u8 = 5;
/// The middle step, used until the owner moves the slider.
pub const DEFAULT_STEP: u8 = 3;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReadinessSettings {
    pub risk_step: u8,
    /// When it was last changed (epoch ms); 0 when never.
    pub updated_ms: i64,
}

impl Default for ReadinessSettings {
    fn default() -> Self {
        ReadinessSettings { risk_step: DEFAULT_STEP, updated_ms: 0 }
    }
}

/// The file as the lab writes and reads it (snake_case).
#[derive(Debug, Deserialize, Serialize)]
struct File {
    #[serde(alias = "riskStep")]
    risk_step: i64,
    #[serde(default, alias = "updatedMs")]
    updated_ms: i64,
}

fn path_in(root: &Path) -> PathBuf {
    root.join("reports").join("readiness").join("settings.json")
}

/// The saved step under `root`, or the default when there is none or it is
/// out of range.
pub fn read_in(root: &Path) -> ReadinessSettings {
    let Ok(text) = std::fs::read_to_string(path_in(root)) else { return ReadinessSettings::default() };
    match serde_json::from_str::<File>(&text) {
        Ok(f) if (MIN_STEP as i64..=MAX_STEP as i64).contains(&f.risk_step) => {
            ReadinessSettings { risk_step: f.risk_step as u8, updated_ms: f.updated_ms }
        }
        _ => ReadinessSettings::default(),
    }
}

/// Save a new step under `root` in one step (temp file, then rename).
pub fn write_in(root: &Path, step: u8, now_ms: i64) -> Result<ReadinessSettings, String> {
    if !(MIN_STEP..=MAX_STEP).contains(&step) {
        return Err(format!("The risk step must be between {MIN_STEP} and {MAX_STEP}, not {step}."));
    }
    let p = path_in(root);
    let dir = p.parent().expect("settings path has a folder");
    let body = serde_json::to_vec_pretty(&File { risk_step: step as i64, updated_ms: now_ms }).map_err(|e| e.to_string())?;
    let write = || -> std::io::Result<()> {
        std::fs::create_dir_all(dir)?;
        let tmp = dir.join("settings.json.tmp");
        std::fs::write(&tmp, &body)?;
        std::fs::rename(&tmp, &p)
    };
    write().map_err(|e| format!("The readiness setting could not be saved: {e}"))?;
    Ok(ReadinessSettings { risk_step: step, updated_ms: now_ms })
}

/// The step in the lab's data folder (`PYTHIA_DATA`).
pub fn settings() -> ReadinessSettings {
    data_dir().map(|d| read_in(&d)).unwrap_or_default()
}

/// Save the step in the lab's data folder.
pub fn set_settings(step: u8) -> Result<ReadinessSettings, String> {
    let root = data_dir().ok_or_else(|| "No lab data folder is set (PYTHIA_DATA).".to_string())?;
    write_in(&root, step, chrono::Utc::now().timestamp_millis())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("pythia-readiness-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        d
    }

    #[test]
    fn the_middle_step_until_one_is_saved() {
        let d = temp("default");
        assert_eq!(read_in(&d), ReadinessSettings::default());
        assert_eq!(read_in(&d).risk_step, 3);
    }

    #[test]
    fn a_saved_step_is_read_back_in_the_lab_spelling() {
        let d = temp("roundtrip");
        let s = write_in(&d, 5, 1_792_000_000_000).unwrap();
        assert_eq!(s.risk_step, 5);
        let text = std::fs::read_to_string(path_in(&d)).unwrap();
        assert!(text.contains("\"risk_step\": 5"), "{text}");
        assert_eq!(read_in(&d), ReadinessSettings { risk_step: 5, updated_ms: 1_792_000_000_000 });
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn a_step_out_of_range_is_refused_and_a_broken_file_reads_as_the_default() {
        let d = temp("range");
        assert!(write_in(&d, 0, 1).is_err());
        assert!(write_in(&d, 6, 1).is_err());
        std::fs::create_dir_all(path_in(&d).parent().unwrap()).unwrap();
        std::fs::write(path_in(&d), "{\"risk_step\": 9}").unwrap();
        assert_eq!(read_in(&d).risk_step, DEFAULT_STEP);
        std::fs::write(path_in(&d), "{\"riskStep\": 2}").unwrap();
        assert_eq!(read_in(&d).risk_step, 2);
        std::fs::write(path_in(&d), "not json").unwrap();
        assert_eq!(read_in(&d).risk_step, DEFAULT_STEP);
        let _ = std::fs::remove_dir_all(&d);
    }
}
