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
    /// Mean in-sample Sharpe of the parameters each fitted fold chose: what
    /// the fitting saw. Unfitted folds are left out, they chose nothing.
    pub is_sharpe: f64,
    /// Out-of-sample Sharpe over in-sample Sharpe. Below 0.5 the fitted
    /// parameters are mostly noise (`PROFIT-PLAN.md` §2). `None` when the
    /// in-sample Sharpe was not positive, which makes a ratio meaningless.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub oos_is_ratio: Option<f64>,
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

pub fn with_params(base: &StrategyConfig, params: &[(String, f64)]) -> StrategyConfig {
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
    let mut fitted_is_sharpes: Vec<f64> = Vec::new();
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
            if fitted {
                fitted_is_sharpes.push(is_sharpe);
            } else {
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
    let deflated = metrics::deflated_sharpe_annualised(
        portfolio.sharpe,
        wf.bt.bars_per_year,
        portfolio.bars,
        portfolio.skew,
        portfolio.kurtosis,
        trials.max(1),
        trial_var,
    );
    let is_sharpe = metrics::mean(&fitted_is_sharpes);
    let oos_is_ratio = (is_sharpe > 0.0 && !fitted_is_sharpes.is_empty()).then(|| portfolio.sharpe / is_sharpe);

    let (verdict, reason) = judge(&portfolio, deflated, wf.min_trades, folds_run);

    StrategyReport {
        strategy_id: base.id.clone(),
        name: base.name.clone(),
        kind: base.kind,
        markets: reports,
        portfolio,
        trials,
        is_sharpe,
        oos_is_ratio,
        deflated_sharpe: deflated,
        verdict,
        reason,
        folds_run,
        folds_unfitted,
    }
}

/// A universe of daily candles, as `(market id, symbol, bars)`.
pub type Universe = Vec<(String, String, Vec<Ohlc>)>;

/// Align every market on its most recent `len` bars, `len` being the shortest
/// series, so a portfolio is pooled over one common window.
pub fn align(markets: &[(String, String, Vec<Ohlc>)]) -> Vec<(&str, &str, &[Ohlc])> {
    let len = markets.iter().map(|(_, _, b)| b.len()).min().unwrap_or(0);
    markets.iter().map(|(id, sym, bars)| (id.as_str(), sym.as_str(), &bars[bars.len() - len..])).collect()
}

/// One configuration run over a set of market windows, pooled equal-weight.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Pooled {
    pub stats: Stats,
    pub pnl: crate::costs::PnlBreakdown,
    /// Pooled per-bar net returns.
    #[serde(skip)]
    pub returns: Vec<f64>,
    /// Pooled per-bar returns with no costs.
    #[serde(skip)]
    pub gross_returns: Vec<f64>,
    /// Index into each input window of the decision bar behind `returns[0]`.
    #[serde(skip)]
    pub first_bar: usize,
}

/// Run one configuration over several windows and pool the results.
pub fn run_pooled(cfg: &StrategyConfig, windows: &[(&str, &str, &[Ohlc])], bt: &BacktestConfig) -> Pooled {
    let mut net = Vec::with_capacity(windows.len());
    let mut gross = Vec::with_capacity(windows.len());
    let mut trades: Vec<f64> = Vec::new();
    let mut first_bar = 0;
    for (id, sym, bars) in windows {
        let r = backtest::run(cfg, id, sym, bars, bt);
        trades.extend(r.trades.iter().map(|t| t.ret));
        first_bar = r.first_bar;
        net.push(r.bar_returns);
        gross.push(r.gross_bar_returns);
    }
    let returns = pool(&net);
    let gross_returns = pool(&gross);
    let stats = stats_from_returns(&returns, &trades, bt.bars_per_year);
    let compound = |xs: &[f64]| xs.iter().fold(1.0, |e, r| e * (1.0 + r)) - 1.0;
    let (g, n) = (compound(&gross_returns), compound(&returns));
    Pooled {
        stats,
        pnl: crate::costs::PnlBreakdown::new(g, g - n),
        returns,
        gross_returns,
        first_bar,
    }
}

/// The backtest settings a strategy is judged with: its venue's costs and its
/// market's calendar.
pub fn bt_for(cfg: &StrategyConfig, crypto: crate::costs::CostVenue, regime_filter: bool) -> BacktestConfig {
    let equity = cfg.venue_class == crate::connectors::Venue::Alpaca;
    BacktestConfig {
        venue: crate::costs::CostVenue::for_venue(cfg.venue_class, Some(crypto)),
        // Daily bars: 365 for crypto (always open), 252 sessions for equities.
        bars_per_year: if equity { 252.0 } else { 365.0 },
        regime_filter,
        ..BacktestConfig::default()
    }
}

