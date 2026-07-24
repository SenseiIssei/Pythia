//! Walk-forward validation: the only backtest worth believing.
//!
//! An in-sample backtest answers "could I have chosen parameters that made
//! money on this data?" — and the answer is essentially always yes, because
//! that is a curve-fitting exercise with a guaranteed solution. It tells you
//! nothing about tomorrow.
//!
//! Walk-forward asks the useful question instead. Fit parameters on a window of
//! history, then evaluate them **only** on data that came after it, and repeat
//! rolling forward. Every number reported here comes from out-of-sample bars —
//! decisions made with no knowledge of what followed.
//!
//! On top of that sits [`metrics::deflated_sharpe_ratio`], which prices in the
//! search itself: trying twelve parameter sets per fold and keeping the winner
//! is a hunt for luck, and the deflation says how much of the result that
//! explains.
//!
//! Expect most strategies to fail. That is the harness working.

pub mod backtest;
pub mod metrics;

use crate::engine::{StrategyConfig, StrategyKind, StrategyParam};
use crate::marketdata::Ohlc;
use backtest::{BacktestConfig, WARMUP};
use metrics::Stats;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WalkForwardConfig {
    /// Number of out-of-sample windows. Each fold fits on everything before it
    /// and is scored on the window that follows.
    pub folds: usize,
    /// A verdict needs at least this many out-of-sample trades — three lucky
    /// trades is not a track record.
    pub min_trades: usize,
    /// Trades a parameter set must make in-sample to be *selectable*.
    ///
    /// Kept low on purpose. Trend rules with wide ATR stops hold for weeks, so
    /// on a two-year daily sample split into folds an in-sample window may only
    /// contain a handful of trades. Demanding more doesn't raise the bar — it
    /// silently discards every candidate, skips the fold, and reports "no data"
    /// for a strategy that was never actually tested.
    pub min_is_trades: usize,
    pub bt: BacktestConfig,
}

impl Default for WalkForwardConfig {
    fn default() -> Self {
        Self { folds: 4, min_trades: 20, min_is_trades: 3, bt: BacktestConfig::default() }
    }
}

