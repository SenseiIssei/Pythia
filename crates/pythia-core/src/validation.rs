//! The validation gates: how a strategy earns real money.
//!
//! `PROFIT-PLAN.md` §2 lists eight gates a strategy must pass, in order, before
//! it may trade live. An optimizer without them is a machine for manufacturing
//! overfit, so they are code, not advice, and the engine refuses to set a
//! strategy to Live until gates 1 to 7 pass.
//!
//! | # | gate | judged on | passes when |
//! |---|---|---|---|
//! | 1 | In-sample | net return of the configured parameters on the first 60 % of history | net > 0 |
//! | 2 | Walk-forward | out-of-sample Sharpe / in-sample Sharpe of the walk-forward fit | ratio >= 0.5 |
//! | 3 | Cost sensitivity | net return on the whole history at 1x, 2x and 3x the cost model | net at 2x > 0 |
//! | 4 | Parameter plateau | share of neighbouring parameter sets net-positive in-sample | share >= 60 % |
//! | 5 | Regime split | net return in trending/ranging and high/low-volatility bars | profitable in both halves of each split, unless a regime filter is on |
//! | 6 | Deflated Sharpe | p = 1 - deflated Sharpe of the walk-forward result | p < 0.05 |
//! | 7 | Paper forward test | trading days and closed trades on real prices | >= 30 days and >= 30 trades |
//! | 8 | Live at minimum size | closed live trades and realised vs modelled slippage | >= 30 trades, slippage within 1.5x |
//!
//! Each gate returns pass, fail or pending, a plain reason, and the number it
//! was judged on. Pending means "no claim either way yet": too little history,
//! too few trades, or not checked. Pending blocks live exactly like a fail does.
//!
//! Gates 1 to 6 need candle history and a few hundred backtests, so they are
//! computed on request ([`research_gates`]) and cached by the engine against the
//! parameters they were run with. Gates 7 and 8 are read from the engine's own
//! running record every time the passport is built ([`passport`]).
//!
//! ## Two definitions worth stating
//!
//! **Plateau (gate 4).** For every tunable parameter, the neighbourhood is one
//! grid step either side: the adjacent values on that parameter's axis of the
//! research grid ([`crate::research::param_grid`]) when the configured value is
//! on the axis, otherwise the value plus or minus the axis's median spacing,
//! and for a parameter the grid does not cover, plus or minus 10 % of the value
//! (at least one step of its slider). Every combination of {down, same, up}
//! across the parameters, minus the configured point itself, is a neighbour:
//! 8 for two parameters, 26 for three. Values are clamped to the parameter's
//! own range. At least 60 % of the neighbours must be net-positive on the
//! in-sample window. A lone profitable spike in the parameter surface is an
//! overfit, not a discovery.
//!
//! **Regimes (gate 5).** Every bar is labelled at decision time with the same
//! rules the engine uses: trending when the 20-bar Kaufman efficiency ratio is
//! at least 0.4, ranging otherwise; high volatility when the 20-bar realised
//! volatility is above that market's median over the sample, low otherwise.
//! Each bar's return is credited to its regimes. Without a regime filter the
//! strategy must be net-positive in both halves of both splits. With the
//! engine's regime filter on, a trend/range regime it barely trades in (under
//! 5 % of its exposure) is ignored, because the filter is part of the strategy
//! and was not chosen after seeing the answer. The volatility split has no
//! filter, so it always needs both halves.

use crate::engine::indicators as ind;
use crate::engine::{StrategyConfig, StrategyParam};
use crate::execution::bandit::SlippageRow;
use crate::marketdata::Ohlc;
use crate::research::backtest::{self, BacktestConfig};
use crate::research::{self, StrategyReport, WalkForwardConfig};
use serde::{Deserialize, Serialize};

/// Share of history the in-sample gates fit and judge on.
pub const IN_SAMPLE_FRACTION: f64 = 0.6;
/// Gate 2's bar: out-of-sample Sharpe at least half the in-sample one.
pub const MIN_OOS_IS_RATIO: f64 = 0.5;
/// Gate 4's bar: share of neighbouring parameter sets that must be net-positive.
pub const MIN_PLATEAU_SHARE: f64 = 0.6;
/// Gate 6's bar.
pub const MAX_P_VALUE: f64 = 0.05;
/// Gate 7's bars.
pub const MIN_FORWARD_DAYS: u32 = 30;
pub const MIN_FORWARD_TRADES: u32 = 30;
/// Gate 8's bars.
pub const MIN_LIVE_TRADES: u32 = 30;
/// Realised slippage above this multiple of the model fails gates 7 and 8
/// (`PROFIT-PLAN.md` §8: "realised slippage within 1.5x of modelled").
pub const MAX_SLIPPAGE_RATIO: f64 = 1.5;
/// A trend/range regime holding less than this share of a filtered strategy's
/// exposure is not judged.
const MIN_REGIME_EXPOSURE: f64 = 0.05;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum GateStatus {
    Pass,
    Fail,
    /// Not enough evidence for a claim either way, or not checked yet.
    Pending,
}

/// A labelled number shown under a gate (e.g. "2x costs: -3.1 %").
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Figure {
    pub label: String,
    pub value: f64,
}