/// Daily candles for a strategy's own universe: Kraken for crypto (no keys
/// needed), Alpaca for equities (`alpaca` = key id, secret, feed).
pub async fn fetch_daily_universe(
    cfg: &StrategyConfig,
    alpaca: Option<(String, String, String)>,
) -> Result<Universe, String> {
    let equity = cfg.venue_class == crate::connectors::Venue::Alpaca;
    let (series, prefix) = if equity {
        let Some((key, secret, feed)) = alpaca else {
            return Err("no equity candles: Alpaca keys are needed to fetch daily history".into());
        };
        // About four years of sessions; Alpaca returns what the plan covers.
        (crate::marketdata::fetch_alpaca_bars(&key, &secret, &feed, "1Day", 1460).await, "alpaca:")
    } else {
        (crate::marketdata::fetch_kraken_bars(1440).await, "crypto:")
    };
    let out: Universe = series
        .into_iter()
        .filter(|s| cfg.universe.contains(&s.id))
        .map(|s| {
            let symbol = s.id.trim_start_matches(prefix).to_string();
            (s.id, symbol, s.bars)
        })
        .collect();
    if out.is_empty() {
        Err(format!("no daily candles for {}'s universe", cfg.name))
    } else {
        Ok(out)
    }
}

// ── the parameter sweep behind the Optimizer page ───────────────────────────

/// One window's headline numbers.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WindowSummary {
    pub sharpe: f64,
    pub total_return: f64,
    pub max_drawdown: f64,
    pub trades: usize,
    pub bars: usize,
    pub pnl: crate::costs::PnlBreakdown,
}

impl From<&Pooled> for WindowSummary {
    fn from(p: &Pooled) -> Self {
        WindowSummary {
            sharpe: p.stats.sharpe,
            total_return: p.stats.total_return,
            max_drawdown: p.stats.max_drawdown,
            trades: p.stats.trades,
            bars: p.stats.bars,
            pnl: p.pnl,
        }
    }
}

/// One parameter set in the sweep.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SweepRow {
    pub params: Vec<(String, f64)>,
    /// The fitting window: the first part of the history.
    pub is: WindowSummary,
    /// The hold-out: everything after it, never seen by the ranking.
    pub oos: WindowSummary,
    /// Out-of-sample Sharpe over in-sample Sharpe; `None` when in-sample was
    /// not positive.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub oos_is_ratio: Option<f64>,
    /// Probability the in-sample Sharpe reflects edge rather than being the
    /// best of `trials` attempts ([`metrics::deflated_sharpe_annualised`]).
    pub deflated_sharpe: f64,
    /// `1 - deflated_sharpe`: below 0.05 is the usual significance bar.
    pub p_value: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SweepReport {
    pub strategy_id: String,
    pub name: String,
    /// Configurations tried. Every one of them raises the bar for the others.
    pub trials: usize,
    /// Share of the history used for fitting.
    pub is_fraction: f64,
    pub markets: usize,
    pub cost_venue: crate::costs::CostVenue,
    /// Ranked by in-sample Sharpe, which is how a naive optimizer would pick.
    pub rows: Vec<SweepRow>,
}

