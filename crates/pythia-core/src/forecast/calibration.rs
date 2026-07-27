//! Scoring forecasts, and deciding how much to believe them.
//!
//! This is the module that stops "AI predictions" from being a random number
//! generator with a confident tone. Every forecast Pythia makes is recorded with
//! the market price at the time, resolved later against what actually happened,
//! and scored. A source that cannot beat the market price on that record is
//! given **zero weight** and cannot move a single order.
//!
//! ## Why the market is the reference, not 0.5
//!
//! A Brier score of 0.18 sounds good until you learn the market scored 0.16 on
//! the same questions. The market price is a free, always-available forecast
//! that is hard to beat — it is the *only* honest baseline. So everything here
//! is measured as skill **relative to the market**:
//!
//! ```text
//! BSS = 1 − brier(model) / brier(market)
//! ```
//!
//! Positive means the source added information. Zero or negative means it did
//! not, and no amount of eloquent rationale changes that.
//!
//! ## Why sample size gates trust
//!
//! Ten lucky forecasts produce a wonderful BSS. Trust therefore ramps with the
//! number of *resolved* forecasts, so a source needs both skill and a track
//! record before it is allowed to disagree with the market by much.

use super::aggregate::{logistic, logit};
use serde::{Deserialize, Serialize};

/// Resolved forecasts needed before a source is trusted at half its measured
/// skill. At n = 50 a source with perfect skill is trusted 0.5; at n = 200, 0.8.
const TRUST_HALF_LIFE: f64 = 50.0;

/// One scored source.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct Score {
    /// Number of resolved forecasts.
    pub n: usize,
    /// Mean squared error against the 0/1 outcome. Lower is better; 0.25 is the
    /// score of always saying 0.5.
    pub brier: f64,
    /// Mean negative log-likelihood. Punishes confident mistakes far harder than
    /// Brier does, which is exactly what we want from an overconfident model.
    pub log_loss: f64,
    /// Mean forecast, and mean outcome. If these diverge the source has a bias:
    /// forecasting 0.7 on average for things that happen 0.4 of the time.
    pub mean_forecast: f64,
    pub mean_outcome: f64,
}

impl Score {
    /// Score a set of (forecast, outcome) pairs.
    pub fn of(samples: &[(f64, bool)]) -> Score {
        if samples.is_empty() {
            return Score::default();
        }
        let n = samples.len() as f64;
        let mut brier = 0.0;
        let mut ll = 0.0;
        let mut mf = 0.0;
        let mut mo = 0.0;
        for &(p, y) in samples {
            let p = p.clamp(1e-6, 1.0 - 1e-6);
            let y_f = if y { 1.0 } else { 0.0 };
            brier += (p - y_f).powi(2);
            ll -= if y { p.ln() } else { (1.0 - p).ln() };
            mf += p;
            mo += y_f;
        }
        Score {
            n: samples.len(),
            brier: brier / n,
            log_loss: ll / n,
            mean_forecast: mf / n,
            mean_outcome: mo / n,
        }
    }

    /// Systematic over- or under-forecasting, in probability points.
    pub fn bias(&self) -> f64 {
        self.mean_forecast - self.mean_outcome
    }
}

/// Brier Skill Score against a reference forecaster. Positive = added value.
pub fn brier_skill(model: &Score, reference: &Score) -> f64 {
    if reference.brier <= 0.0 || model.n == 0 || reference.n == 0 {
        return 0.0;
    }
    1.0 - model.brier / reference.brier
}

/// How far a source is allowed to pull the final forecast away from the market
/// price: measured skill, discounted by how little evidence there is for it.
///
/// Both factors must be present. Great skill over 5 forecasts is luck; 500
/// forecasts of no skill is a well-documented failure. Returns 0..1.
pub fn trust(model: &Score, market: &Score) -> f64 {
    let skill = brier_skill(model, market).clamp(0.0, 1.0);
    if skill <= 0.0 {
        return 0.0;
    }
    let n = model.n as f64;
    let evidence = n / (n + TRUST_HALF_LIFE);
    skill * evidence
}