/// What the evidence supports. Deliberately blunt.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Verdict {
    /// Positive out-of-sample and unlikely to be a product of the search.
    Pass,
    /// Positive out-of-sample, but not distinguishable from luck at 95%.
    Marginal,
    /// Lost money out-of-sample.
    Fail,
    /// Not enough trades or history to make any claim.
    Insufficient,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FoldResult {
    pub fold: usize,
    pub is_end: usize,
    pub oos_end: usize,
    /// The parameters in-sample optimization selected for this fold.
    pub chosen: Vec<(String, f64)>,
    pub is_sharpe: f64,
    /// False when no parameter set traded enough in-sample to be selectable and
    /// the fold fell back to the shipped defaults. The out-of-sample result is
    /// still real; it just isn't evidence that the *fitting* works.
    pub fitted: bool,
    pub oos: Stats,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MarketReport {
    pub market_id: String,
    pub symbol: String,
    pub folds: Vec<FoldResult>,
    /// Aggregate over every out-of-sample bar, all folds concatenated.
    pub oos: Stats,
    /// Per-bar out-of-sample returns, for portfolio aggregation.
    #[serde(skip)]
    pub oos_returns: Vec<f64>,
    /// Per-trade out-of-sample returns. Kept separately from `oos_returns`
    /// because win rate and profit factor are trade-level facts that cannot be
    /// recovered from a per-bar series.
    #[serde(skip)]
    pub oos_trade_returns: Vec<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StrategyReport {
    pub strategy_id: String,
    pub name: String,
    pub kind: StrategyKind,
    pub markets: Vec<MarketReport>,
    /// Equal-weight across markets — the number that describes running this
    /// strategy over its whole universe, which is how it actually trades.
    pub portfolio: Stats,
    /// Parameter sets tried per fold. Feeds the deflation.
    pub trials: usize,
    /// Probability the out-of-sample Sharpe is real rather than the best draw
    /// from `trials` attempts. ≥0.95 is the usual bar.
    pub deflated_sharpe: f64,
    pub verdict: Verdict,
    pub reason: String,
    /// Out-of-sample windows that actually produced a result, summed across
    /// markets. Zero here means the sample was too short to fold, not that the
    /// strategy lost.
    pub folds_run: usize,
    /// Folds where no parameter set traded enough in-sample to choose between,
    /// so the shipped defaults were used instead.
    pub folds_unfitted: usize,
}

/// Candidate parameter sets for a strategy kind.
///
/// Kept small on purpose. Every extra combination raises the bar the result has
/// to clear in [`metrics::deflated_sharpe_ratio`], so a huge grid is not a free
/// way to find a better strategy — it is a way to need more evidence.
pub fn param_grid(kind: StrategyKind) -> Vec<Vec<(String, f64)>> {
    let p = |pairs: &[(&str, f64)]| -> Vec<(String, f64)> {
        pairs.iter().map(|(k, v)| (k.to_string(), *v)).collect()
    };
    match kind {
        StrategyKind::EmaCross => {
            let mut out = Vec::new();
            for fast in [5.0, 9.0, 13.0] {
                for slow in [21.0, 34.0, 55.0] {
                    out.push(p(&[("fast", fast), ("slow", slow)]));
                }
            }
            out
        }
        StrategyKind::MultiTf => {
            let mut out = Vec::new();
            for fast in [5.0, 9.0] {
                for slow in [21.0, 34.0] {
                    for htf in [50.0, 100.0] {
                        out.push(p(&[("fast", fast), ("slow", slow), ("htf", htf)]));
                    }
                }
            }
            out
        }
        StrategyKind::Bollinger => {
            let mut out = Vec::new();
            for period in [14.0, 20.0, 30.0] {
                for k in [1.5, 2.0, 2.5] {
                    out.push(p(&[("period", period), ("k", k)]));
                }
            }
            out
        }
        StrategyKind::RsiReversal => {
            let mut out = Vec::new();
            for period in [7.0, 14.0, 21.0] {
                for (os, ob) in [(20.0, 80.0), (30.0, 70.0)] {
                    out.push(p(&[("period", period), ("oversold", os), ("overbought", ob)]));
                }
            }
            out
        }
        StrategyKind::Breakout => {
            [10.0, 20.0, 40.0, 55.0].iter().map(|v| p(&[("period", *v)])).collect()
        }
        // MACD is parameterless here; the rest are not single-market technical
        // rules and are validated elsewhere (or not at all — see `is_validatable`).
        _ => vec![vec![]],
    }
}

/// Whether this strategy kind can be validated by this harness.
///
/// Pairs needs two correlated legs, Prob-Edge needs prediction-market odds and
/// a probability model, Composed is user-defined, Manual is a human. Reporting
/// a verdict on those from single-market candles would be a lie of omission.
pub fn is_validatable(kind: StrategyKind) -> bool {
    matches!(
        kind,
        StrategyKind::EmaCross
            | StrategyKind::MultiTf
            | StrategyKind::Bollinger
            | StrategyKind::RsiReversal
            | StrategyKind::MacdTrend
            | StrategyKind::Breakout
    )
}

fn with_params(base: &StrategyConfig, params: &[(String, f64)]) -> StrategyConfig {
    let mut cfg = base.clone();
    // `run_strategy` emits nothing for a paused strategy. Several ship paused,
    // and validating them as-is silently produced "0 trades across 36 folds" —
    // which reads as "no data" when the truth is "we never asked it anything".
    // Validation is a question about the rule, not about its current switch.
    cfg.state = crate::engine::StrategyState::Paper;
    for (key, value) in params {
        if let Some(p) = cfg.params.iter_mut().find(|p| &p.key == key) {
            p.value = *value;
        } else {
            cfg.params.push(StrategyParam {
                key: key.clone(),
                label: key.clone(),
                value: *value,
                min: 0.0,
                max: 1000.0,
                step: 1.0,
            });
        }
    }
    cfg
}

/// Equal-weight the per-market return series into one portfolio series.
/// Truncates to the shortest input so a market that produced fewer bars can't
/// silently shift the others.
fn pool(series: &[Vec<f64>]) -> Vec<f64> {
    let len = series.iter().map(|s| s.len()).min().unwrap_or(0);
    let n = series.len() as f64;
    if n == 0.0 {
        return Vec::new();
    }
    (0..len).map(|i| series.iter().map(|s| s[i]).sum::<f64>() / n).collect()
}

/// Walk one strategy forward over one market's candles.
///
/// Selection here is per-market. [`walk_forward`] fits at portfolio level
/// instead, which is both more robust and the footing the deflation needs;
/// this remains for inspecting a single market in isolation.
pub fn walk_forward_market(
    base: &StrategyConfig,
    market_id: &str,
    symbol: &str,
    bars: &[Ohlc],
    wf: &WalkForwardConfig,
) -> (MarketReport, Vec<f64>) {
    let n = bars.len();
    let grid = param_grid(base.kind);
    let mut folds = Vec::new();
    let mut oos_returns: Vec<f64> = Vec::new();
    let mut oos_trade_returns: Vec<f64> = Vec::new();
    // One entry per selection (fold), holding the variance of that selection's
    // candidate Sharpes — see the note where this is consumed.
    let mut selection_vars: Vec<f64> = Vec::new();

    // Each fold needs a full warmup ahead of its out-of-sample window, so the
    // strategy enters it with the same history depth it would have live.
    let window = n / (wf.folds + 1);
    if window <= WARMUP + wf.min_trades {
        return (
            MarketReport {
                market_id: market_id.into(),
                symbol: symbol.into(),
                folds,
                oos: Stats::default(),
                oos_returns: Vec::new(),
                oos_trade_returns: Vec::new(),
            },
            selection_vars,
        );
    }

    for f in 0..wf.folds {
        let is_end = window * (f + 1);
        let oos_end = (window * (f + 2)).min(n);
        if oos_end <= is_end || is_end < WARMUP + 2 {
            continue;
        }

        // ── in-sample: pick the parameters, seeing nothing past `is_end` ─────
        let mut best: Option<(Vec<(String, f64)>, f64)> = None;
        let mut fold_sharpes: Vec<f64> = Vec::with_capacity(grid.len());
        for params in &grid {
            let cfg = with_params(base, params);
            let r = backtest::run(&cfg, market_id, symbol, &bars[..is_end], &wf.bt);
            fold_sharpes.push(r.stats.sharpe);
            // A parameter set that barely traded in-sample has not earned the
            // right to be chosen, however flattering its Sharpe.
            if r.stats.trades < wf.min_is_trades {
                continue;
            }
            if best.as_ref().map(|(_, s)| r.stats.sharpe > *s).unwrap_or(true) {
                best = Some((params.clone(), r.stats.sharpe));
            }
        }
        // Nothing traded enough in-sample to choose between. Fall back to the
        // shipped parameters and still score the window — skipping it would
        // report "no data" for a strategy that simply trades infrequently,
        // which is a very different claim.
        let fitted = best.is_some();
        // 0.0 rather than NaN for the unfitted case: serde_json turns a NaN into
        // a bare `null`, which the dashboard would render as a missing field.
        let (chosen, is_sharpe) = best
            .unwrap_or_else(|| (base.params.iter().map(|p| (p.key.clone(), p.value)).collect(), 0.0));

        // ── out-of-sample: run the chosen parameters forward ─────────────────
        // Include WARMUP bars of lead-in so indicators are warm at the window's
        // first bar, then drop them — the backtester's own warmup skip lines the
        // returns up exactly with the out-of-sample range.
        let lead = is_end.saturating_sub(WARMUP);
        let cfg = with_params(base, &chosen);
        let r = backtest::run(&cfg, market_id, symbol, &bars[lead..oos_end], &wf.bt);

        selection_vars.push(metrics::stdev(&fold_sharpes).powi(2));
        oos_returns.extend_from_slice(&r.bar_returns);
        oos_trade_returns.extend(r.trades.iter().map(|t| t.ret));
        folds.push(FoldResult {
            fold: f,
            is_end,
            oos_end,
            chosen,
            is_sharpe,
            fitted,
            oos: r.stats,
        });
    }

    let oos = stats_from_returns(&oos_returns, &oos_trade_returns, wf.bt.bars_per_year);
    (
        MarketReport {
            market_id: market_id.into(),
            symbol: symbol.into(),
            folds,
            oos,
            oos_returns,
            oos_trade_returns,
        },
        selection_vars,
    )
}

/// Rebuild an equity curve from a return stream and summarize it.
fn stats_from_returns(returns: &[f64], trade_returns: &[f64], bars_per_year: f64) -> Stats {
    let mut equity = vec![1.0];
    let mut e = 1.0;
    for r in returns {
        e *= 1.0 + r;
        equity.push(e);
    }
    metrics::summarize(returns, &equity, trade_returns, bars_per_year)
}

/// Walk one strategy forward across its whole universe, fitting **at portfolio
/// level**.
///
/// Parameters are chosen once per fold for the entire universe, not once per
/// market. Two reasons, and the second is the important one:
///
/// - Fitting per market on a ~110-bar window is overfitting with extra steps.
///   One parameter set that works across nine markets is a far stronger claim
///   than nine parameter sets each tuned to its own noise.
/// - The deflation only means anything if the trial Sharpes and the reported
///   Sharpe are measured the same way. Deflating a pooled multi-market Sharpe
///   against the spread of *single-market* Sharpes compares a diversified,
///   low-variance estimate against a noisy one, and over-penalises enormously —
///   it scored a genuine +28% out-of-sample result at 0% confidence.
pub fn walk_forward(
    base: &StrategyConfig,
    markets: &[(String, String, Vec<Ohlc>)],
    wf: &WalkForwardConfig,
) -> StrategyReport {
    let grid = param_grid(base.kind);
    let trials = grid.len();

    // Align on the most recent bars so every market covers the same window.
    let len = markets.iter().map(|(_, _, b)| b.len()).min().unwrap_or(0);
    let aligned: Vec<(&String, &String, &[Ohlc])> = markets
        .iter()
        .map(|(id, sym, bars)| (id, sym, &bars[bars.len() - len..]))
        .collect();

    let mut portfolio_returns: Vec<f64> = Vec::new();
    let mut all_trade_returns: Vec<f64> = Vec::new();
    let mut selection_vars: Vec<f64> = Vec::new();
    let mut folds_run = 0usize;
    let mut folds_unfitted = 0usize;
    // Per-market accumulators, in `aligned` order.
    let mut market_returns: Vec<Vec<f64>> = vec![Vec::new(); aligned.len()];
    let mut market_trades: Vec<Vec<f64>> = vec![Vec::new(); aligned.len()];
    let mut market_folds: Vec<Vec<FoldResult>> = vec![Vec::new(); aligned.len()];

    let window = if aligned.is_empty() { 0 } else { len / (wf.folds + 1) };
    let base_params: Vec<(String, f64)> =
        base.params.iter().map(|p| (p.key.clone(), p.value)).collect();

    if window > WARMUP + 10 {
        for f in 0..wf.folds {
            let is_end = window * (f + 1);
            let oos_end = (window * (f + 2)).min(len);
            if oos_end <= is_end || is_end < WARMUP + 2 {
                continue;
            }

            // ── in-sample: one parameter set for the whole universe ──────────
            let mut sharpes: Vec<f64> = Vec::with_capacity(grid.len());
            let mut best: Option<(usize, f64)> = None;
            for (gi, params) in grid.iter().enumerate() {
                let cfg = with_params(base, params);
                let mut series = Vec::with_capacity(aligned.len());
                let mut trades = 0usize;
                for (id, sym, bars) in &aligned {
                    let r = backtest::run(&cfg, id, sym, &bars[..is_end], &wf.bt);
                    trades += r.stats.trades;
                    series.push(r.bar_returns);
                }
                let sr = metrics::sharpe(&pool(&series), wf.bt.bars_per_year);
                sharpes.push(sr);
                if trades >= wf.min_is_trades && best.map(|(_, s)| sr > s).unwrap_or(true) {
                    best = Some((gi, sr));
                }
            }
            selection_vars.push(metrics::stdev(&sharpes).powi(2));

            let fitted = best.is_some();
            let (chosen, is_sharpe) = match best {
                Some((gi, sr)) => (grid[gi].clone(), sr),
                None => (base_params.clone(), 0.0),
            };

            // ── out-of-sample: those parameters, forward only ───────────────
            // WARMUP bars of lead-in so indicators are warm at the window's
            // first bar; the backtester's own warmup skip lines the returns up
            // exactly with the out-of-sample range.
            let lead = is_end.saturating_sub(WARMUP);
            let cfg = with_params(base, &chosen);
            let mut series = Vec::with_capacity(aligned.len());
            for (m, (id, sym, bars)) in aligned.iter().enumerate() {
                let r = backtest::run(&cfg, id, sym, &bars[lead..oos_end], &wf.bt);
                market_returns[m].extend_from_slice(&r.bar_returns);
                market_trades[m].extend(r.trades.iter().map(|t| t.ret));
                all_trade_returns.extend(r.trades.iter().map(|t| t.ret));
                market_folds[m].push(FoldResult {
                    fold: f,
                    is_end,
                    oos_end,
                    chosen: chosen.clone(),
                    is_sharpe,
                    fitted,
                    oos: r.stats.clone(),
                });
                series.push(r.bar_returns);
            }
            portfolio_returns.extend(pool(&series));
            folds_run += 1;
            if !fitted {
                folds_unfitted += 1;
            }
        }
    }

    let reports: Vec<MarketReport> = aligned
        .iter()
        .enumerate()
        .map(|(m, (id, sym, _))| MarketReport {
            market_id: (*id).clone(),
            symbol: (*sym).clone(),
            folds: std::mem::take(&mut market_folds[m]),
            oos: stats_from_returns(&market_returns[m], &market_trades[m], wf.bt.bars_per_year),
            oos_returns: std::mem::take(&mut market_returns[m]),
            oos_trade_returns: std::mem::take(&mut market_trades[m]),
        })
        .collect();

    let portfolio = stats_from_returns(&portfolio_returns, &all_trade_returns, wf.bt.bars_per_year);

    // Trial variance = spread of the candidates *within* a selection, averaged
    // across folds — the same footing as `portfolio.sharpe`, since both are
    // pooled multi-market estimates over comparable windows.
    let trial_var = metrics::mean(&selection_vars);
    let deflated = metrics::deflated_sharpe_ratio(
        portfolio.sharpe,
        portfolio.bars,
        portfolio.skew,
        portfolio.kurtosis,
        trials.max(1),
        trial_var,
    );

    let (verdict, reason) = judge(&portfolio, deflated, wf.min_trades, folds_run);

    StrategyReport {
        strategy_id: base.id.clone(),
        name: base.name.clone(),
        kind: base.kind,
        markets: reports,
        portfolio,
        trials,
        deflated_sharpe: deflated,
        verdict,
        reason,
        folds_run,
        folds_unfitted,
    }
}

fn judge(portfolio: &Stats, deflated: f64, min_trades: usize, folds_run: usize) -> (Verdict, String) {
    if folds_run == 0 {
        return (
            Verdict::Insufficient,
            "history too short to split into folds — fetch more bars or use fewer folds".into(),
        );
    }
    if portfolio.bars == 0 || portfolio.trades < min_trades {
        return (
            Verdict::Insufficient,
            format!(
                "only {} out-of-sample trade(s) across {folds_run} fold(s) — no claim either way",
                portfolio.trades
            ),
        );
    }
    if portfolio.total_return <= 0.0 || portfolio.sharpe <= 0.0 {
        return (
            Verdict::Fail,
            format!(
                "lost money out-of-sample ({:+.1}%, Sharpe {:.2}) after costs",
                portfolio.total_return * 100.0,
                portfolio.sharpe
            ),
        );
    }
    if deflated < 0.95 {
        return (
            Verdict::Marginal,
            format!(
                "positive ({:+.1}%, Sharpe {:.2}) but only {:.0}% confident it isn't the best of {} guesses",
                portfolio.total_return * 100.0,
                portfolio.sharpe,
                deflated * 100.0,
                "the",
            ),
        );
    }
    (
        Verdict::Pass,
        format!(
            "{:+.1}% out-of-sample, Sharpe {:.2}, {:.0}% confidence it isn't luck",
            portfolio.total_return * 100.0,
            portfolio.sharpe,
            deflated * 100.0
        ),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::connectors::Venue;
    use crate::engine::{StrategyState, StrategyKind};

    fn cfg(kind: StrategyKind, universe: &[&str]) -> StrategyConfig {
        StrategyConfig {
            id: "t".into(),
            name: "T".into(),
            kind,
            venue_class: Venue::Crypto,
            state: StrategyState::Paper,
            universe: universe.iter().map(|s| s.to_string()).collect(),
            params: vec![],
            budget_pct: 10.0,
            pnl: 0.0,
            trades: 0,
            win_rate: 0.0,
            max_drawdown: 0.0,
            profit_factor: 0.0,
            equity_curve: vec![0.0],
            rules: None,
        }
    }

    /// Synthetic candles with a constant drift plus noise. `flip_every` reverses
    /// the drift periodically; pass 0 for a series that only ever goes up.
    ///
    /// The distinction matters: a trend follower in a permanent uptrend opens
    /// exactly one position and rides it to the end of the sample, which is
    /// correct behaviour but useless for exercising fold structure.
    fn series(n: usize, seed: u64, drift: f64, flip_every: usize) -> Vec<Ohlc> {
        let mut rng = seed.max(1);
        let mut price = 100.0;
        (0..n)
            .map(|i| {
                rng ^= rng << 13;
                rng ^= rng >> 7;
                rng ^= rng << 17;
                let noise = ((rng >> 11) as f64 / (1u64 << 53) as f64 - 0.5) * 0.02;
                let sign = if flip_every > 0 && (i / flip_every) % 2 == 1 { -1.0 } else { 1.0 };
                let open = price;
                price *= 1.0 + drift * sign + noise;
                Ohlc {
                    ts: i as i64 * 86_400_000,
                    open,
                    high: open.max(price) * 1.004,
                    low: open.min(price) * 0.996,
                    close: price,
                    volume: 1.0,
                }
            })
            .collect()
    }

    fn trending(n: usize, seed: u64) -> Vec<Ohlc> {
        series(n, seed, 0.002, 0)
    }

    fn regime_flipping(n: usize, seed: u64) -> Vec<Ohlc> {
        series(n, seed, 0.003, 150)
    }

    #[test]
    fn only_single_market_technical_rules_are_validatable() {
        assert!(is_validatable(StrategyKind::EmaCross));
        assert!(is_validatable(StrategyKind::Breakout));
        // These need inputs this harness does not have; claiming a verdict on
        // them would be worse than declining to.
        assert!(!is_validatable(StrategyKind::Pairs));
        assert!(!is_validatable(StrategyKind::ProbEdge));
        assert!(!is_validatable(StrategyKind::Composed));
        assert!(!is_validatable(StrategyKind::Manual));
    }

    #[test]
    fn grids_stay_small_because_every_extra_trial_raises_the_bar() {
        for kind in [
            StrategyKind::EmaCross,
            StrategyKind::MultiTf,
            StrategyKind::Bollinger,
            StrategyKind::RsiReversal,
            StrategyKind::Breakout,
        ] {
            let g = param_grid(kind);
            assert!(!g.is_empty());
            assert!(g.len() <= 16, "{kind:?} grid has {} entries", g.len());
        }
    }

    #[test]
    fn a_short_series_yields_no_verdict_rather_than_a_wrong_one() {
        let bars = trending(120, 7);
        let base = cfg(StrategyKind::EmaCross, &["crypto:BTC/USD"]);
        let r = walk_forward(
            &base,
            &[("crypto:BTC/USD".into(), "BTC/USD".into(), bars)],
            &WalkForwardConfig::default(),
        );
        assert_eq!(r.verdict, Verdict::Insufficient);
    }

    #[test]
    fn out_of_sample_windows_never_overlap_their_training_data() {
        let bars = regime_flipping(2000, 11);
        let base = cfg(StrategyKind::EmaCross, &["crypto:BTC/USD"]);
        let wf = WalkForwardConfig { folds: 4, ..Default::default() };
        let (report, _) = walk_forward_market(&base, "crypto:BTC/USD", "BTC/USD", &bars, &wf);

        assert!(!report.folds.is_empty());
        for f in &report.folds {
            assert!(f.oos_end > f.is_end, "an out-of-sample window must come after its fit");
        }
        // Each fold's fit window ends where the previous one's test window did:
        // strictly forward-walking, no reuse of scored data for fitting.
        for pair in report.folds.windows(2) {
            assert!(pair[1].is_end >= pair[0].oos_end);
        }
    }

    #[test]
    fn an_infrequent_trader_is_still_scored_not_reported_as_no_data() {
        // A trend rule with wide ATR stops holds for weeks. On two years of
        // daily bars split into folds, an in-sample window may contain only a
        // couple of trades — which used to disqualify every parameter set,
        // skip every fold, and report "no data" for a strategy that had never
        // actually been tested. Real Kraken history hit this on all five crypto
        // strategies at once.
        let bars = regime_flipping(721, 5); // Kraken's daily cap
        let base = cfg(StrategyKind::EmaCross, &["crypto:BTC/USD"]);
        let wf = WalkForwardConfig { folds: 4, ..Default::default() };
        let (report, _) = walk_forward_market(&base, "crypto:BTC/USD", "BTC/USD", &bars, &wf);

        assert!(
            !report.folds.is_empty(),
            "a 721-bar sample must produce folds; infrequent trading is a result, not an absence of one"
        );
        assert!(report.oos.bars > 0);
    }

    #[test]
    fn a_paused_strategy_is_still_validated() {
        // Several strategies ship paused, and `run_strategy` emits nothing for
        // a paused config — so validating them as-is reported "0 trades" for
        // rules that were never actually asked anything.
        let bars = regime_flipping(1200, 4);
        let base = StrategyConfig {
            state: StrategyState::Paused,
            ..cfg(StrategyKind::EmaCross, &["crypto:BTC/USD"])
        };
        let (report, _) =
            walk_forward_market(&base, "crypto:BTC/USD", "BTC/USD", &bars, &WalkForwardConfig::default());
        assert!(
            report.oos.trades > 0,
            "a paused switch is a runtime state, not an opinion about the rule"
        );
    }

    #[test]
    fn trade_level_stats_survive_fold_aggregation() {
        // Win rate and profit factor cannot be recovered from a per-bar return
        // series; concatenating folds without carrying trade returns reported
        // every strategy as a 0% win rate.
        let markets: Vec<(String, String, Vec<Ohlc>)> = (0..2)
            .map(|i| (format!("crypto:M{i}"), format!("M{i}"), regime_flipping(1500, 31 + i as u64)))
            .collect();
        let base = StrategyConfig {
            universe: markets.iter().map(|(id, _, _)| id.clone()).collect(),
            ..cfg(StrategyKind::EmaCross, &[])
        };
        let r = walk_forward(&base, &markets, &WalkForwardConfig::default());
        assert!(r.portfolio.trades > 0);
        assert!(r.portfolio.win_rate > 0.0, "some trades must have won");
        assert!(r.portfolio.win_rate <= 1.0);
        assert!(r.portfolio.profit_factor > 0.0);
    }

    #[test]
    fn an_unfitted_fold_is_marked_rather_than_hidden() {
        // When nothing traded enough in-sample to choose between, the fold falls
        // back to the shipped defaults — legitimate, but it is not evidence the
        // fitting works, so it has to be visible.
        let bars = regime_flipping(721, 9);
        let base = cfg(StrategyKind::EmaCross, &["crypto:BTC/USD"]);
        let wf = WalkForwardConfig { folds: 4, min_is_trades: 10_000, ..Default::default() };
        let (report, _) = walk_forward_market(&base, "crypto:BTC/USD", "BTC/USD", &bars, &wf);
        assert!(!report.folds.is_empty());
        assert!(
            report.folds.iter().all(|f| !f.fitted),
            "an impossible in-sample gate means every fold used defaults"
        );
    }

    #[test]
    fn a_losing_strategy_is_reported_as_failing() {
        // Mean reversion on a persistent trend is a losing proposition, and the
        // harness has to be willing to say so.
        let markets: Vec<(String, String, Vec<Ohlc>)> = (0..3)
            .map(|i| {
                (format!("crypto:M{i}"), format!("M{i}"), trending(2000, 3 + i as u64))
            })
            .collect();
        let base = cfg(StrategyKind::Bollinger, &["crypto:M0", "crypto:M1", "crypto:M2"]);
        let base = StrategyConfig {
            universe: markets.iter().map(|(id, _, _)| id.clone()).collect(),
            ..base
        };
        let r = walk_forward(&base, &markets, &WalkForwardConfig::default());
        assert!(
            matches!(r.verdict, Verdict::Fail | Verdict::Marginal | Verdict::Insufficient),
            "fading a strong uptrend should not come out a winner: {:?} — {}",
            r.verdict,
            r.reason
        );
    }

    #[test]
    fn deflation_makes_the_verdict_stricter_not_just_decorative() {
        let markets: Vec<(String, String, Vec<Ohlc>)> = (0..3)
            .map(|i| (format!("crypto:M{i}"), format!("M{i}"), trending(2500, 21 + i as u64)))
            .collect();
        let base = StrategyConfig {
            universe: markets.iter().map(|(id, _, _)| id.clone()).collect(),
            ..cfg(StrategyKind::EmaCross, &[])
        };
        let r = walk_forward(&base, &markets, &WalkForwardConfig::default());
        assert!((0.0..=1.0).contains(&r.deflated_sharpe));
        assert!(r.trials > 1, "a single trial would make deflation meaningless");
        // A Pass is only allowed to be issued with the confidence to back it.
        if r.verdict == Verdict::Pass {
            assert!(r.deflated_sharpe >= 0.95);
        }
    }
}
