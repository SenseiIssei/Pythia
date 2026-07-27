//! Statistical forecasters — the ones that need no API key and no model.
//!
//! Each is a small, explicit hypothesis about how a market misprices things.
//! None is assumed correct: they all go into the same scored pool as the LLMs
//! (see [`super::calibration`]) and a hypothesis that does not beat the market
//! on its own track record ends up at zero weight. That is the point of writing
//! them as separate named sources rather than one blended heuristic — when the
//! scoreboard says `stat:longshot` has skill and `stat:momentum` does not, you
//! have learned something specific.
//!
//! ## The baseline nobody should forget
//!
//! For a prediction market, the market price *is* a forecast, and a good one: it
//! is the aggregated, money-weighted opinion of everyone who bothered to trade.
//! It is also a martingale — its best estimate of tomorrow's price is today's.
//! So every forecaster here starts from the price and has to justify a
//! deviation, rather than producing a number from scratch and pretending the
//! market is not there.

use super::aggregate::{logistic, logit};

/// Standard normal CDF, via the Abramowitz & Stegun 7.1.26 error-function
/// approximation (|error| < 1.5e-7 — far below anything that matters here).
pub fn norm_cdf(z: f64) -> f64 {
    0.5 * (1.0 + erf(z / std::f64::consts::SQRT_2))
}

fn erf(x: f64) -> f64 {
    let sign = if x < 0.0 { -1.0 } else { 1.0 };
    let x = x.abs();
    let t = 1.0 / (1.0 + 0.327_591_1 * x);
    let y = 1.0
        - (((((1.061_405_429 * t - 1.453_152_027) * t) + 1.421_413_741) * t - 0.284_496_736) * t
            + 0.254_829_592)
            * t
            * (-x * x).exp();
    sign * y
}

/// **Favourite–longshot bias.** Across sports books, horse racing and prediction
/// markets, low-probability outcomes trade persistently rich and high-probability
/// outcomes persistently cheap: people overpay for lottery tickets.
///
/// The correction stretches log-odds by `k > 1`, which pushes longshots down and
/// favourites up while leaving anything near 0.5 essentially untouched (because
/// `logit(0.5) = 0`). That symmetry is what makes it a one-parameter hypothesis
/// rather than a fudge factor.
pub fn longshot_correction(market_p: f64, k: f64) -> f64 {
    logistic(logit(market_p) * k.clamp(0.5, 2.0))
}

/// **Odds momentum.** Prediction-market prices drift: news arrives gradually and
/// gets priced in over hours or days rather than instantly.
///
/// The hypothesis is that recent drift in log-odds continues, weakly. Two
/// dampers keep it honest:
///
/// - `beta` is small by default (0.15) — this is a nudge, not a trend-follower.
/// - the effect is scaled down as resolution approaches, because a market with
///   two days left has already absorbed most of what it is going to learn.
///
/// `history` is the market's own recent implied probabilities, oldest first.
pub fn odds_momentum(history: &[f64], beta: f64, days_to_resolution: Option<f64>) -> Option<f64> {
    if history.len() < 4 {
        return None;
    }
    let now = *history.last()?;
    // Drift over the recent window, in log-odds.
    let window = history.len().min(20);
    let past = history[history.len() - window];
    let drift = logit(now) - logit(past);
    if !drift.is_finite() {
        return None;
    }
    // Long-dated markets have more room left to drift; near resolution the
    // remaining information is small.
    let horizon_damp = match days_to_resolution {
        Some(d) if d > 0.0 => (d / (d + 7.0)).clamp(0.1, 1.0),
        _ => 0.5,
    };
    Some(logistic(logit(now) + beta * drift * horizon_damp))
}

/// **Liquidity-weighted confidence.** Not a forecast — a weight. A market with
/// $2k of liquidity is a handful of opinions; one with $2M has been argued over.
/// Deviating from a thin market's price is far more defensible than deviating
/// from a deep one's, and this scales that.
///
/// Returns 0..1, where 1 means "this market is thin, our own view counts for
/// relatively more".
pub fn thinness(liquidity: Option<f64>) -> f64 {
    match liquidity {
        Some(l) if l > 0.0 => (1.0 / (1.0 + l / 250_000.0)).clamp(0.05, 1.0),
        _ => 1.0, // unknown liquidity → assume thin, i.e. don't over-trust the price
    }
}

