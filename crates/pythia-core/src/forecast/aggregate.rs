//! Combining probability forecasts.
//!
//! The naive thing — average the probabilities — is wrong, and wrong in a way
//! that matters. Averaging 0.02 and 0.20 gives 0.11; in log-odds it gives 0.06.
//! Probabilities live on a bounded scale where the *ratio* of odds is the
//! meaningful quantity, so all pooling here happens in log-odds space.
//!
//! ## Two knobs, pointing in opposite directions
//!
//! **Extremizing** (`sharpen > 1`) pushes the pooled forecast away from 0.5.
//! It is the right correction for *independent* forecasters: if five people who
//! looked at different evidence all say 0.7, the group knows more than any one
//! of them and 0.75 is better calibrated than 0.7.
//!
//! **Shrinking** (`trust < 1`) pulls the forecast back toward a prior. It is the
//! right correction when forecasters are *correlated* or *unproven*.
//!
//! Pythia's ensemble is mostly large language models trained on overlapping
//! data. They are nowhere near independent — five models agreeing is close to
//! one model saying it five times. So the default is `sharpen = 1.0` (no
//! extremizing) and heavy shrinkage toward the market price, with the shrinkage
//! lifted only as a source *earns* it by beating the market on a scored track
//! record. See [`super::calibration::trust`].

/// Probabilities are clamped this far from 0 and 1 before taking log-odds.
/// Without it a forecaster saying "certain" produces an infinite log-odds that
/// swallows every other opinion in the pool.
const EPS: f64 = 1e-6;

pub fn logit(p: f64) -> f64 {
    let p = p.clamp(EPS, 1.0 - EPS);
    (p / (1.0 - p)).ln()
}

pub fn logistic(x: f64) -> f64 {
    // Split by sign to avoid exp() overflowing on large |x|.
    if x >= 0.0 {
        1.0 / (1.0 + (-x).exp())
    } else {
        let e = x.exp();
        e / (1.0 + e)
    }
}

/// Weighted log-odds pool of `(probability, weight)` pairs, optionally sharpened.
///
/// Returns `None` when there is nothing to pool or every weight is zero — the
/// caller must then fall back to its prior rather than inventing a number.
pub fn pool(components: &[(f64, f64)], sharpen: f64) -> Option<f64> {
    let total: f64 = components.iter().map(|(_, w)| w.max(0.0)).sum();
    if components.is_empty() || total <= 0.0 {
        return None;
    }
    let mean: f64 = components
        .iter()
        .map(|(p, w)| w.max(0.0) * logit(*p))
        .sum::<f64>()
        / total;
    Some(logistic(mean * sharpen))
}

/// Move `p` toward `prior` in log-odds space. `trust` is how much of the way to
/// keep: 1.0 returns `p` untouched, 0.0 returns `prior`.
pub fn shrink_toward(p: f64, prior: f64, trust: f64) -> f64 {
    let t = trust.clamp(0.0, 1.0);
    logistic(t * logit(p) + (1.0 - t) * logit(prior))
}

/// Kish's effective sample size: how many *equally weighted* forecasters this
/// weighting is worth. One source at weight 10 and nine at weight 0.01 is an
/// ensemble of one, and this is the number that says so.
pub fn effective_n(weights: &[f64]) -> f64 {
    let sum: f64 = weights.iter().map(|w| w.max(0.0)).sum();
    let sum_sq: f64 = weights.iter().map(|w| w.max(0.0).powi(2)).sum();
    if sum_sq <= 0.0 {
        0.0
    } else {
        sum * sum / sum_sq
    }
}

/// Spread of opinion across the pool, in log-odds. High disagreement is a signal
/// in itself: it means the sources are seeing different things, which is when an
/// ensemble is worth the most — and also when any single one of them is least
/// trustworthy on its own.
pub fn disagreement(components: &[(f64, f64)]) -> f64 {
    if components.len() < 2 {
        return 0.0;
    }
    let logits: Vec<f64> = components.iter().map(|(p, _)| logit(*p)).collect();
    let mean = logits.iter().sum::<f64>() / logits.len() as f64;
    (logits.iter().map(|l| (l - mean).powi(2)).sum::<f64>() / logits.len() as f64).sqrt()
}

