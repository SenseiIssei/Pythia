//! Performance statistics, and the two that actually decide whether a backtest
//! means anything.
//!
//! Sharpe, Sortino, drawdown and profit factor describe what *did* happen. They
//! say nothing about whether it will happen again — and on a strategy selected
//! as the best of N attempts, they are systematically optimistic, because the
//! selection itself is a search for luck.
//!
//! [`deflated_sharpe_ratio`] is the correction. It asks: given that I tried N
//! parameter sets, how good would the *best* of them look if none had any edge
//! at all? Then it reports the probability that the observed result beats that
//! bar. Below ~0.95 the honest answer is "this is indistinguishable from having
//! searched hard enough".
//!
//! Reference: Bailey & López de Prado, *The Deflated Sharpe Ratio* (2014).

use serde::{Deserialize, Serialize};

/// Euler–Mascheroni constant, used for the expected maximum of N draws.
const EULER_GAMMA: f64 = 0.577_215_664_901_532_9;

/// Headline statistics for one return stream.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Stats {
    pub bars: usize,
    pub trades: usize,
    /// Compounded return over the whole sample, as a fraction (0.12 = +12%).
    pub total_return: f64,
    /// Annualized Sharpe, zero risk-free rate.
    pub sharpe: f64,
    /// Annualized Sortino (downside deviation only).
    pub sortino: f64,
    /// Worst peak-to-trough on the equity curve, as a positive fraction.
    pub max_drawdown: f64,
    pub win_rate: f64,
    /// Gross wins / gross losses. `f64::INFINITY` when there are no losses.
    pub profit_factor: f64,
    /// Mean net return per trade — the number that has to clear costs.
    pub avg_trade: f64,
    pub skew: f64,
    /// Non-excess kurtosis (3.0 for a normal distribution).
    pub kurtosis: f64,
}

pub fn mean(xs: &[f64]) -> f64 {
    if xs.is_empty() {
        return 0.0;
    }
    xs.iter().sum::<f64>() / xs.len() as f64
}

/// Sample standard deviation (n−1). Zero for fewer than two observations.
pub fn stdev(xs: &[f64]) -> f64 {
    if xs.len() < 2 {
        return 0.0;
    }
    let m = mean(xs);
    (xs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (xs.len() as f64 - 1.0)).sqrt()
}

/// Sample skewness. Zero when there is no dispersion to be skewed.
pub fn skewness(xs: &[f64]) -> f64 {
    let n = xs.len() as f64;
    if xs.len() < 3 {
        return 0.0;
    }
    let m = mean(xs);
    let sd = stdev(xs);
    if sd == 0.0 {
        return 0.0;
    }
    xs.iter().map(|x| ((x - m) / sd).powi(3)).sum::<f64>() * n / ((n - 1.0) * (n - 2.0))
}

/// Non-excess kurtosis: 3.0 for a normal distribution, higher for fat tails.
pub fn kurtosis(xs: &[f64]) -> f64 {
    if xs.len() < 4 {
        return 3.0;
    }
    let m = mean(xs);
    let sd = stdev(xs);
    if sd == 0.0 {
        return 3.0;
    }
    let n = xs.len() as f64;
    xs.iter().map(|x| ((x - m) / sd).powi(4)).sum::<f64>() / n
}

/// Below this, a return series has no dispersion worth dividing by.
///
/// Not a paranoia constant: summing `(x − mean)²` over a constant series leaves
/// floating-point crumbs rather than exactly zero, and dividing a real mean by
/// a crumb yields a Sharpe around 1e16. That number then sails through every
/// downstream filter as the best strategy ever tested. Real per-bar return
/// deviations sit around 1e-3; 1e-12 is nine orders below anything genuine.
const MIN_DISPERSION: f64 = 1e-12;

/// Annualized Sharpe ratio at zero risk-free rate.
pub fn sharpe(returns: &[f64], bars_per_year: f64) -> f64 {
    let sd = stdev(returns);
    if sd < MIN_DISPERSION {
        return 0.0;
    }
    mean(returns) / sd * bars_per_year.sqrt()
}

