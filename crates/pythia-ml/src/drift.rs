//! Has the live input drifted away from what the model was trained on?
//!
//! Population stability index of recent live values against the training
//! deciles from the model card. Ten bins of 10 % each by construction, so the
//! expected share per bin is 0.1. Usual reading: under 0.1 stable, 0.1 to 0.25
//! a shift worth watching, above 0.25 the model is answering a different question.

use serde::Serialize;

pub const MIN_VALUES: usize = 48;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum DriftLevel {
    Stable,
    Shift,
    Drift,
}

pub fn level(psi: f64) -> DriftLevel {
    if psi < 0.1 {
        DriftLevel::Stable
    } else if psi < 0.25 {
        DriftLevel::Shift
    } else {
        DriftLevel::Drift
    }
}

/// PSI of `values` (NaN ignored) against nine training deciles. `None` with
/// fewer than `MIN_VALUES` finite values, too few to say anything.
pub fn psi(deciles: &[f64], values: &[f64]) -> Option<f64> {
    if deciles.len() != 9 {
        return None;
    }
    let vals: Vec<f64> = values.iter().copied().filter(|v| v.is_finite()).collect();
    if vals.len() < MIN_VALUES {
        return None;
    }
    let mut counts = [0usize; 10];
    for v in &vals {
        let bin = deciles.iter().position(|d| *v <= *d).unwrap_or(9);
        counts[bin] += 1;
    }
    let n = vals.len() as f64;
    Some(
        counts
            .iter()
            .map(|&c| {
                let o = (c as f64 / n).max(1e-4);
                (o - 0.1) * (o / 0.1).ln()
            })
            .sum(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn same_distribution_is_stable() {
        let deciles: Vec<f64> = (1..=9).map(|i| i as f64 / 10.0).collect();
        let vals: Vec<f64> = (0..1000).map(|i| (i as f64 + 0.5) / 1000.0).collect();
        let p = psi(&deciles, &vals).unwrap();
        assert!(p < 0.01, "{p}");
        assert_eq!(level(p), DriftLevel::Stable);
    }

    #[test]
    fn shifted_distribution_is_drift() {
        let deciles: Vec<f64> = (1..=9).map(|i| i as f64 / 10.0).collect();
        let vals: Vec<f64> = (0..1000).map(|i| 0.8 + (i as f64) / 5000.0).collect();
        assert_eq!(level(psi(&deciles, &vals).unwrap()), DriftLevel::Drift);
    }

    #[test]
    fn too_few_values_says_nothing() {
        let deciles: Vec<f64> = (1..=9).map(|i| i as f64).collect();
        assert!(psi(&deciles, &[1.0, 2.0]).is_none());
    }
}
