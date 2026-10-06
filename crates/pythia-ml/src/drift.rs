//! Has the live input moved away from what the model was trained on?
//!
//! Two different questions, kept apart on purpose:
//!
//! * **Out of range**: the share of live values outside the 0.5 % .. 99.5 %
//!   band of the training data. Trees cannot extrapolate; past the edge of
//!   what they have seen they answer with the outermost leaf. This is the
//!   signal that the model may be wrong, and it decides the level.
//! * **Shift (PSI)**: how differently the live values spread over the training
//!   bins. A week of data always looks unlike six years of data for slow
//!   inputs, because a week is one market regime. Reported, not alarming.
//!
//! The bins come from the model card: decile edges with ties collapsed and
//! the share of training rows in each, so inputs that sit on one value half the
//! time (a return floored at zero) are compared fairly.

use serde::{Deserialize, Serialize};

pub const MIN_VALUES: usize = 48;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Bins {
    pub edges: Vec<f64>,
    pub expected: Vec<f64>,
    pub lo: f64,
    pub hi: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum DriftLevel {
    Stable,
    Shift,
    Drift,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DriftCheck {
    pub psi: f64,
    /// Percent of live values outside the training 0.5 % .. 99.5 % band.
    pub outside_pct: f64,
    pub level: DriftLevel,
}

/// `None` with fewer than `MIN_VALUES` finite values, too few to say anything.
pub fn check(bins: &Bins, values: &[f64]) -> Option<DriftCheck> {
    if bins.expected.len() != bins.edges.len() + 1 {
        return None;
    }
    let vals: Vec<f64> = values.iter().copied().filter(|v| v.is_finite()).collect();
    if vals.len() < MIN_VALUES {
        return None;
    }
    let n = vals.len() as f64;
    let mut counts = vec![0usize; bins.expected.len()];
    let mut outside = 0usize;
    for v in &vals {
        let bin = bins.edges.iter().position(|e| *v <= *e).unwrap_or(bins.edges.len());
        counts[bin] += 1;
        if *v < bins.lo || *v > bins.hi {
            outside += 1;
        }
    }
    let psi = counts
        .iter()
        .zip(&bins.expected)
        .map(|(&c, &e)| {
            let o = (c as f64 / n).max(1e-4);
            let e = e.max(1e-4);
            (o - e) * (o / e).ln()
        })
        .sum();
    // Expected outside the band by construction: 1 %. Five times that is a real excursion.
    let outside_pct = outside as f64 / n * 100.0;
    let level = if outside_pct > 5.0 {
        DriftLevel::Drift
    } else if outside_pct > 2.0 || psi > 0.25 {
        DriftLevel::Shift
    } else {
        DriftLevel::Stable
    };
    Some(DriftCheck { psi, outside_pct, level })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn uniform_bins() -> Bins {
        Bins { edges: (1..=9).map(|i| i as f64 / 10.0).collect(), expected: vec![0.1; 10], lo: 0.005, hi: 0.995 }
    }

    #[test]
    fn same_distribution_is_stable() {
        let vals: Vec<f64> = (0..1000).map(|i| (i as f64 + 0.5) / 1000.0).collect();
        let c = check(&uniform_bins(), &vals).unwrap();
        assert!(c.psi < 0.01, "{c:?}");
        assert_eq!(c.level, DriftLevel::Stable);
    }

    #[test]
    fn values_past_the_training_range_are_drift() {
        let vals: Vec<f64> = (0..1000).map(|i| 0.9 + i as f64 / 2000.0).collect();
        let c = check(&uniform_bins(), &vals).unwrap();
        assert!(c.outside_pct > 50.0);
        assert_eq!(c.level, DriftLevel::Drift);
    }

    #[test]
    fn a_regime_inside_the_range_is_a_shift_not_drift() {
        let vals: Vec<f64> = (0..1000).map(|i| 0.6 + i as f64 / 5000.0).collect();
        let c = check(&uniform_bins(), &vals).unwrap();
        assert_eq!(c.level, DriftLevel::Shift);
    }

    #[test]
    fn ties_are_compared_fairly() {
        // Half the training mass sits at exactly 0: deciles collapse to one edge.
        let bins = Bins { edges: vec![-0.5, 0.0], expected: vec![0.2, 0.6, 0.2], lo: -1.0, hi: 1.0 };
        let vals: Vec<f64> = (0..100).map(|i| if i < 20 { -0.7 } else if i < 80 { 0.0 } else { 0.3 }).collect();
        let c = check(&bins, &vals).unwrap();
        assert!(c.psi < 0.01, "{c:?}");
        assert_eq!(c.level, DriftLevel::Stable);
    }

    #[test]
    fn too_few_values_says_nothing() {
        assert!(check(&uniform_bins(), &[0.1, 0.2]).is_none());
    }
}