fn fig(label: &str, value: f64) -> Figure {
    Figure { label: label.to_string(), value }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Gate {
    /// 1 to 8, in the order of `PROFIT-PLAN.md` §2.
    pub id: u8,
    pub name: String,
    pub status: GateStatus,
    /// Plain language: why it passed, failed or is pending.
    pub reason: String,
    /// The number the gate was judged on.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<f64>,
    /// What `value` is, e.g. "net return" or "p-value".
    pub measure: String,
    /// Supporting numbers.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub figures: Vec<Figure>,
}

pub const GATE_NAMES: [&str; 8] = [
    "In-sample",
    "Walk-forward",
    "Cost sensitivity",
    "Parameter plateau",
    "Regime split",
    "Deflated Sharpe",
    "Paper forward test",
    "Live at minimum size",
];

const MEASURES: [&str; 8] = [
    "net return, first 60 %",
    "OOS / IS Sharpe",
    "net return at 2x costs",
    "share of neighbours net-positive",
    "regimes net-positive (of 4)",
    "p-value",
    "closed trades on real prices",
    "closed live trades",
];

impl Gate {
    fn new(id: u8, status: GateStatus, reason: impl Into<String>, value: Option<f64>) -> Gate {
        Gate {
            id,
            name: GATE_NAMES[(id - 1) as usize].to_string(),
            status,
            reason: reason.into(),
            value,
            measure: MEASURES[(id - 1) as usize].to_string(),
            figures: Vec::new(),
        }
    }

    fn with(mut self, figures: Vec<Figure>) -> Gate {
        self.figures = figures;
        self
    }

    pub fn passed(&self) -> bool {
        self.status == GateStatus::Pass
    }
}

fn pct(x: f64) -> String {
    format!("{:+.1}%", x * 100.0)
}

// ── the judges: pure functions of numbers, one per gate ─────────────────────

/// Gate 1. `net` is the in-sample net return as a fraction.
pub fn judge_in_sample(net: f64, trades: usize, bars: usize) -> Gate {
    if bars == 0 {
        return Gate::new(1, GateStatus::Pending, "not enough history to fit on", None);
    }
    if trades == 0 {
        return Gate::new(1, GateStatus::Fail, "made no trades in-sample, so there is no result to build on", Some(0.0));
    }
    if net > 0.0 {
        Gate::new(1, GateStatus::Pass, format!("{} after costs over {trades} trades in the first 60 % of history", pct(net)), Some(net))
    } else {
        Gate::new(
            1,
            GateStatus::Fail,
            format!("lost money after costs on the very data it was fitted to ({} over {trades} trades)", pct(net)),
            Some(net),
        )
    }
}

/// Gate 2, from a walk-forward report.
pub fn judge_walk_forward(r: &StrategyReport, min_trades: usize) -> Gate {
    if r.folds_run == 0 {
        return Gate::new(2, GateStatus::Pending, "history too short to split into walk-forward folds", None);
    }
    if r.portfolio.trades < min_trades {
        return Gate::new(
            2,
            GateStatus::Pending,
            format!("only {} out-of-sample trades; at least {min_trades} are needed for a ratio worth reading", r.portfolio.trades),
            r.oos_is_ratio,
        );
    }
    let figures = vec![fig("in-sample Sharpe", r.is_sharpe), fig("out-of-sample Sharpe", r.portfolio.sharpe)];
    match r.oos_is_ratio {
        None => Gate::new(2, GateStatus::Fail, "the fitted parameters did not even have a positive Sharpe in-sample", None)
            .with(figures),
        Some(x) if x >= MIN_OOS_IS_RATIO => Gate::new(
            2,
            GateStatus::Pass,
            format!("out-of-sample kept {:.0}% of the in-sample Sharpe", x * 100.0),
            Some(x),
        )
        .with(figures),
        Some(x) => Gate::new(
            2,
            GateStatus::Fail,
            format!(
                "out-of-sample kept only {:.0}% of the in-sample Sharpe; below {:.0}% the parameters are mostly noise",
                x * 100.0,
                MIN_OOS_IS_RATIO * 100.0
            ),
            Some(x),
        )
        .with(figures),
    }
}

/// Gate 3. `nets` is the net return at 1x, 2x and 3x the cost model.
pub fn judge_costs(nets: [f64; 3], trades: usize) -> Gate {
    let figures = vec![fig("1x costs", nets[0]), fig("2x costs", nets[1]), fig("3x costs", nets[2])];
    if trades == 0 {
        return Gate::new(3, GateStatus::Fail, "made no trades, so there is nothing for costs to test", Some(0.0)).with(figures);
    }
    if nets[1] > 0.0 {
        let tail = if nets[2] > 0.0 { " and at 3x" } else { ", though not at 3x" };
        Gate::new(3, GateStatus::Pass, format!("still positive at double the modelled costs ({}){tail}", pct(nets[1])), Some(nets[1]))
            .with(figures)
    } else if nets[0] > 0.0 {
        Gate::new(
            3,
            GateStatus::Fail,
            format!(
                "profitable at modelled costs ({}) but not at double ({}); if 2x costs kill it, live will",
                pct(nets[0]),
                pct(nets[1])
            ),
            Some(nets[1]),
        )
        .with(figures)
    } else {
        Gate::new(3, GateStatus::Fail, format!("loses money even at modelled costs ({})", pct(nets[0])), Some(nets[1])).with(figures)
    }
}

/// Gate 4. `neighbour_nets` are the in-sample net returns of the neighbours.
pub fn judge_plateau(neighbour_nets: &[f64], tunable: usize) -> Gate {
    if tunable == 0 {
        return Gate::new(4, GateStatus::Pass, "no tunable parameters, so there is no peak to have overfit", None);
    }
    if neighbour_nets.is_empty() {
        return Gate::new(4, GateStatus::Pending, "no neighbouring parameter sets could be formed", None);
    }
    let n = neighbour_nets.len();
    let pos = neighbour_nets.iter().filter(|x| **x > 0.0).count();
    let share = pos as f64 / n as f64;
    let figures = vec![fig("neighbours", n as f64), fig("net-positive", pos as f64)];
    if share >= MIN_PLATEAU_SHARE {
        Gate::new(4, GateStatus::Pass, format!("{pos} of {n} neighbouring parameter sets are also profitable: a plateau"), Some(share))
            .with(figures)
    } else {
        Gate::new(
            4,
            GateStatus::Fail,
            format!(
                "only {pos} of {n} neighbouring parameter sets are profitable; a lone peak is an overfit, not a discovery"
            ),
            Some(share),
        )
        .with(figures)
    }
}

/// Net return and exposure in one regime.
#[derive(Debug, Clone, Copy, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RegimeResult {
    pub net: f64,
    /// Bars with a position open.
    pub exposure: usize,
}

/// The four regime buckets of gate 5.
#[derive(Debug, Clone, Copy, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RegimeSplit {
    pub trending: RegimeResult,
    pub ranging: RegimeResult,
    pub high_vol: RegimeResult,
    pub low_vol: RegimeResult,
}