/// Fraction of bankroll for a binary bet at `p_model` against price `p_market`,
/// using fractional Kelly.
///
/// A YES contract bought at `p_market` pays 1, so the Kelly fraction is
/// `(p − price) / (1 − price)`. Negative means the bet is on the other side;
/// the caller decides whether it can take that side (spot cannot short).
pub fn kelly_binary(p_model: f64, p_market: f64, fraction: f64) -> f64 {
    let price = p_market.clamp(EPS, 1.0 - EPS);
    let p = p_model.clamp(0.0, 1.0);
    let full = (p - price) / (1.0 - price);
    (full * fraction).clamp(-1.0, 1.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(a: f64, b: f64) -> bool {
        (a - b).abs() < 1e-9
    }

    #[test]
    fn logit_and_logistic_round_trip() {
        for p in [0.01, 0.1, 0.5, 0.9, 0.99] {
            assert!(close(logistic(logit(p)), p), "{p}");
        }
        assert!(close(logit(0.5), 0.0));
    }

    #[test]
    fn certainty_cannot_produce_an_infinite_opinion() {
        // A source saying 1.0 must not swallow the pool.
        assert!(logit(1.0).is_finite());
        assert!(logit(0.0).is_finite());
        let p = pool(&[(1.0, 1.0), (0.5, 1.0)], 1.0).unwrap();
        assert!(p.is_finite() && p < 1.0 && p > 0.5, "{p}");
    }

    #[test]
    fn logistic_does_not_overflow_at_extremes() {
        assert!(close(logistic(1000.0), 1.0));
        assert!(close(logistic(-1000.0), 0.0));
        assert!(logistic(-1000.0) >= 0.0);
    }

    #[test]
    fn pooling_happens_in_log_odds_not_in_probability() {
        // The whole point: 0.02 and 0.20 average to 0.11 linearly, but ~0.063
        // in log-odds, which is the answer that respects the odds ratio.
        let p = pool(&[(0.02, 1.0), (0.20, 1.0)], 1.0).unwrap();
        assert!(p > 0.05 && p < 0.08, "got {p}");
        assert!(p < 0.11, "must not be the arithmetic mean");
    }

    #[test]
    fn weights_move_the_pool_toward_the_heavier_source() {
        let even = pool(&[(0.2, 1.0), (0.8, 1.0)], 1.0).unwrap();
        assert!(close(even, 0.5), "symmetric inputs pool to 0.5, got {even}");
        let skewed = pool(&[(0.2, 3.0), (0.8, 1.0)], 1.0).unwrap();
        assert!(skewed < 0.5);
    }

    #[test]
    fn a_zero_weight_source_is_ignored_entirely() {
        // This is how an unproven forecaster is silenced: weight 0, no influence.
        let p = pool(&[(0.9, 0.0), (0.3, 1.0)], 1.0).unwrap();
        assert!(close(p, 0.3));
    }

    #[test]
    fn nothing_to_pool_returns_none_rather_than_a_made_up_number() {
        assert!(pool(&[], 1.0).is_none());
        assert!(pool(&[(0.7, 0.0), (0.3, 0.0)], 1.0).is_none());
    }

    #[test]
    fn sharpening_pushes_away_from_a_half_and_never_flips_the_side() {
        let base = pool(&[(0.7, 1.0), (0.75, 1.0)], 1.0).unwrap();
        let sharp = pool(&[(0.7, 1.0), (0.75, 1.0)], 1.8).unwrap();
        assert!(sharp > base, "extremizing must move away from 0.5");
        assert!(sharp > 0.5, "and never cross it");
        // Symmetrically on the other side.
        let low = pool(&[(0.3, 1.0), (0.25, 1.0)], 1.8).unwrap();
        assert!(low < 0.5);
    }

    #[test]
    fn shrinking_with_no_trust_returns_the_prior_exactly() {
        assert!(close(shrink_toward(0.9, 0.4, 0.0), 0.4));
        assert!(close(shrink_toward(0.9, 0.4, 1.0), 0.9));
        // Halfway is halfway in log-odds, which is not the arithmetic midpoint.
        let half = shrink_toward(0.9, 0.4, 0.5);
        assert!(half > 0.4 && half < 0.9);
        assert!((half - 0.65).abs() > 1e-3, "log-odds midpoint, not linear");
    }

    #[test]
    fn effective_sample_size_exposes_a_pool_dominated_by_one_source() {
        assert!(close(effective_n(&[1.0, 1.0, 1.0, 1.0]), 4.0));
        let dominated = effective_n(&[10.0, 0.01, 0.01, 0.01]);
        assert!(dominated < 1.1, "an ensemble of one, got {dominated}");
        assert_eq!(effective_n(&[]), 0.0);
    }

    #[test]
    fn disagreement_is_zero_when_everyone_agrees() {
        assert!(close(disagreement(&[(0.7, 1.0), (0.7, 1.0)]), 0.0));
        assert!(disagreement(&[(0.1, 1.0), (0.9, 1.0)]) > 1.0);
        assert_eq!(disagreement(&[(0.7, 1.0)]), 0.0, "one source cannot disagree");
    }

    #[test]
    fn kelly_is_zero_at_fair_value_and_negative_when_the_market_is_rich() {
        assert!(close(kelly_binary(0.5, 0.5, 0.25), 0.0));
        assert!(kelly_binary(0.7, 0.5, 0.25) > 0.0);
        assert!(kelly_binary(0.3, 0.5, 0.25) < 0.0);
        // Fractional Kelly is exactly that fraction of full Kelly.
        let full = kelly_binary(0.7, 0.5, 1.0);
        let quarter = kelly_binary(0.7, 0.5, 0.25);
        assert!(close(quarter, full * 0.25));
        // And it stays bounded even against an absurd price.
        assert!(kelly_binary(1.0, 0.999_999, 1.0).abs() <= 1.0);
    }
}