/// Annualized Sortino ratio — like Sharpe, but only downside moves count as
/// risk. Upside volatility is not a problem anyone needs protecting from.
pub fn sortino(returns: &[f64], bars_per_year: f64) -> f64 {
    if returns.is_empty() {
        return 0.0;
    }
    let downside: Vec<f64> = returns.iter().copied().filter(|r| *r < 0.0).collect();
    if downside.is_empty() {
        return 0.0; // no losing bars in-sample is a red flag, not a triumph
    }
    let dd = (downside.iter().map(|r| r * r).sum::<f64>() / returns.len() as f64).sqrt();
    if dd < MIN_DISPERSION {
        return 0.0;
    }
    mean(returns) / dd * bars_per_year.sqrt()
}

/// Worst peak-to-trough decline on an equity curve, as a positive fraction.
pub fn max_drawdown(equity: &[f64]) -> f64 {
    let mut peak = f64::MIN;
    let mut worst: f64 = 0.0;
    for &v in equity {
        if v > peak {
            peak = v;
        }
        if peak > 0.0 {
            worst = worst.max((peak - v) / peak);
        }
    }
    worst
}

// ── normal distribution helpers ─────────────────────────────────────────────

/// Error function — Abramowitz & Stegun 7.1.26, |error| ≤ 1.5e-7.
fn erf(x: f64) -> f64 {
    let sign = if x < 0.0 { -1.0 } else { 1.0 };
    let x = x.abs();
    let t = 1.0 / (1.0 + 0.327_591_1 * x);
    let y = 1.0
        - ((((1.061_405_429 * t - 1.453_152_027) * t + 1.421_413_741) * t - 0.284_496_736) * t
            + 0.254_829_592)
            * t
            * (-x * x).exp();
    sign * y
}

/// Standard normal CDF.
pub fn norm_cdf(x: f64) -> f64 {
    0.5 * (1.0 + erf(x / std::f64::consts::SQRT_2))
}

/// Standard normal quantile (inverse CDF) — Acklam's rational approximation,
/// accurate to about 1.15e-9 in the region we care about.
pub fn norm_ppf(p: f64) -> f64 {
    if p <= 0.0 {
        return f64::NEG_INFINITY;
    }
    if p >= 1.0 {
        return f64::INFINITY;
    }
    const A: [f64; 6] = [
        -3.969_683_028_665_376e1, 2.209_460_984_245_205e2, -2.759_285_104_469_687e2,
        1.383_577_518_672_690e2, -3.066_479_806_614_716e1, 2.506_628_277_459_239,
    ];
    const B: [f64; 5] = [
        -5.447_609_879_822_406e1, 1.615_858_368_580_409e2, -1.556_989_798_598_866e2,
        6.680_131_188_771_972e1, -1.328_068_155_288_572e1,
    ];
    const C: [f64; 6] = [
        -7.784_894_002_430_293e-3, -3.223_964_580_411_365e-1, -2.400_758_277_161_838,
        -2.549_732_539_343_734, 4.374_664_141_464_968, 2.938_163_982_698_783,
    ];
    const D: [f64; 4] = [
        7.784_695_709_041_462e-3, 3.224_671_290_700_398e-1, 2.445_134_137_142_996,
        3.754_408_661_907_416,
    ];
    const P_LOW: f64 = 0.024_25;

    if p < P_LOW {
        let q = (-2.0 * p.ln()).sqrt();
        (((((C[0] * q + C[1]) * q + C[2]) * q + C[3]) * q + C[4]) * q + C[5])
            / ((((D[0] * q + D[1]) * q + D[2]) * q + D[3]) * q + 1.0)
    } else if p <= 1.0 - P_LOW {
        let q = p - 0.5;
        let r = q * q;
        (((((A[0] * r + A[1]) * r + A[2]) * r + A[3]) * r + A[4]) * r + A[5]) * q
            / (((((B[0] * r + B[1]) * r + B[2]) * r + B[3]) * r + B[4]) * r + 1.0)
    } else {
        let q = (-2.0 * (1.0 - p).ln()).sqrt();
        -(((((C[0] * q + C[1]) * q + C[2]) * q + C[3]) * q + C[4]) * q + C[5])
            / ((((D[0] * q + D[1]) * q + D[2]) * q + D[3]) * q + 1.0)
    }
}

// ── the honesty metrics ─────────────────────────────────────────────────────