/// Gate 5.
pub fn judge_regimes(s: &RegimeSplit, regime_filter: bool) -> Gate {
    let figures = vec![
        fig("trending", s.trending.net),
        fig("ranging", s.ranging.net),
        fig("high volatility", s.high_vol.net),
        fig("low volatility", s.low_vol.net),
    ];
    let all = [s.trending, s.ranging, s.high_vol, s.low_vol];
    let count = all.iter().filter(|r| r.net > 0.0).count() as f64;
    let exposure = s.trending.exposure + s.ranging.exposure;
    if exposure == 0 {
        return Gate::new(5, GateStatus::Fail, "never held a position, so it is profitable in no regime", Some(0.0)).with(figures);
    }
    let judged = |r: &RegimeResult| -> bool {
        // The engine's regime filter decides trend/range participation by
        // design; a regime it barely trades in is the filter working.
        !(regime_filter && (r.exposure as f64) < MIN_REGIME_EXPOSURE * exposure as f64)
    };
    let mut failing: Vec<&str> = Vec::new();
    for (name, r) in [("trending", &s.trending), ("ranging", &s.ranging)] {
        if judged(r) && r.net <= 0.0 {
            failing.push(name);
        }
    }
    for (name, r) in [("high-volatility", &s.high_vol), ("low-volatility", &s.low_vol)] {
        if r.net <= 0.0 {
            failing.push(name);
        }
    }
    if failing.is_empty() {
        let note = if regime_filter { " (the regime filter decides where it trades)" } else { "" };
        return Gate::new(5, GateStatus::Pass, format!("net-positive in every regime it trades in{note}"), Some(count)).with(figures);
    }
    let hint = if regime_filter {
        ""
    } else {
        "; a strategy that works in one regime only needs a regime filter that was part of it from the start"
    };
    Gate::new(5, GateStatus::Fail, format!("loses money in {} markets{hint}", join_and(&failing)), Some(count)).with(figures)
}

/// "a", "a and b", "a, b and c".
fn join_and(items: &[&str]) -> String {
    match items {
        [] => String::new(),
        [one] => one.to_string(),
        [rest @ .., last] => format!("{} and {last}", rest.join(", ")),
    }
}

/// Gate 6, from a walk-forward report.
pub fn judge_deflated(r: &StrategyReport, min_trades: usize) -> Gate {
    if r.folds_run == 0 || r.portfolio.trades < min_trades {
        return Gate::new(
            6,
            GateStatus::Pending,
            format!("only {} out-of-sample trades: too few to test for significance", r.portfolio.trades),
            None,
        );
    }
    let p = (1.0 - r.deflated_sharpe).clamp(0.0, 1.0);
    let figures = vec![fig("deflated Sharpe", r.deflated_sharpe), fig("configurations tried", r.trials as f64)];
    if p < MAX_P_VALUE {
        Gate::new(
            6,
            GateStatus::Pass,
            format!("p = {p:.3}: unlikely to be the luckiest of {} tries", r.trials),
            Some(p),
        )
        .with(figures)
    } else {
        Gate::new(
            6,
            GateStatus::Fail,
            format!("p = {p:.3}: not distinguishable from the best of {} tries on noise", r.trials),
            Some(p),
        )
        .with(figures)
    }
}

/// What the engine knows about a strategy's paper forward test.
#[derive(Debug, Clone, Default)]
pub struct ForwardRecord {
    pub paper_since: Option<i64>,
    /// Closed paper trades on real prices.
    pub trades: u32,
    /// Equities count weekdays; crypto trades every day.
    pub equities: bool,
    pub now: i64,
    /// Realised against modelled slippage on this strategy's venue, if any.
    pub slippage: Option<SlippageRow>,
}

/// Trading days between two instants: calendar days for crypto, weekdays for
/// equities (holidays are not modelled; they would only make it stricter).
pub fn trading_days(since: i64, now: i64, equities: bool) -> u32 {
    if now <= since {
        return 0;
    }
    const DAY: i64 = 86_400_000;
    let days = ((now - since) / DAY) as u32;
    if !equities {
        return days;
    }
    use chrono::{Datelike, TimeZone, Weekday};
    let Some(start) = chrono::Utc.timestamp_millis_opt(since).single() else { return 0 };
    (1..=days)
        .filter(|d| {
            let wd = (start + chrono::Duration::days(*d as i64)).weekday();
            !matches!(wd, Weekday::Sat | Weekday::Sun)
        })
        .count() as u32
}

fn slippage_failure(s: &Option<SlippageRow>) -> Option<String> {
    let s = s.as_ref()?;
    let ratio = s.ratio?;
    (s.enough && ratio > MAX_SLIPPAGE_RATIO).then(|| {
        format!(
            "real fills on {} cost {ratio:.1}x what the cost model assumes ({:.1} vs {:.1} bps); recalibrate config/costs.json and re-run the checks",
            s.venue, s.median_realised_bps, s.median_modelled_bps
        )
    })
}

/// Gate 7.
pub fn judge_forward(f: &ForwardRecord) -> Gate {
    let Some(since) = f.paper_since else {
        return Gate::new(7, GateStatus::Pending, "not running in paper yet; the forward test starts when it does", Some(0.0));
    };
    let days = trading_days(since, f.now, f.equities);
    let figures = vec![fig("trading days", days as f64), fig("trades", f.trades as f64)];
    if let Some(why) = slippage_failure(&f.slippage) {
        return Gate::new(7, GateStatus::Fail, why, Some(f.trades as f64)).with(figures);
    }
    if days >= MIN_FORWARD_DAYS && f.trades >= MIN_FORWARD_TRADES {
        Gate::new(7, GateStatus::Pass, format!("{days} trading days and {} trades on live prices", f.trades), Some(f.trades as f64))
            .with(figures)
    } else {
        Gate::new(
            7,
            GateStatus::Pending,
            format!(
                "{days} of {MIN_FORWARD_DAYS} trading days and {} of {MIN_FORWARD_TRADES} trades on live prices so far",
                f.trades
            ),
            Some(f.trades as f64),
        )
        .with(figures)
    }
}

/// What the engine knows about a strategy's live trading.
#[derive(Debug, Clone, Default)]
pub struct LiveRecord {
    pub trades: u32,
    pub slippage: Option<SlippageRow>,
}

/// Gate 8. Pending until there is live data; it is the one gate a strategy
/// earns while live, so it never blocks arming.
pub fn judge_live(l: &LiveRecord) -> Gate {
    let figures = vec![fig("live trades", l.trades as f64)];
    if l.trades == 0 {
        return Gate::new(8, GateStatus::Pending, "no live trades yet; this gate is earned at minimum size after arming", Some(0.0));
    }
    if let Some(why) = slippage_failure(&l.slippage) {
        return Gate::new(8, GateStatus::Fail, why, Some(l.trades as f64)).with(figures);
    }
    if l.trades < MIN_LIVE_TRADES {
        return Gate::new(
            8,
            GateStatus::Pending,
            format!("{} of {MIN_LIVE_TRADES} live trades at minimum size", l.trades),
            Some(l.trades as f64),
        )
        .with(figures);
    }
    match l.slippage.as_ref().filter(|s| s.enough).and_then(|s| s.ratio) {
        Some(ratio) => Gate::new(
            8,
            GateStatus::Pass,
            format!("{} live trades, real fills within {ratio:.1}x of the cost model", l.trades),
            Some(l.trades as f64),
        )
        .with(figures),
        None => Gate::new(
            8,
            GateStatus::Pending,
            "enough live trades, but not yet enough fills to compare slippage against the model",
            Some(l.trades as f64),
        )
        .with(figures),
    }
}