/// One bucket of a reliability diagram: of the forecasts in `[lo, hi)`, what
/// fraction actually happened?
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReliabilityBin {
    pub lo: f64,
    pub hi: f64,
    pub n: usize,
    /// Mean forecast in the bin.
    pub mean_forecast: f64,
    /// Observed frequency in the bin. A calibrated source has these two equal.
    pub observed: f64,
}

/// Bucket forecasts into a reliability diagram. This is the picture that tells
/// you *how* a source is wrong: consistently overconfident, biased one way, or
/// simply noisy.
pub fn reliability(samples: &[(f64, bool)], bins: usize) -> Vec<ReliabilityBin> {
    let bins = bins.max(1);
    let width = 1.0 / bins as f64;
    let mut out: Vec<ReliabilityBin> = (0..bins)
        .map(|i| ReliabilityBin {
            lo: i as f64 * width,
            hi: (i + 1) as f64 * width,
            n: 0,
            mean_forecast: 0.0,
            observed: 0.0,
        })
        .collect();

    for &(p, y) in samples {
        let idx = ((p.clamp(0.0, 1.0) / width) as usize).min(bins - 1);
        let b = &mut out[idx];
        b.n += 1;
        b.mean_forecast += p;
        b.observed += if y { 1.0 } else { 0.0 };
    }
    for b in &mut out {
        if b.n > 0 {
            b.mean_forecast /= b.n as f64;
            b.observed /= b.n as f64;
        }
    }
    out
}

/// A learned recalibration map `p' = logistic(a · logit(p) + b)`.
///
/// `a < 1` tames an overconfident source (pulls its extremes toward 0.5); `b`
/// removes a directional bias. Fitting this is strictly better than telling a
/// model "please be calibrated" and hoping.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Recalibration {
    pub slope: f64,
    pub intercept: f64,
    /// Resolved forecasts the fit is based on.
    pub n: usize,
}

impl Default for Recalibration {
    /// Identity — the correct starting point when nothing has been observed.
    fn default() -> Self {
        Recalibration { slope: 1.0, intercept: 0.0, n: 0 }
    }
}

impl Recalibration {
    pub fn apply(&self, p: f64) -> f64 {
        logistic(self.slope * logit(p) + self.intercept)
    }

    pub fn is_identity(&self) -> bool {
        (self.slope - 1.0).abs() < 1e-9 && self.intercept.abs() < 1e-9
    }
}

/// Minimum resolved forecasts before a recalibration is fitted at all. Below
/// this the fit is noise and the identity map is the honest answer.
const MIN_FIT_SAMPLES: usize = 30;

/// Most recent samples the fit will look at.
///
/// Two reasons, and the second is the real one. The fit is O(iterations × n),
/// so an unbounded ledger makes it unboundedly slow. More importantly a
/// source's calibration *drifts* — a model that was overconfident a year ago may
/// not be now — so a fit dominated by ancient history is answering the wrong
/// question. Recency is both cheaper and more correct.
const MAX_FIT_SAMPLES: usize = 2_000;

/// Fit [`Recalibration`] by gradient descent on log-loss (logistic regression of
/// the outcome on the forecast's log-odds).
///
/// Converges reliably because the loss is convex in (slope, intercept); a fixed
/// step count keeps it cheap enough to re-run on every snapshot.
pub fn fit_recalibration(samples: &[(f64, bool)]) -> Recalibration {
    if samples.len() < MIN_FIT_SAMPLES {
        return Recalibration { n: samples.len(), ..Default::default() };
    }
    // Newest last, so the tail is the recent window.
    let window = &samples[samples.len().saturating_sub(MAX_FIT_SAMPLES)..];
    let xs: Vec<f64> = window.iter().map(|(p, _)| logit(*p)).collect();
    let ys: Vec<f64> = window.iter().map(|(_, y)| if *y { 1.0 } else { 0.0 }).collect();
    let n = xs.len() as f64;

    let (mut a, mut b) = (1.0f64, 0.0f64);
    let lr = 0.05;
    for _ in 0..800 {
        let (mut ga, mut gb) = (0.0, 0.0);
        for i in 0..xs.len() {
            let err = logistic(a * xs[i] + b) - ys[i];
            ga += err * xs[i];
            gb += err;
        }
        a -= lr * ga / n;
        b -= lr * gb / n;
    }
    Recalibration {
        // A negative slope would mean the source is anti-predictive; inverting
        // it is a curve-fit on noise, so clamp to "says nothing" instead.
        slope: a.clamp(0.0, 3.0),
        intercept: b.clamp(-3.0, 3.0),
        n: samples.len(),
    }
}