/// Probability that the true Sharpe exceeds `benchmark`, given the sample's
/// length, skew and fat tails.
///
/// A Sharpe estimated from 40 returns is nearly meaningless; the same number
/// from 4,000 is evidence. This is what converts "the number was 1.8" into a
/// probability you can act on. Non-normal returns are penalised: negative skew
/// and fat tails both mean the estimate is less trustworthy than it looks.
pub fn probabilistic_sharpe_ratio(
    observed_sr: f64,
    benchmark_sr: f64,
    n: usize,
    skew: f64,
    kurt: f64,
) -> f64 {
    if n < 2 {
        return 0.0;
    }
    // Variance of the Sharpe estimator under non-normal returns.
    let denom = 1.0 - skew * observed_sr + (kurt - 1.0) / 4.0 * observed_sr * observed_sr;
    if denom <= 0.0 {
        return 0.0; // estimator variance is undefined — claim nothing
    }
    let z = (observed_sr - benchmark_sr) * ((n as f64 - 1.0).sqrt()) / denom.sqrt();
    norm_cdf(z)
}

/// The Sharpe a strategy with **no edge at all** would be expected to post,
/// purely by being the best of `n_trials` attempts.
///
/// This is the bar a backtest has to clear. Try enough parameter sets and one
/// of them will look excellent; that is arithmetic, not alpha.
pub fn expected_max_sharpe(n_trials: usize, trial_sr_variance: f64) -> f64 {
    if n_trials <= 1 || trial_sr_variance <= 0.0 {
        return 0.0;
    }
    let n = n_trials as f64;
    let e = std::f64::consts::E;
    // Expected maximum of N standard normal draws (Bailey & López de Prado).
    let z = (1.0 - EULER_GAMMA) * norm_ppf(1.0 - 1.0 / n)
        + EULER_GAMMA * norm_ppf(1.0 - 1.0 / (n * e));
    trial_sr_variance.sqrt() * z
}

/// Probability the observed Sharpe reflects real edge rather than the best draw
/// from `n_trials` attempts.
///
/// Read it as a confidence level: **≥0.95 is the usual bar**, below ~0.90 the
/// result is not distinguishable from a thorough search of noise. It is a
/// deliberately unforgiving number, and it is the single most useful line in
/// any backtest report.
pub fn deflated_sharpe_ratio(
    observed_sr: f64,
    n: usize,
    skew: f64,
    kurt: f64,
    n_trials: usize,
    trial_sr_variance: f64,
) -> f64 {
    let sr0 = expected_max_sharpe(n_trials, trial_sr_variance);
    probabilistic_sharpe_ratio(observed_sr, sr0, n, skew, kurt)
}

/// [`deflated_sharpe_ratio`] for an **annualised** Sharpe and an annualised
/// trial variance.
///
/// The PSR and DSR formulas are written for the per-period Sharpe: the
/// `sqrt(n - 1)` in the z-score already scales a per-bar estimate by the
/// sample length. Feeding them an annualised Sharpe multiplies the z-score by
/// `sqrt(bars_per_year)` (about 19 for daily crypto), which turns almost any
/// positive result into "99 % confident". Everything in this crate reports
/// annualised Sharpes, so this is the entry point to use.
pub fn deflated_sharpe_annualised(
    observed_sr_ann: f64,
    bars_per_year: f64,
    n: usize,
    skew: f64,
    kurt: f64,
    n_trials: usize,
    trial_sr_variance_ann: f64,
) -> f64 {
    let k = bars_per_year.max(1.0);
    deflated_sharpe_ratio(observed_sr_ann / k.sqrt(), n, skew, kurt, n_trials, trial_sr_variance_ann / k)
}