// ── the research half: gates 1 to 6 on candle history ───────────────────────

/// Gates 1 to 6 for one strategy, cached by the engine against the parameters
/// they were computed with.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchVerdict {
    pub strategy_id: String,
    /// The parameters these gates judged. A change invalidates them.
    pub params: Vec<(String, f64)>,
    pub checked_at: i64,
    pub markets: usize,
    pub bars: usize,
    pub cost_venue: crate::costs::CostVenue,
    pub gates: Vec<Gate>,
}

fn params_of(cfg: &StrategyConfig) -> Vec<(String, f64)> {
    cfg.params.iter().map(|p| (p.key.clone(), p.value)).collect()
}

/// Run gates 1 to 6 on a universe of candles.
pub fn research_gates(
    base: &StrategyConfig,
    markets: &[(String, String, Vec<Ohlc>)],
    bt: &BacktestConfig,
    wf: &WalkForwardConfig,
    now: i64,
) -> ResearchVerdict {
    let aligned = research::align(markets);
    let len = aligned.first().map(|(_, _, b)| b.len()).unwrap_or(0);
    let verdict = |gates: Vec<Gate>| ResearchVerdict {
        strategy_id: base.id.clone(),
        params: params_of(base),
        checked_at: now,
        markets: aligned.len(),
        bars: len,
        cost_venue: bt.venue,
        gates,
    };
    if !research::is_validatable(base.kind) {
        let why = "this kind of strategy needs inputs single-market candles cannot provide (two legs, prediction odds, \
                   or a human), so it cannot be validated here";
        return verdict((1..=6).map(|id| Gate::new(id, GateStatus::Pending, why, None)).collect());
    }
    let split = (len as f64 * IN_SAMPLE_FRACTION) as usize;
    if aligned.is_empty() || split <= backtest::WARMUP + 20 {
        let why = format!("{len} bars of history is too short to judge; at least {} are needed", (backtest::WARMUP + 21) * 2);
        return verdict((1..=6).map(|id| Gate::new(id, GateStatus::Pending, why.clone(), None)).collect());
    }
    // The configured parameters as they would trade, but scored whatever the
    // strategy's current on/off switch says.
    let cfg = research::with_params(base, &params_of(base));
    let is_windows: Vec<(&str, &str, &[Ohlc])> = aligned.iter().map(|(i, s, b)| (*i, *s, &b[..split])).collect();

    // 1 · in-sample
    let is_run = research::run_pooled(&cfg, &is_windows, bt);
    let g1 = judge_in_sample(is_run.pnl.net, is_run.stats.trades, is_run.stats.bars);

    // 2 and 6 · walk-forward, with its deflated Sharpe
    let report = research::walk_forward(base, markets, &WalkForwardConfig { bt: *bt, ..*wf });
    let g2 = judge_walk_forward(&report, wf.min_trades);
    let g6 = judge_deflated(&report, wf.min_trades);

    // 3 · cost sensitivity on the whole history
    let nets = [1.0, 2.0, 3.0].map(|k| research::run_pooled(&cfg, &aligned, &BacktestConfig { cost_mult: bt.cost_mult * k, ..*bt }));
    let g3 = judge_costs([nets[0].pnl.net, nets[1].pnl.net, nets[2].pnl.net], nets[0].stats.trades);

    // 4 · parameter plateau, in-sample
    let (neighbours, tunable) = neighbourhood(base);
    let neighbour_nets: Vec<f64> = neighbours
        .iter()
        .map(|p| research::run_pooled(&research::with_params(base, p), &is_windows, bt).pnl.net)
        .collect();
    let mut g4 = judge_plateau(&neighbour_nets, tunable);
    if g4.status != GateStatus::Pending && tunable > 0 {
        g4.figures.push(fig("configured in-sample", is_run.pnl.net));
    }

    // 5 · regime split on the whole history
    let split5 = regime_split(&cfg, &aligned, bt);
    let g5 = judge_regimes(&split5, bt.regime_filter);

    verdict(vec![g1, g2, g3, g4, g5, g6])
}

/// The neighbouring parameter sets of gate 4, and how many parameters are
/// tunable. See the module docs for the definition.
pub fn neighbourhood(cfg: &StrategyConfig) -> (Vec<Vec<(String, f64)>>, usize) {
    let grid = research::param_grid(cfg.kind);
    let tunable: Vec<&StrategyParam> = cfg.params.iter().collect();
    if tunable.is_empty() {
        return (Vec::new(), 0);
    }
    // Per parameter: the values one step down and one step up.
    let steps: Vec<(f64, f64)> = tunable
        .iter()
        .map(|p| {
            let mut axis: Vec<f64> =
                grid.iter().flat_map(|set| set.iter().filter(|(k, _)| k == &p.key).map(|(_, v)| *v)).collect();
            axis.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            axis.dedup_by(|a, b| (*a - *b).abs() < 1e-9);
            let eps = 1e-9 * p.value.abs().max(1.0);
            let clamp = |v: f64| v.clamp(p.min, p.max);
            if let Some(i) = axis.iter().position(|v| (v - p.value).abs() < eps) {
                let spacing = median_spacing(&axis).unwrap_or(fallback_step(p));
                let down = if i > 0 { axis[i - 1] } else { p.value - spacing };
                let up = if i + 1 < axis.len() { axis[i + 1] } else { p.value + spacing };
                (clamp(down), clamp(up))
            } else {
                let d = median_spacing(&axis).unwrap_or(fallback_step(p));
                (clamp(p.value - d), clamp(p.value + d))
            }
        })
        .collect();

    let k = tunable.len();
    let mut out: Vec<Vec<(String, f64)>> = Vec::new();
    for combo in 0..3usize.pow(k as u32) {
        let mut c = combo;
        let mut set = Vec::with_capacity(k);
        for (j, p) in tunable.iter().enumerate() {
            let v = match c % 3 {
                0 => steps[j].0,
                1 => p.value,
                _ => steps[j].1,
            };
            c /= 3;
            set.push((p.key.clone(), v));
        }
        let is_center = set.iter().zip(&tunable).all(|((_, v), p)| (v - p.value).abs() < 1e-12);
        let dup = out.iter().any(|o| o.iter().zip(&set).all(|((_, a), (_, b))| (a - b).abs() < 1e-12));
        if !is_center && !dup {
            out.push(set);
        }
    }
    (out, k)
}