/// Sweep a strategy's parameter grid on real candles: fit on the first
/// `is_fraction` of the history, hold out the rest, and deflate every
/// in-sample Sharpe for the number of configurations tried.
///
/// The rows are ranked by in-sample Sharpe on purpose. That is the ranking an
/// optimizer without deflation shows, and next to it the deflated Sharpe and
/// the out-of-sample/in-sample ratio say how much of it to believe.
pub fn sweep(base: &StrategyConfig, markets: &[(String, String, Vec<Ohlc>)], bt: &BacktestConfig, is_fraction: f64) -> SweepReport {
    let aligned = align(markets);
    let len = aligned.first().map(|(_, _, b)| b.len()).unwrap_or(0);
    let split = ((len as f64) * is_fraction.clamp(0.2, 0.9)) as usize;
    let lead = split.saturating_sub(WARMUP);
    let is_windows: Vec<(&str, &str, &[Ohlc])> = aligned.iter().map(|(i, s, b)| (*i, *s, &b[..split])).collect();
    let oos_windows: Vec<(&str, &str, &[Ohlc])> = aligned.iter().map(|(i, s, b)| (*i, *s, &b[lead..])).collect();

    let grid = param_grid(base.kind);
    let runs: Vec<(Vec<(String, f64)>, Pooled, Pooled)> = grid
        .iter()
        .map(|params| {
            let cfg = with_params(base, params);
            (params.clone(), run_pooled(&cfg, &is_windows, bt), run_pooled(&cfg, &oos_windows, bt))
        })
        .collect();

    let trials = runs.len().max(1);
    let is_sharpes: Vec<f64> = runs.iter().map(|(_, is, _)| is.stats.sharpe).collect();
    let trial_var = metrics::stdev(&is_sharpes).powi(2);
    let mut rows: Vec<SweepRow> = runs
        .iter()
        .map(|(params, is, oos)| {
            let dsr = metrics::deflated_sharpe_annualised(
                is.stats.sharpe,
                bt.bars_per_year,
                is.stats.bars,
                is.stats.skew,
                is.stats.kurtosis,
                trials,
                trial_var,
            );
            SweepRow {
                params: params.clone(),
                is: is.into(),
                oos: oos.into(),
                oos_is_ratio: (is.stats.sharpe > 0.0).then(|| oos.stats.sharpe / is.stats.sharpe),
                deflated_sharpe: dsr,
                p_value: 1.0 - dsr,
            }
        })
        .collect();
    rows.sort_by(|a, b| b.is.sharpe.partial_cmp(&a.is.sharpe).unwrap_or(std::cmp::Ordering::Equal));

    SweepReport {
        strategy_id: base.id.clone(),
        name: base.name.clone(),
        trials,
        is_fraction: is_fraction.clamp(0.2, 0.9),
        markets: aligned.len(),
        cost_venue: bt.venue,
        rows,
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
            ledger: Default::default(),
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

    fn universe(n: usize, seeds: &[u64], gen: fn(usize, u64) -> Vec<Ohlc>) -> Vec<(String, String, Vec<Ohlc>)> {
        seeds.iter().map(|s| (format!("crypto:M{s}"), format!("M{s}"), gen(n, *s))).collect()
    }

    fn noise(n: usize, seed: u64) -> Vec<Ohlc> {
        series(n, seed, 0.0, 0)
    }

    #[test]
    fn the_sweep_ranks_by_in_sample_and_deflates_every_row() {
        let markets = universe(900, &[3, 4, 5], regime_flipping);
        let base = StrategyConfig {
            universe: markets.iter().map(|(id, _, _)| id.clone()).collect(),
            ..cfg(StrategyKind::EmaCross, &[])
        };
        let r = sweep(&base, &markets, &BacktestConfig::default(), 0.6);
        assert_eq!(r.trials, param_grid(StrategyKind::EmaCross).len());
        assert_eq!(r.rows.len(), r.trials);
        assert_eq!(r.markets, 3);
        for pair in r.rows.windows(2) {
            assert!(pair[0].is.sharpe >= pair[1].is.sharpe, "ranked by in-sample Sharpe");
        }
        for row in &r.rows {
            assert!((0.0..=1.0).contains(&row.deflated_sharpe));
            assert!((row.p_value - (1.0 - row.deflated_sharpe)).abs() < 1e-12);
            assert!(row.is.bars > 0 && row.oos.bars > 0);
            assert!((row.is.pnl.gross - row.is.pnl.costs - row.is.pnl.net).abs() < 1e-9);
            if row.is.sharpe <= 0.0 {
                assert!(row.oos_is_ratio.is_none(), "no ratio against a non-positive in-sample Sharpe");
            }
        }
        // Deflation can only lower confidence relative to an undeflated test.
        let top = &r.rows[0];
        let undeflated = metrics::deflated_sharpe_annualised(top.is.sharpe, 365.0, top.is.bars, 0.0, 3.0, 1, 0.0);
        assert!(top.deflated_sharpe <= undeflated + 0.05);
    }

    #[test]
    fn the_best_of_a_sweep_over_noise_is_not_significant() {
        // Pure random walks: whatever ranks first in-sample got lucky.
        for seed in [11u64, 23, 37] {
            let markets = universe(900, &[seed, seed + 1, seed + 2], noise);
            let base = StrategyConfig {
                universe: markets.iter().map(|(id, _, _)| id.clone()).collect(),
                ..cfg(StrategyKind::EmaCross, &[])
            };
            let r = sweep(&base, &markets, &BacktestConfig::default(), 0.6);
            assert!(
                r.rows[0].p_value > 0.05,
                "seed {seed}: the luckiest of {} configurations on noise must not look significant (p = {:.3})",
                r.trials,
                r.rows[0].p_value
            );
        }
    }

    #[test]
    fn walk_forward_reports_an_oos_to_is_ratio() {
        let markets = universe(1500, &[31, 32], regime_flipping);
        let base = StrategyConfig {
            universe: markets.iter().map(|(id, _, _)| id.clone()).collect(),
            ..cfg(StrategyKind::EmaCross, &[])
        };
        let r = walk_forward(&base, &markets, &WalkForwardConfig::default());
        match r.oos_is_ratio {
            Some(x) => {
                assert!(r.is_sharpe > 0.0);
                assert!((x - r.portfolio.sharpe / r.is_sharpe).abs() < 1e-9);
            }
            None => assert!(r.is_sharpe <= 0.0),
        }
        let v = serde_json::to_value(&r).unwrap();
        assert!(v.get("isSharpe").is_some(), "camelCase on the wire");
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