/// Everything known about one forecasting source.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Track {
    pub source: String,
    /// Which question type this record is for. A source is scored separately on
    /// each, because being right about an hourly tick is not being right about
    /// an election.
    pub kind: String,
    pub score: Score,
    /// The market's score on the *same* questions — the only fair comparison.
    pub market_score: Score,
    pub brier_skill: f64,
    pub trust: f64,
    pub recalibration: Recalibration,
    pub reliability: Vec<ReliabilityBin>,
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Always saying 0.5 scores exactly 0.25 — the number every source is
    /// implicitly competing against.
    #[test]
    fn the_uninformative_forecast_scores_a_quarter() {
        let s = Score::of(&[(0.5, true), (0.5, false), (0.5, true), (0.5, false)]);
        assert!((s.brier - 0.25).abs() < 1e-12);
        assert!((s.log_loss - 2f64.ln()).abs() < 1e-9);
    }

    #[test]
    fn a_perfect_forecaster_scores_zero() {
        let s = Score::of(&[(1.0, true), (0.0, false), (1.0, true)]);
        assert!(s.brier < 1e-9);
        assert_eq!(s.n, 3);
    }

    #[test]
    fn log_loss_punishes_confident_mistakes_far_harder_than_brier() {
        let confident_wrong = Score::of(&[(0.99, false)]);
        let unsure_wrong = Score::of(&[(0.60, false)]);
        // Brier: ~0.98 vs 0.36 — a factor of 2.7.
        let brier_ratio = confident_wrong.brier / unsure_wrong.brier;
        // Log loss: ~4.6 vs 0.92 — a factor of 5.
        let ll_ratio = confident_wrong.log_loss / unsure_wrong.log_loss;
        assert!(ll_ratio > brier_ratio, "{ll_ratio} should exceed {brier_ratio}");
    }

    #[test]
    fn bias_catches_a_source_that_systematically_over_forecasts() {
        // Says 0.8 every time; it happens a third of the time.
        let s = Score::of(&[(0.8, true), (0.8, false), (0.8, false)]);
        assert!(s.bias() > 0.4, "got {}", s.bias());
    }

    #[test]
    fn skill_is_measured_against_the_market_not_against_nothing() {
        let model = Score { n: 100, brier: 0.18, ..Default::default() };
        let market = Score { n: 100, brier: 0.20, ..Default::default() };
        assert!((brier_skill(&model, &market) - 0.1).abs() < 1e-9);
        // Worse than the market is negative skill, not "pretty good".
        let worse = Score { n: 100, brier: 0.24, ..Default::default() };
        assert!(brier_skill(&worse, &market) < 0.0);
    }

    #[test]
    fn a_source_that_cannot_beat_the_market_gets_exactly_zero_trust() {
        let market = Score { n: 500, brier: 0.20, ..Default::default() };
        let no_skill = Score { n: 500, brier: 0.20, ..Default::default() };
        assert_eq!(trust(&no_skill, &market), 0.0);
        let worse = Score { n: 500, brier: 0.30, ..Default::default() };
        assert_eq!(trust(&worse, &market), 0.0, "negative skill must not go negative into the pool");
    }

    #[test]
    fn trust_requires_a_track_record_not_just_a_good_run() {
        let market = Score { n: 5, brier: 0.25, ..Default::default() };
        let lucky = Score { n: 5, brier: 0.05, ..Default::default() };
        let proven = Score { n: 500, brier: 0.05, ..Default::default() };
        let market_long = Score { n: 500, brier: 0.25, ..Default::default() };

        let t_lucky = trust(&lucky, &market);
        let t_proven = trust(&proven, &market_long);
        assert!(t_lucky < 0.15, "five good calls is luck, got {t_lucky}");
        assert!(t_proven > 0.6, "500 good calls is evidence, got {t_proven}");
        assert!(t_proven > t_lucky * 4.0);
    }

    #[test]
    fn trust_never_leaves_the_unit_interval() {
        let market = Score { n: 1000, brier: 0.25, ..Default::default() };
        let perfect = Score { n: 100_000, brier: 0.0, ..Default::default() };
        let t = trust(&perfect, &market);
        assert!((0.0..=1.0).contains(&t), "got {t}");
    }

    #[test]
    fn an_empty_record_produces_no_trust_and_no_panic() {
        assert_eq!(trust(&Score::default(), &Score::default()), 0.0);
        assert_eq!(brier_skill(&Score::default(), &Score::default()), 0.0);
        assert_eq!(Score::of(&[]).n, 0);
    }

    #[test]
    fn reliability_bins_show_where_a_source_is_wrong() {
        // Everything forecast at 0.9 happens only half the time.
        let samples: Vec<(f64, bool)> = (0..10).map(|i| (0.9, i % 2 == 0)).collect();
        let bins = reliability(&samples, 10);
        let top = bins.last().unwrap();
        assert_eq!(top.n, 10);
        assert!((top.mean_forecast - 0.9).abs() < 1e-9);
        assert!((top.observed - 0.5).abs() < 1e-9, "the gap is the miscalibration");
        // Empty bins report zero counts rather than being omitted.
        assert!(bins.iter().filter(|b| b.n == 0).count() == 9);
    }

    #[test]
    fn a_forecast_of_exactly_one_lands_in_the_top_bin_not_out_of_bounds() {
        let bins = reliability(&[(1.0, true)], 10);
        assert_eq!(bins[9].n, 1);
    }

    #[test]
    fn recalibration_is_the_identity_until_there_is_enough_evidence() {
        let few: Vec<(f64, bool)> = (0..10).map(|i| (0.9, i % 2 == 0)).collect();
        let r = fit_recalibration(&few);
        assert!(r.is_identity(), "10 samples is not a calibration curve");
        assert!((r.apply(0.9) - 0.9).abs() < 1e-9);
    }

    #[test]
    fn recalibration_tames_an_overconfident_source() {
        // A source that says 0.95 / 0.05 for things that happen 70% / 30% of the
        // time. The fitted slope should pull its extremes back toward 0.5.
        let mut samples = Vec::new();
        for i in 0..100 {
            samples.push((0.95, i % 10 < 7));
            samples.push((0.05, i % 10 < 3));
        }
        let r = fit_recalibration(&samples);
        assert!(r.slope < 1.0, "overconfidence should shrink the slope, got {}", r.slope);
        let corrected = r.apply(0.95);
        assert!(corrected < 0.95 && corrected > 0.5, "0.95 → {corrected}");
        // And it stays a valid probability.
        assert!((0.0..=1.0).contains(&r.apply(0.999)));
    }

    #[test]
    fn recalibration_refuses_to_invert_an_anti_predictive_source() {
        // Forecasts are exactly backwards. Inverting them would be a curve-fit
        // on noise; the honest correction is "this source says nothing".
        let mut samples = Vec::new();
        for i in 0..60 {
            samples.push((0.9, false));
            samples.push((0.1, true));
            let _ = i;
        }
        let r = fit_recalibration(&samples);
        assert!(r.slope >= 0.0, "slope must not go negative, got {}", r.slope);
    }
}