fn median_spacing(axis: &[f64]) -> Option<f64> {
    if axis.len() < 2 {
        return None;
    }
    let mut gaps: Vec<f64> = axis.windows(2).map(|w| w[1] - w[0]).collect();
    gaps.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    Some(gaps[gaps.len() / 2])
}

/// A parameter the research grid does not cover: 10 % of its value, at least
/// one step of its slider.
fn fallback_step(p: &StrategyParam) -> f64 {
    (p.value.abs() * 0.1).max(p.step.max(1e-9))
}

/// Gate 5's buckets, summed over markets as log returns and averaged.
pub fn regime_split(cfg: &StrategyConfig, windows: &[(&str, &str, &[Ohlc])], bt: &BacktestConfig) -> RegimeSplit {
    let mut acc = [(0.0_f64, 0usize); 4]; // trending, ranging, high, low
    let n = windows.len().max(1) as f64;
    for (id, sym, bars) in windows {
        let r = backtest::run(cfg, id, sym, bars, bt);
        let closes: Vec<f64> = bars.iter().map(|b| b.close).collect();
        // Realised volatility at each decision bar, and its median over the sample.
        let vols: Vec<Option<f64>> =
            (0..r.bar_returns.len()).map(|k| ind::ret_vol(&closes[..=r.first_bar + k], 20)).collect();
        let mut known: Vec<f64> = vols.iter().flatten().copied().collect();
        known.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let median_vol = known.get(known.len() / 2).copied().unwrap_or(0.0);
        for (k, ret) in r.bar_returns.iter().enumerate() {
            let i = r.first_bar + k;
            let lr = (1.0 + ret).max(1e-12).ln();
            let exposed = ret.abs() > 0.0;
            let trending = ind::efficiency_ratio(&closes[..=i], 20).map(|e| e >= 0.4).unwrap_or(false);
            let high = vols[k].map(|v| v > median_vol).unwrap_or(false);
            for (slot, hit) in [(0, trending), (1, !trending), (2, high), (3, !high)] {
                if hit {
                    acc[slot].0 += lr;
                    acc[slot].1 += exposed as usize;
                }
            }
        }
    }
    let res = |(lr, exp): (f64, usize)| RegimeResult { net: (lr / n).exp() - 1.0, exposure: exp };
    RegimeSplit { trending: res(acc[0]), ranging: res(acc[1]), high_vol: res(acc[2]), low_vol: res(acc[3]) }
}

// ── the passport ────────────────────────────────────────────────────────────

/// The eight gates for one strategy, as the Strategies page shows them.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Passport {
    pub strategy_id: String,
    pub gates: Vec<Gate>,
    /// Gates 1 to 7 all pass: the strategy may be set to Live.
    pub live_ready: bool,
    /// Why it may not, in plain language. `None` when `live_ready`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub blocked_reason: Option<String>,
    /// When gates 1 to 6 were last computed.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub checked_at: Option<i64>,
    /// The research gates were run with different parameters than the
    /// strategy has now, so they no longer describe it.
    pub stale: bool,
}

/// Assemble a passport from cached research and the live record.
pub fn passport(
    cfg: &StrategyConfig,
    research: Option<&ResearchVerdict>,
    forward: &ForwardRecord,
    live: &LiveRecord,
) -> Passport {
    let current = params_of(cfg);
    let same_params = |v: &ResearchVerdict| {
        v.params.len() == current.len()
            && v.params.iter().zip(&current).all(|((ka, va), (kb, vb))| ka == kb && (va - vb).abs() < 1e-9)
    };
    let stale = research.map(|v| !same_params(v)).unwrap_or(false);
    let mut gates: Vec<Gate> = match research {
        Some(v) if !stale => v.gates.clone(),
        Some(_) => (1..=6)
            .map(|id| {
                Gate::new(id, GateStatus::Pending, "the parameters changed since the last check; run the checks again", None)
            })
            .collect(),
        None => (1..=6)
            .map(|id| Gate::new(id, GateStatus::Pending, "not checked yet: run the checks on real candles", None))
            .collect(),
    };
    gates.push(judge_forward(forward));
    gates.push(judge_live(live));

    let first_open = gates.iter().take(7).find(|g| !g.passed());
    let blocked_reason = first_open.map(|g| {
        let state = match g.status {
            GateStatus::Fail => "failed",
            GateStatus::Pending => "is not done",
            GateStatus::Pass => "passed",
        };
        format!(
            "Not ready for real money: gate {} ({}) {state}. {}",
            g.id,
            g.name.to_lowercase(),
            capitalise(&g.reason)
        )
    });
    Passport {
        strategy_id: cfg.id.clone(),
        live_ready: blocked_reason.is_none(),
        blocked_reason,
        checked_at: research.map(|v| v.checked_at),
        stale,
        gates,
    }
}