/// **P(price higher after `horizon` bars)** for a directional market.
///
/// A geometric random walk with drift: `P = Φ(μH / σ√H)`. The interesting part
/// is what happens to `μ`.
///
/// Estimated drift on a few hundred bars is almost entirely noise — the standard
/// error of a mean return swamps the mean itself at these sample sizes. So the
/// drift is shrunk toward zero by `n / (n + 200)` *and* by an explicit
/// `drift_trust` factor. The result is that this forecaster sits near 0.5 unless
/// a trend is both strong and long-established, which is the honest output. A
/// version that did not shrink would produce confident nonsense.
pub fn price_up_probability(history: &[f64], horizon: usize, drift_trust: f64) -> Option<f64> {
    if history.len() < 30 || horizon == 0 {
        return None;
    }
    let rets: Vec<f64> = history
        .windows(2)
        .filter(|w| w[0] > 0.0 && w[1] > 0.0)
        .map(|w| (w[1] / w[0]).ln())
        .collect();
    if rets.len() < 20 {
        return None;
    }

    let n = rets.len() as f64;
    let mean = rets.iter().sum::<f64>() / n;

    // EWMA volatility — recent regime matters more than the whole window.
    let lambda = 0.94;
    let mut var = rets.iter().map(|r| (r - mean).powi(2)).sum::<f64>() / n;
    for r in &rets {
        var = lambda * var + (1.0 - lambda) * (r - mean).powi(2);
    }
    let sigma = var.sqrt();
    if sigma <= 0.0 || !sigma.is_finite() {
        return None;
    }

    // Shrink the drift: sample-size shrinkage, then an explicit trust factor.
    let shrink = n / (n + 200.0);
    let mu = mean * shrink * drift_trust.clamp(0.0, 1.0);

    let h = horizon as f64;
    let z = (mu * h) / (sigma * h.sqrt());
    if !z.is_finite() {
        return None;
    }
    // A directional forecast beyond these bounds from a drift estimate is not
    // credible at any sample size we have.
    Some(norm_cdf(z).clamp(0.02, 0.98))
}