/// Full statistics for a per-bar return stream and its realised trades.
pub fn summarize(
    bar_returns: &[f64],
    equity: &[f64],
    trade_returns: &[f64],
    bars_per_year: f64,
) -> Stats {
    let wins: Vec<f64> = trade_returns.iter().copied().filter(|r| *r > 0.0).collect();
    let losses: Vec<f64> = trade_returns.iter().copied().filter(|r| *r <= 0.0).collect();
    let gross_win: f64 = wins.iter().sum();
    let gross_loss: f64 = losses.iter().map(|r| r.abs()).sum();

    Stats {
        bars: bar_returns.len(),
        trades: trade_returns.len(),
        total_return: equity.last().copied().unwrap_or(1.0) / equity.first().copied().unwrap_or(1.0) - 1.0,
        sharpe: sharpe(bar_returns, bars_per_year),
        sortino: sortino(bar_returns, bars_per_year),
        max_drawdown: max_drawdown(equity),
        win_rate: if trade_returns.is_empty() { 0.0 } else { wins.len() as f64 / trade_returns.len() as f64 },
        profit_factor: if gross_loss > 0.0 {
            gross_win / gross_loss
        } else if gross_win > 0.0 {
            f64::INFINITY
        } else {
            0.0
        },
        avg_trade: mean(trade_returns),
        skew: skewness(bar_returns),
        kurtosis: kurtosis(bar_returns),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approx(a: f64, b: f64, tol: f64) -> bool {
        (a - b).abs() < tol
    }

    #[test]
    fn normal_cdf_matches_known_values() {
        assert!(approx(norm_cdf(0.0), 0.5, 1e-7));
        assert!(approx(norm_cdf(1.0), 0.841_344_7, 1e-6));
        assert!(approx(norm_cdf(-1.96), 0.025, 1e-5));
        assert!(approx(norm_cdf(1.645), 0.95, 1e-4));
    }

    #[test]
    fn normal_ppf_inverts_the_cdf() {
        for p in [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99] {
            assert!(approx(norm_cdf(norm_ppf(p)), p, 1e-6), "failed at p={p}");
        }
        assert!(approx(norm_ppf(0.975), 1.959_964, 1e-5));
    }

    #[test]
    fn a_constant_return_series_has_no_sharpe_rather_than_an_enormous_one() {
        // Summing (x − mean)² over a constant series leaves floating-point
        // crumbs, not zero. Dividing by one of those produced a Sharpe of ~2e16,
        // which would top any ranking it entered.
        let r = vec![0.001; 100];
        assert_eq!(sharpe(&r, 252.0), 0.0, "constant returns are not a risk-free money machine");
        assert_eq!(sortino(&r, 252.0), 0.0);
    }

    #[test]
    fn sharpe_scales_with_the_annualization_factor() {

        let mixed: Vec<f64> = (0..252).map(|i| if i % 2 == 0 { 0.01 } else { -0.005 }).collect();
        let s = sharpe(&mixed, 252.0);
        assert!(s > 0.0);
        // Quadrupling the periods per year doubles the annualized figure.
        assert!(approx(sharpe(&mixed, 1008.0), s * 2.0, 1e-9));
    }

    #[test]
    fn sortino_ignores_upside_volatility() {
        // Same mean, but one series has its variance entirely on the upside.
        let choppy: Vec<f64> = (0..100).map(|i| if i % 2 == 0 { 0.02 } else { -0.01 }).collect();
        let upside: Vec<f64> = (0..100).map(|i| if i % 2 == 0 { 0.03 } else { -0.001 }).collect();
        assert!(
            sortino(&upside, 252.0) > sortino(&choppy, 252.0),
            "punishing upside volatility is what Sortino exists to avoid"
        );
    }

    #[test]
    fn max_drawdown_finds_the_worst_trough_not_the_last() {
        // Deep early trough, shallower late one — the early one must win.
        let eq = vec![100.0, 120.0, 60.0, 130.0, 110.0];
        assert!(approx(max_drawdown(&eq), 0.5, 1e-9));
        assert_eq!(max_drawdown(&[1.0, 2.0, 3.0]), 0.0);
    }

    #[test]
    fn skew_and_kurtosis_have_the_right_signs() {
        let mut left_tail = vec![0.01; 60];
        left_tail.push(-0.5); // one disaster
        assert!(skewness(&left_tail) < 0.0);
        assert!(kurtosis(&left_tail) > 3.0, "a fat tail is not normal");

        let symmetric: Vec<f64> = (0..100).map(|i| if i % 2 == 0 { 0.01 } else { -0.01 }).collect();
        assert!(approx(skewness(&symmetric), 0.0, 1e-9));
    }

    #[test]
    fn psr_rewards_longer_samples() {
        // The same Sharpe is far more believable from 2000 observations than 50.
        let short = probabilistic_sharpe_ratio(1.0, 0.0, 50, 0.0, 3.0);
        let long = probabilistic_sharpe_ratio(1.0, 0.0, 2000, 0.0, 3.0);
        assert!(long > short, "{long} should exceed {short}");
        assert!(long > 0.99);
    }

    #[test]
    fn psr_punishes_negative_skew_and_fat_tails() {
        // Deliberately a modest Sharpe on a short sample: with a strong Sharpe
        // over hundreds of bars both cases saturate at 1.0 and the comparison
        // says nothing.
        let clean = probabilistic_sharpe_ratio(0.15, 0.0, 60, 0.0, 3.0);
        let nasty = probabilistic_sharpe_ratio(0.15, 0.0, 60, -1.5, 12.0);
        assert!(
            nasty < clean,
            "a strategy that wins small and loses huge deserves less confidence ({nasty} vs {clean})"
        );
        assert!(clean > 0.5 && clean < 1.0, "clean case should be informative, got {clean}");
    }

    #[test]
    fn expected_max_sharpe_grows_with_the_number_of_attempts() {
        let few = expected_max_sharpe(5, 0.25);
        let many = expected_max_sharpe(500, 0.25);
        assert!(many > few, "searching harder raises the bar you must clear");
        // A single attempt has nothing to deflate.
        assert_eq!(expected_max_sharpe(1, 0.25), 0.0);
        assert_eq!(expected_max_sharpe(100, 0.0), 0.0);
    }

    #[test]
    fn deflated_sharpe_deflates() {
        // A Sharpe of 1.5 found on the first try is credible; the same number
        // found as the best of 200 tries, on trials that varied a lot, is not.
        let honest = deflated_sharpe_ratio(1.5, 1000, 0.0, 3.0, 1, 0.0);
        let searched = deflated_sharpe_ratio(1.5, 1000, 0.0, 3.0, 200, 0.5);
        assert!(honest > 0.99);
        assert!(searched < honest, "{searched} should be well below {honest}");
    }

    #[test]
    fn an_annualised_sharpe_is_deflated_on_the_per_period_scale() {
        // An annual Sharpe of 1.0 over two years of daily bars, best of nine
        // tries whose Sharpes spread with variance 0.1. Fed annualised numbers
        // directly, the z-score is inflated by sqrt(365) and the answer becomes
        // a step function: anything above the bar scores ~100 %. On the
        // per-period scale it is a real but unconvincing 70-80 %.
        let naive = deflated_sharpe_ratio(1.0, 730, 0.0, 3.0, 9, 0.1);
        let honest = deflated_sharpe_annualised(1.0, 365.0, 730, 0.0, 3.0, 9, 0.1);
        assert!(naive > 0.99, "the old usage was overconfident: {naive}");
        assert!(honest < 0.9 && honest > 0.5, "best of nine at Sharpe 1.0 is suggestive, not proof: {honest}");
        // A genuinely strong, long result still clears the bar.
        let strong = deflated_sharpe_annualised(2.5, 365.0, 3000, 0.0, 3.0, 9, 0.25);
        assert!(strong > 0.95, "{strong}");
        // With one trial and no spread it is the plain PSR against zero.
        let one = deflated_sharpe_annualised(1.0, 252.0, 1000, 0.0, 3.0, 1, 0.0);
        let psr = probabilistic_sharpe_ratio(1.0 / 252f64.sqrt(), 0.0, 1000, 0.0, 3.0);
        assert!((one - psr).abs() < 1e-12);
    }

    #[test]
    fn summarize_reports_an_infinite_profit_factor_without_dividing_by_zero() {
        let trades = vec![0.02, 0.03];
        let s = summarize(&[0.01, 0.02], &[1.0, 1.05], &trades, 252.0);
        assert!(s.profit_factor.is_infinite());
        assert_eq!(s.win_rate, 1.0);
        assert_eq!(s.trades, 2);

        // And no trades at all is 0, not NaN.
        let empty = summarize(&[], &[1.0], &[], 252.0);
        assert_eq!(empty.profit_factor, 0.0);
        assert_eq!(empty.win_rate, 0.0);
    }
}