fn capitalise(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
        None => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::connectors::Venue;
    use crate::engine::{StrategyKind, StrategyState};
    use crate::research::metrics::Stats;
    use crate::research::Verdict;

    fn report(trades: usize, is_sharpe: f64, oos_sharpe: f64, dsr: f64) -> StrategyReport {
        StrategyReport {
            strategy_id: "t".into(),
            name: "T".into(),
            kind: StrategyKind::EmaCross,
            markets: vec![],
            portfolio: Stats { trades, sharpe: oos_sharpe, bars: 500, ..Default::default() },
            trials: 9,
            is_sharpe,
            oos_is_ratio: (is_sharpe > 0.0).then(|| oos_sharpe / is_sharpe),
            deflated_sharpe: dsr,
            verdict: if trades < 20 { Verdict::Insufficient } else { Verdict::Pass },
            reason: String::new(),
            folds_run: 4,
            folds_unfitted: 0,
        }
    }

    fn cfg(kind: StrategyKind, params: Vec<StrategyParam>, universe: &[&str]) -> StrategyConfig {
        StrategyConfig {
            id: "s".into(),
            name: "S".into(),
            kind,
            venue_class: Venue::Crypto,
            state: StrategyState::Paper,
            universe: universe.iter().map(|s| s.to_string()).collect(),
            params,
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

    fn p(key: &str, value: f64, min: f64, max: f64) -> StrategyParam {
        StrategyParam { key: key.into(), label: key.into(), value, min, max, step: 1.0 }
    }

    fn ema() -> StrategyConfig {
        cfg(StrategyKind::EmaCross, vec![p("fast", 9.0, 3.0, 30.0), p("slow", 21.0, 10.0, 100.0)], &[])
    }

    // ── gate 1 ──
    #[test]
    fn gate_1_needs_a_positive_net_in_sample() {
        assert_eq!(judge_in_sample(0.12, 30, 400).status, GateStatus::Pass);
        let lost = judge_in_sample(-0.02, 30, 400);
        assert_eq!(lost.status, GateStatus::Fail);
        assert_eq!(lost.value, Some(-0.02), "the number it was judged on is reported");
        assert_eq!(judge_in_sample(0.0, 0, 400).status, GateStatus::Fail, "no trades is not a result");
        assert_eq!(judge_in_sample(0.0, 0, 0).status, GateStatus::Pending);
    }

    // ── gate 2 ──
    #[test]
    fn gate_2_needs_out_of_sample_to_keep_half_the_in_sample_sharpe() {
        let ok = judge_walk_forward(&report(40, 1.2, 0.7, 0.9), 20);
        assert_eq!(ok.status, GateStatus::Pass);
        assert!((ok.value.unwrap() - 0.7 / 1.2).abs() < 1e-12);
        let decayed = judge_walk_forward(&report(40, 1.2, 0.5, 0.9), 20);
        assert_eq!(decayed.status, GateStatus::Fail, "0.42 is below 0.5");
        let negative_is = judge_walk_forward(&report(40, -0.3, 0.2, 0.5), 20);
        assert_eq!(negative_is.status, GateStatus::Fail);
        assert_eq!(judge_walk_forward(&report(5, 1.2, 0.9, 0.9), 20).status, GateStatus::Pending);
        let mut none = report(40, 1.0, 1.0, 0.9);
        none.folds_run = 0;
        assert_eq!(judge_walk_forward(&none, 20).status, GateStatus::Pending);
    }

    // ── gate 3 ──
    #[test]
    fn gate_3_must_survive_double_costs_and_reports_all_three() {
        let g = judge_costs([0.20, 0.08, -0.03], 50);
        assert_eq!(g.status, GateStatus::Pass);
        assert_eq!(g.value, Some(0.08));
        let labels: Vec<&str> = g.figures.iter().map(|f| f.label.as_str()).collect();
        assert_eq!(labels, ["1x costs", "2x costs", "3x costs"]);
        let thin = judge_costs([0.05, -0.01, -0.07], 50);
        assert_eq!(thin.status, GateStatus::Fail);
        assert!(thin.reason.contains("double"));
        assert_eq!(judge_costs([-0.01, -0.05, -0.09], 50).status, GateStatus::Fail);
        assert_eq!(judge_costs([0.0, 0.0, 0.0], 0).status, GateStatus::Fail);
    }

    // ── gate 4 ──
    #[test]
    fn gate_4_wants_a_plateau_not_a_spike() {
        let plateau = judge_plateau(&[0.1, 0.05, 0.02, -0.01, 0.03, 0.04, 0.01, -0.02], 2);
        assert_eq!(plateau.status, GateStatus::Pass, "6 of 8 is 75 %");
        let spike = judge_plateau(&[0.1, -0.05, -0.02, -0.01, 0.03, -0.04, -0.01, -0.02], 2);
        assert_eq!(spike.status, GateStatus::Fail, "2 of 8 is a spike");
        assert!((spike.value.unwrap() - 0.25).abs() < 1e-12);
        assert_eq!(judge_plateau(&[], 0).status, GateStatus::Pass, "nothing tuned, nothing overfit");
        // Exactly 60 % passes.
        let edge = judge_plateau(&[1.0, 1.0, 1.0, -1.0, -1.0], 1);
        assert_eq!(edge.status, GateStatus::Pass);
    }

    #[test]
    fn the_neighbourhood_is_one_grid_step_either_side() {
        let (n, k) = neighbourhood(&ema());
        assert_eq!(k, 2);
        assert_eq!(n.len(), 8, "3 x 3 minus the centre");
        // fast = 9 sits on the grid axis [5, 9, 13]; slow = 21 on [21, 34, 55]
        // is the lowest value, so its step down is the median spacing (17),
        // clamped to the parameter's own minimum of 10.
        let fasts: Vec<f64> = n.iter().map(|s| s[0].1).collect();
        let slows: Vec<f64> = n.iter().map(|s| s[1].1).collect();
        for v in &fasts {
            assert!([5.0, 9.0, 13.0].contains(v), "fast neighbour {v}");
        }
        for v in &slows {
            assert!([10.0, 21.0, 34.0].contains(v), "slow neighbour {v}");
        }
        assert!(!n.iter().any(|s| s[0].1 == 9.0 && s[1].1 == 21.0), "the configured point is not its own neighbour");

        // Off-grid values step by the axis's median spacing.
        let off = cfg(StrategyKind::EmaCross, vec![p("fast", 7.0, 3.0, 30.0)], &[]);
        let (n, _) = neighbourhood(&off);
        let vals: Vec<f64> = n.iter().map(|s| s[0].1).collect();
        assert_eq!(vals, [3.0, 11.0]);

        // A kind with nothing to tune has no neighbourhood.
        let macd = cfg(StrategyKind::MacdTrend, vec![], &[]);
        assert_eq!(neighbourhood(&macd), (vec![], 0));
    }

    // ── gate 5 ──
    fn r(net: f64, exposure: usize) -> RegimeResult {
        RegimeResult { net, exposure }
    }

    #[test]
    fn gate_5_fails_a_one_regime_strategy_without_a_filter() {
        let everywhere = RegimeSplit { trending: r(0.1, 100), ranging: r(0.02, 80), high_vol: r(0.05, 90), low_vol: r(0.07, 90) };
        assert_eq!(judge_regimes(&everywhere, false).status, GateStatus::Pass);
        assert_eq!(judge_regimes(&everywhere, false).value, Some(4.0));

        let trend_only = RegimeSplit { trending: r(0.3, 100), ranging: r(-0.1, 80), high_vol: r(0.1, 90), low_vol: r(0.1, 90) };
        let g = judge_regimes(&trend_only, false);
        assert_eq!(g.status, GateStatus::Fail);
        assert!(g.reason.contains("ranging"));
        assert!(g.reason.contains("regime filter"), "the way out is named");
    }

    #[test]
    fn gate_5_accepts_a_regime_the_filter_keeps_it_out_of() {
        // With the filter on, a trend follower barely trades in chop. That is
        // the filter working, not a regime it failed in.
        let filtered = RegimeSplit { trending: r(0.3, 200), ranging: r(-0.001, 3), high_vol: r(0.1, 100), low_vol: r(0.2, 103) };
        assert_eq!(judge_regimes(&filtered, true).status, GateStatus::Pass);
        // But a real loss where it does trade still fails, filter or not.
        let leaky = RegimeSplit { trending: r(0.3, 200), ranging: r(-0.05, 60), high_vol: r(0.1, 130), low_vol: r(0.2, 130) };
        assert_eq!(judge_regimes(&leaky, true).status, GateStatus::Fail);
        // And the volatility split has no filter.
        let vol_only = RegimeSplit { trending: r(0.3, 200), ranging: r(0.0, 2), high_vol: r(0.4, 100), low_vol: r(-0.1, 102) };
        assert_eq!(judge_regimes(&vol_only, true).status, GateStatus::Fail);
        // Never trading is profitable nowhere.
        assert_eq!(judge_regimes(&RegimeSplit::default(), true).status, GateStatus::Fail);
    }

    // ── gate 6 ──
    #[test]
    fn gate_6_needs_p_below_five_percent() {
        let g = judge_deflated(&report(60, 1.0, 1.0, 0.97), 20);
        assert_eq!(g.status, GateStatus::Pass);
        assert!((g.value.unwrap() - 0.03).abs() < 1e-12);
        assert_eq!(judge_deflated(&report(60, 1.0, 1.0, 0.90), 20).status, GateStatus::Fail);
        assert_eq!(judge_deflated(&report(4, 1.0, 1.0, 0.99), 20).status, GateStatus::Pending);
    }

    fn noise(n: usize, seed: u64) -> Vec<Ohlc> {
        let mut rng = seed.max(1);
        let mut price = 100.0;
        (0..n)
            .map(|i| {
                rng ^= rng << 13;
                rng ^= rng >> 7;
                rng ^= rng << 17;
                let z = ((rng >> 11) as f64 / (1u64 << 53) as f64 - 0.5) * 0.04;
                let open = price;
                price *= 1.0 + z;
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

    #[test]
    fn a_strategy_fit_to_pure_noise_fails_gate_6() {
        // Random walks have no edge to find. Walk-forward still picks the best
        // of nine parameter sets every fold; the deflated Sharpe has to see
        // through that, every time.
        for seed in [7u64, 19, 42, 77, 101] {
            let markets: Vec<(String, String, Vec<Ohlc>)> = (0..3)
                .map(|m| (format!("crypto:N{m}"), format!("N{m}"), noise(900, seed * 10 + m)))
                .collect();
            let base = StrategyConfig {
                universe: markets.iter().map(|(id, _, _)| id.clone()).collect(),
                ..ema()
            };
            let v = research_gates(&base, &markets, &BacktestConfig::default(), &WalkForwardConfig::default(), 0);
            let g6 = &v.gates[5];
            assert_eq!(g6.id, 6);
            assert_eq!(
                g6.status,
                GateStatus::Fail,
                "seed {seed}: noise must not pass or hide behind pending: {} ({:?})",
                g6.reason,
                g6.value
            );
        }
    }

    /// Long alternating trends with daily noise: something a trend follower
    /// genuinely has an edge on.
    fn trends(n: usize, seed: u64) -> Vec<Ohlc> {
        let mut bars = noise(n, seed);
        let mut price = 100.0;
        for (i, b) in bars.iter_mut().enumerate() {
            let sign = if (i / 120) % 2 == 0 { 1.0 } else { -1.0 };
            let z = (b.close / b.open - 1.0) * 0.5; // keep the noise, halve it
            let open = price;
            price *= 1.0 + 0.006 * sign + z;
            *b = Ohlc { ts: b.ts, open, high: open.max(price) * 1.002, low: open.min(price) * 0.998, close: price, volume: 1.0 };
        }
        bars
    }

    #[test]
    fn a_real_edge_can_pass_the_research_gates() {
        // The gates are a bar, not a wall: a trend follower on data that
        // really trends clears in-sample, double costs and significance.
        let markets: Vec<(String, String, Vec<Ohlc>)> =
            (0..3).map(|m| (format!("crypto:T{m}"), format!("T{m}"), trends(1400, 900 + m))).collect();
        let base = StrategyConfig { universe: markets.iter().map(|(id, _, _)| id.clone()).collect(), ..ema() };
        let v = research_gates(&base, &markets, &BacktestConfig::default(), &WalkForwardConfig::default(), 0);
        for id in [1usize, 3, 6] {
            let g = &v.gates[id - 1];
            assert_eq!(g.status, GateStatus::Pass, "gate {id}: {} ({:?})", g.reason, g.value);
        }
    }

    #[test]
    fn research_gates_cover_one_to_six_in_order_with_numbers() {
        let markets: Vec<(String, String, Vec<Ohlc>)> =
            (0..2).map(|m| (format!("crypto:N{m}"), format!("N{m}"), noise(800, 500 + m))).collect();
        let base = StrategyConfig { universe: markets.iter().map(|(id, _, _)| id.clone()).collect(), ..ema() };
        let v = research_gates(&base, &markets, &BacktestConfig::default(), &WalkForwardConfig::default(), 123);
        let ids: Vec<u8> = v.gates.iter().map(|g| g.id).collect();
        assert_eq!(ids, [1, 2, 3, 4, 5, 6]);
        assert_eq!(v.checked_at, 123);
        assert_eq!(v.params, vec![("fast".to_string(), 9.0), ("slow".to_string(), 21.0)]);
        // Cost sensitivity reports all three runs, and more cost is never better.
        let g3 = &v.gates[2];
        assert_eq!(g3.figures.len(), 3);
        assert!(g3.figures[0].value >= g3.figures[1].value && g3.figures[1].value >= g3.figures[2].value);
        // The regime gate reports all four buckets.
        assert_eq!(v.gates[4].figures.len(), 4);
        for g in &v.gates {
            assert!(!g.reason.is_empty());
        }
    }

    #[test]
    fn a_kind_the_harness_cannot_score_stays_pending_not_passed() {
        let pairs = cfg(StrategyKind::Pairs, vec![], &[]);
        let v = research_gates(&pairs, &[("a".into(), "A".into(), noise(800, 1))], &BacktestConfig::default(), &WalkForwardConfig::default(), 0);
        assert!(v.gates.iter().all(|g| g.status == GateStatus::Pending));
        let short = research_gates(&ema(), &[("a".into(), "A".into(), noise(100, 1))], &BacktestConfig::default(), &WalkForwardConfig::default(), 0);
        assert!(short.gates.iter().all(|g| g.status == GateStatus::Pending));
    }

    // ── gate 7 ──
    const DAY: i64 = 86_400_000;

    #[test]
    fn gate_7_needs_thirty_trading_days_and_thirty_trades() {
        let now = 1_760_000_000_000; // a fixed instant
        let f = |days: i64, trades: u32, equities: bool| ForwardRecord {
            paper_since: Some(now - days * DAY),
            trades,
            equities,
            now,
            slippage: None,
        };
        assert_eq!(judge_forward(&f(31, 30, false)).status, GateStatus::Pass);
        assert_eq!(judge_forward(&f(31, 12, false)).status, GateStatus::Pending, "days without trades");
        assert_eq!(judge_forward(&f(10, 80, false)).status, GateStatus::Pending, "trades without days");
        // 31 calendar days hold only ~22 weekdays.
        assert_eq!(judge_forward(&f(31, 40, true)).status, GateStatus::Pending);
        assert_eq!(judge_forward(&f(45, 40, true)).status, GateStatus::Pass);
        assert_eq!(judge_forward(&ForwardRecord { now, ..Default::default() }).status, GateStatus::Pending);
        assert_eq!(judge_forward(&f(31, 30, false)).value, Some(30.0));
    }

    #[test]
    fn gate_7_fails_when_real_fills_cost_far_more_than_the_model() {
        let now = 1_760_000_000_000;
        let bad = SlippageRow {
            venue: "kraken".into(),
            fills: 40,
            median_realised_bps: 9.0,
            median_modelled_bps: 3.0,
            ratio: Some(3.0),
            enough: true,
        };
        let f = ForwardRecord { paper_since: Some(now - 40 * DAY), trades: 50, equities: false, now, slippage: Some(bad) };
        let g = judge_forward(&f);
        assert_eq!(g.status, GateStatus::Fail);
        assert!(g.reason.contains("costs.json"));
    }

    #[test]
    fn weekdays_are_counted_for_equities() {
        // Monday 2026-01-05 00:00 UTC to the following Monday: five weekdays.
        let monday = chrono::NaiveDate::from_ymd_opt(2026, 1, 5).unwrap().and_hms_opt(0, 0, 0).unwrap().and_utc().timestamp_millis();
        assert_eq!(trading_days(monday, monday + 7 * DAY, true), 5);
        assert_eq!(trading_days(monday, monday + 7 * DAY, false), 7);
        assert_eq!(trading_days(monday, monday - DAY, false), 0);
    }

    // ── gate 8 ──
    #[test]
    fn gate_8_is_pending_until_there_is_live_data() {
        assert_eq!(judge_live(&LiveRecord::default()).status, GateStatus::Pending);
        assert_eq!(judge_live(&LiveRecord { trades: 12, slippage: None }).status, GateStatus::Pending);
        let good = SlippageRow { venue: "alpaca".into(), fills: 60, median_realised_bps: 1.2, median_modelled_bps: 1.0, ratio: Some(1.2), enough: true };
        assert_eq!(judge_live(&LiveRecord { trades: 35, slippage: Some(good.clone()) }).status, GateStatus::Pass);
        let bad = SlippageRow { ratio: Some(2.4), median_realised_bps: 2.4, ..good };
        assert_eq!(judge_live(&LiveRecord { trades: 35, slippage: Some(bad) }).status, GateStatus::Fail);
        assert_eq!(judge_live(&LiveRecord { trades: 35, slippage: None }).status, GateStatus::Pending);
    }

    // ── the passport ──
    fn all_pass_research(cfg: &StrategyConfig) -> ResearchVerdict {
        ResearchVerdict {
            strategy_id: cfg.id.clone(),
            params: params_of(cfg),
            checked_at: 1,
            markets: 1,
            bars: 700,
            cost_venue: crate::costs::CostVenue::Kraken,
            gates: (1..=6).map(|id| Gate::new(id, GateStatus::Pass, "ok", Some(1.0))).collect(),
        }
    }

    fn forward_ok() -> ForwardRecord {
        let now = 1_760_000_000_000;
        ForwardRecord { paper_since: Some(now - 40 * DAY), trades: 40, equities: false, now, slippage: None }
    }

    #[test]
    fn live_needs_gates_one_to_seven_and_not_eight() {
        let s = ema();
        let pp = passport(&s, Some(&all_pass_research(&s)), &forward_ok(), &LiveRecord::default());
        assert_eq!(pp.gates.len(), 8);
        assert_eq!(pp.gates[7].status, GateStatus::Pending, "gate 8 is earned after arming");
        assert!(pp.live_ready);
        assert!(pp.blocked_reason.is_none());

        let mut f = forward_ok();
        f.trades = 3;
        let pp = passport(&s, Some(&all_pass_research(&s)), &f, &LiveRecord::default());
        assert!(!pp.live_ready);
        let why = pp.blocked_reason.unwrap();
        assert!(why.contains("gate 7"), "{why}");
        assert!(why.starts_with("Not ready for real money"), "plain language: {why}");
    }

    #[test]
    fn an_unchecked_or_changed_strategy_is_not_live_ready() {
        let s = ema();
        let none = passport(&s, None, &forward_ok(), &LiveRecord::default());
        assert!(!none.live_ready);
        assert!(none.gates[..6].iter().all(|g| g.status == GateStatus::Pending));

        let research = all_pass_research(&s);
        let mut changed = s.clone();
        changed.params[0].value = 13.0;
        let pp = passport(&changed, Some(&research), &forward_ok(), &LiveRecord::default());
        assert!(pp.stale);
        assert!(!pp.live_ready, "checks on other parameters describe another strategy");
        assert!(pp.gates[0].reason.contains("changed"));
    }

    #[test]
    fn the_first_failing_gate_is_the_one_named() {
        let s = ema();
        let mut research = all_pass_research(&s);
        research.gates[2] = judge_costs([0.05, -0.01, -0.07], 50);
        research.gates[4] = judge_regimes(&RegimeSplit::default(), false);
        let pp = passport(&s, Some(&research), &forward_ok(), &LiveRecord::default());
        let why = pp.blocked_reason.unwrap();
        assert!(why.contains("gate 3 (cost sensitivity) failed"), "{why}");
    }

    #[test]
    fn gates_serialise_in_camel_case_with_lowercase_status() {
        let s = ema();
        let pp = passport(&s, Some(&all_pass_research(&s)), &forward_ok(), &LiveRecord::default());
        let v = serde_json::to_value(&pp).unwrap();
        assert!(v.get("liveReady").is_some());
        assert!(v.get("strategyId").is_some());
        assert_eq!(v["gates"][0]["status"], "pass");
        assert!(v["gates"][6].get("figures").is_some());
        assert!(v["gates"][0].get("measure").is_some());
    }
}