/// Realised volatility over the window, annualised-agnostic (per bar). Exposed
/// because the UI shows it next to the forecast: a 0.55 forecast means something
/// very different on a 0.2%/bar asset than on a 5%/bar one.
pub fn bar_volatility(history: &[f64]) -> Option<f64> {
    if history.len() < 20 {
        return None;
    }
    let rets: Vec<f64> = history
        .windows(2)
        .filter(|w| w[0] > 0.0 && w[1] > 0.0)
        .map(|w| (w[1] / w[0]).ln())
        .collect();
    if rets.len() < 10 {
        return None;
    }
    let n = rets.len() as f64;
    let mean = rets.iter().sum::<f64>() / n;
    Some((rets.iter().map(|r| (r - mean).powi(2)).sum::<f64>() / n).sqrt())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_normal_cdf_matches_known_values() {
        assert!((norm_cdf(0.0) - 0.5).abs() < 1e-9);
        assert!((norm_cdf(1.0) - 0.841_344_746).abs() < 1e-6);
        assert!((norm_cdf(-1.0) - 0.158_655_254).abs() < 1e-6);
        assert!((norm_cdf(1.96) - 0.975).abs() < 1e-3);
        // Tails stay in range rather than drifting outside it.
        assert!(norm_cdf(-10.0) >= 0.0 && norm_cdf(10.0) <= 1.0);
    }

    #[test]
    fn longshot_correction_pushes_extremes_out_and_leaves_the_middle_alone() {
        let k = 1.08;
        assert!(longshot_correction(0.03, k) < 0.03, "longshots trade rich");
        assert!(longshot_correction(0.95, k) > 0.95, "favourites trade cheap");
        assert!((longshot_correction(0.5, k) - 0.5).abs() < 1e-12, "0.5 is a fixed point");
        // It is monotone, so it can never reorder two markets.
        assert!(longshot_correction(0.4, k) < longshot_correction(0.6, k));
    }

    #[test]
    fn longshot_correction_with_k_of_one_changes_nothing() {
        for p in [0.05, 0.3, 0.5, 0.8, 0.97] {
            assert!((longshot_correction(p, 1.0) - p).abs() < 1e-9, "{p}");
        }
    }

    #[test]
    fn odds_momentum_continues_a_drift_but_only_a_little() {
        let rising: Vec<f64> = vec![0.30, 0.34, 0.38, 0.42, 0.46, 0.50];
        let p = odds_momentum(&rising, 0.15, Some(30.0)).unwrap();
        assert!(p > 0.50, "an upward drift should nudge above the last price");
        assert!(p < 0.56, "but it is a nudge, not an extrapolation — got {p}");
    }

    #[test]
    fn odds_momentum_is_damped_as_resolution_approaches() {
        let rising: Vec<f64> = vec![0.30, 0.34, 0.38, 0.42, 0.46, 0.50];
        let far = odds_momentum(&rising, 0.15, Some(90.0)).unwrap();
        let near = odds_momentum(&rising, 0.15, Some(1.0)).unwrap();
        assert!(far > near, "a market resolving tomorrow has less left to learn");
        assert!(near > 0.50);
    }

    #[test]
    fn odds_momentum_needs_history_and_says_so() {
        assert!(odds_momentum(&[0.5, 0.5], 0.15, Some(10.0)).is_none());
        assert!(odds_momentum(&[], 0.15, None).is_none());
    }

    #[test]
    fn a_flat_market_produces_no_momentum_signal() {
        let flat = vec![0.4; 10];
        let p = odds_momentum(&flat, 0.15, Some(30.0)).unwrap();
        assert!((p - 0.4).abs() < 1e-9);
    }

    #[test]
    fn thinness_falls_as_liquidity_rises() {
        let thin = thinness(Some(5_000.0));
        let deep = thinness(Some(5_000_000.0));
        assert!(thin > deep);
        assert!(deep < 0.1, "a $5M book should not be second-guessed lightly");
        assert_eq!(thinness(None), 1.0, "unknown liquidity is treated as thin");
        assert!((0.0..=1.0).contains(&thinness(Some(0.0))));
    }

    #[test]
    fn a_pure_random_walk_forecasts_a_coin_flip() {
        // Deterministic zig-zag: zero drift, non-zero vol.
        let series: Vec<f64> = (0..200)
            .map(|i| 100.0 * if i % 2 == 0 { 1.0 } else { 1.01 })
            .collect();
        let p = price_up_probability(&series, 10, 1.0).unwrap();
        assert!((p - 0.5).abs() < 0.1, "no drift should mean no opinion, got {p}");
    }

    /// A trending series with real bar-to-bar noise. A pure `1.004^i` curve has
    /// exactly zero volatility, which is not a market — it makes the z-score
    /// infinite and hides whatever the test meant to check.
    fn trending(n: usize, drift: f64) -> Vec<f64> {
        (0..n)
            .map(|i| {
                let wobble = 1.0 + 0.01 * ((i % 7) as f64 - 3.0) / 3.0;
                100.0 * (1.0 + drift).powi(i as i32) * wobble
            })
            .collect()
    }

    #[test]
    fn a_strong_persistent_uptrend_moves_the_forecast_above_a_half() {
        let p = price_up_probability(&trending(300, 0.004), 10, 1.0).unwrap();
        assert!(p > 0.6, "a 0.4%/bar trend should register, got {p}");
        let down = price_up_probability(&trending(300, -0.004), 10, 1.0).unwrap();
        assert!(down < 0.4, "and symmetrically downward, got {down}");
    }

    #[test]
    fn drift_shrinkage_keeps_a_short_lucky_run_near_a_half() {
        // 35 bars of steady rise is not evidence of drift — it is 35 bars.
        let p_short = price_up_probability(&trending(35, 0.004), 10, 1.0).unwrap();
        let p_long = price_up_probability(&trending(300, 0.004), 10, 1.0).unwrap();
        assert!(p_short < p_long, "less evidence must mean less confidence: {p_short} vs {p_long}");
        assert!(p_short < 0.8, "a short run must stay humble, got {p_short}");
    }

    #[test]
    fn zero_drift_trust_disables_the_forecaster_entirely() {
        let p = price_up_probability(&trending(300, 0.004), 10, 0.0).unwrap();
        assert!((p - 0.5).abs() < 1e-9, "trust 0 must mean exactly no opinion");
    }

    #[test]
    fn price_forecasts_need_data_and_never_panic_on_bad_input() {
        assert!(price_up_probability(&[], 10, 1.0).is_none());
        assert!(price_up_probability(&[100.0; 5], 10, 1.0).is_none());
        assert!(price_up_probability(&[100.0; 100], 0, 1.0).is_none());
        // A constant series has zero volatility — no division blow-up.
        assert!(price_up_probability(&[100.0; 100], 10, 1.0).is_none());
        // Zeros and negatives in the series are skipped, not fatal.
        let messy: Vec<f64> = (0..100).map(|i| if i == 50 { 0.0 } else { 100.0 + i as f64 }).collect();
        assert!(price_up_probability(&messy, 5, 1.0).is_some());
    }

    #[test]
    fn bar_volatility_is_larger_for_a_wilder_series() {
        let calm: Vec<f64> = (0..100).map(|i| 100.0 + (i % 2) as f64 * 0.1).collect();
        let wild: Vec<f64> = (0..100).map(|i| 100.0 + (i % 2) as f64 * 10.0).collect();
        assert!(bar_volatility(&wild).unwrap() > bar_volatility(&calm).unwrap());
        assert!(bar_volatility(&[100.0, 101.0]).is_none());
    }
}
