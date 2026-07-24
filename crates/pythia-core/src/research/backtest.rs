//! A deliberately pessimistic single-market backtester.
//!
//! Everything here is arranged so the result is more likely to *understate* an
//! edge than overstate one, because the failure mode that costs money is the
//! other direction. Four rules do most of that work:
//!
//! 1. **Signal on bar `t`, fill on bar `t+1`'s open.** Filling at the close of
//!    the bar that produced the signal is the classic lookahead bias — it uses
//!    a price that did not exist when the decision was made, and it is worth an
//!    enormous amount of imaginary profit on a mean-reversion rule.
//! 2. **Exits are checked against the bar's high and low, not its close.** A
//!    stop that was touched intrabar was hit, regardless of where the bar
//!    settled.
//! 3. **When a bar's range contains both the stop and the target, the stop is
//!    assumed to have hit first.** From OHLC alone the path is unknowable, and
//!    the optimistic assumption is exactly the one that makes a bad strategy
//!    look profitable.
//! 4. **Costs on both sides of every trade**, entry and exit, including
//!    slippage on market exits.
//!
//! Signals come from [`crate::engine::strategies::run_strategy`] — the same
//! code the live engine runs. A backtest that reimplements its own version of
//! the strategy is testing the reimplementation.

use super::metrics::{self, Stats};
use crate::connectors::{Side, Venue};
use crate::engine::indicators as ind;
use crate::engine::{Market, MarketKind, Regime, StrategyConfig};
use crate::marketdata::Ohlc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Per-side trading costs, in basis points.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CostModel {
    /// Commission / taker fee per side.
    pub fee_bps: f64,
    /// Spread + market impact per side, applied to every market fill.
    pub slippage_bps: f64,
}

impl Default for CostModel {
    fn default() -> Self {
        // Matches the live paper fill model: 6bps fee, 8bps slippage. On a
        // strategy that turns over daily this is ~7% a year of pure drag, which
        // is why most short-horizon rules die here rather than in the market.
        Self { fee_bps: 6.0, slippage_bps: 8.0 }
    }
}

impl CostModel {
    fn fee(&self) -> f64 {
        self.fee_bps / 10_000.0
    }
    fn slip(&self) -> f64 {
        self.slippage_bps / 10_000.0
    }
    /// Free execution — for isolating how much of a result is the cost model.
    pub fn frictionless() -> Self {
        Self { fee_bps: 0.0, slippage_bps: 0.0 }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BacktestConfig {
    pub costs: CostModel,
    /// Stop distance in ATR units (0 = no stop).
    pub stop_atr_mult: f64,
    /// Take-profit distance in ATR units (0 = let winners run).
    pub take_profit_atr_mult: f64,
    /// Trailing-stop distance in ATR units (0 = fixed stop).
    pub trail_atr_mult: f64,
    pub atr_period: usize,
    /// For annualizing Sharpe: 365 for daily crypto, 252 for daily equities.
    pub bars_per_year: f64,
    /// Block entries that fight the 60-bar trend, as the live engine does.
    pub trend_filter: bool,
    /// Block mean-reversion in trends and trend-following in chop.
    pub regime_filter: bool,
}

impl Default for BacktestConfig {
    fn default() -> Self {
        // Mirrors the shipped RiskLimits so a backtest describes the system
        // that would actually run, not an idealized cousin of it.
        Self {
            costs: CostModel::default(),
            stop_atr_mult: 8.0,
            take_profit_atr_mult: 0.0,
            trail_atr_mult: 6.0,
            atr_period: 14,
            bars_per_year: 365.0,
            trend_filter: true,
            regime_filter: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Trade {
    pub entry_ts: i64,
    pub exit_ts: i64,
    pub side: Side,
    pub entry: f64,
    pub exit: f64,
    /// Net of all costs, as a fraction of the position.
    pub ret: f64,
    pub bars_held: usize,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BacktestResult {
    pub stats: Stats,
    pub trades: Vec<Trade>,
    /// Per-bar strategy return, zero while flat.
    pub bar_returns: Vec<f64>,
    pub equity: Vec<f64>,
}

struct Open {
    side: Side,
    entry: f64,
    entry_ts: i64,
    entry_i: usize,
    mark: f64,
    stop: f64,
    target: f64,
    trail_ref: f64,
    equity_at_entry: f64,
}

/// Bars needed before the first signal can be trusted. The 60-bar trend filter
/// and MACD's 26+9 seeding are the binding constraints.
pub const WARMUP: usize = 70;

/// Rolling history the strategies are allowed to see, matching the live
/// engine's cap in `Engine::tick`.
///
/// Not an optimization — a fidelity requirement. Live, an EMA is seeded from at
/// most 260 bars; letting the backtest seed from two years of history tests a
/// different indicator that happens to share a name. (It also keeps each signal
/// evaluation O(260) rather than O(sample), which is the difference between a
/// validation run finishing in seconds and in minutes.)
const HISTORY_CAP: usize = 260;

/// Run one strategy over one market's candles.
pub fn run(cfg: &StrategyConfig, market_id: &str, symbol: &str, bars: &[Ohlc], bt: &BacktestConfig) -> BacktestResult {
    let n = bars.len();
    let closes: Vec<f64> = bars.iter().map(|b| b.close).collect();
    let mut equity = 1.0_f64;
    let mut equity_curve: Vec<f64> = Vec::with_capacity(n);
    let mut bar_returns: Vec<f64> = Vec::with_capacity(n);
    let mut trades: Vec<Trade> = Vec::new();
    let mut open: Option<Open> = None;

    // The strategies read from these maps; both are mutated in place each bar so
    // a 700-bar sample doesn't spend its life cloning vectors.
    let mut markets: HashMap<String, Market> = [(
        market_id.to_string(),
        Market {
            id: market_id.to_string(),
            venue: Venue::Crypto,
            symbol: symbol.to_string(),
            kind: MarketKind::Crypto,
            price: 0.0,
            change24h: 0.0,
            model_prob: None,
            liquidity: None,
            regime: None,
            trend_strength: None,
            updated_at: 0,
        },
    )]
    .into();
    let mut history: HashMap<String, Vec<f64>> =
        [(market_id.to_string(), Vec::with_capacity(HISTORY_CAP + 1))].into();

    let warmup = WARMUP.max(bt.atr_period + 2);
    if n <= warmup + 2 {
        // Not enough history to say anything. Returning an empty result is the
        // honest answer; a two-trade "backtest" is worse than none.
        return BacktestResult {
            stats: Stats::default(),
            trades,
            bar_returns,
            equity: vec![1.0],
        };
    }

    // Seed the rolling window with everything before the first decision bar.
    {
        let h = history.get_mut(market_id).expect("seeded");
        for &c in closes.iter().take(warmup) {
            h.push(c);
            if h.len() > HISTORY_CAP {
                h.remove(0);
            }
        }
    }

    for i in warmup..(n - 1) {
        let next = bars[i + 1];
        let equity_before = equity;

        // Advance the window every bar, whether or not we look for a signal —
        // the live engine's history does not pause while a position is open.
        {
            let h = history.get_mut(market_id).expect("seeded");
            h.push(closes[i]);
            if h.len() > HISTORY_CAP {
                h.remove(0);
            }
        }

        // ── manage an open position on the NEXT bar's range ──────────────────
        if let Some(p) = open.as_mut() {
            let long = p.side == Side::Buy;
            let hit_stop = p.stop > 0.0 && if long { next.low <= p.stop } else { next.high >= p.stop };
            let hit_target =
                p.target > 0.0 && if long { next.high >= p.target } else { next.low <= p.target };

            // Stop before target when both are in range: the path is unknowable
            // from OHLC, so assume the bad one.
            let exit = if hit_stop {
                // A stop is a market order — it slips.
                let fill = if long { p.stop * (1.0 - bt.costs.slip()) } else { p.stop * (1.0 + bt.costs.slip()) };
                Some((fill, "stop-loss"))
            } else if hit_target {
                // A target is a resting limit — it fills at its price or not at all.
                Some((p.target, "take-profit"))
            } else {
                None
            };

            if let Some((fill, reason)) = exit {
                let dir = if long { 1.0 } else { -1.0 };
                let r = dir * (fill - p.mark) / p.mark;
                equity *= (1.0 + r) * (1.0 - bt.costs.fee());
                trades.push(Trade {
                    entry_ts: p.entry_ts,
                    exit_ts: next.ts,
                    side: p.side,
                    entry: p.entry,
                    exit: fill,
                    ret: equity / p.equity_at_entry - 1.0,
                    bars_held: i + 1 - p.entry_i,
                    reason: reason.to_string(),
                });
                open = None;
            } else {
                // Mark to the bar's close, then ratchet the trail on its extreme.
                let dir = if long { 1.0 } else { -1.0 };
                let r = dir * (next.close - p.mark) / p.mark;
                equity *= 1.0 + r;
                p.mark = next.close;
                if bt.trail_atr_mult > 0.0 && p.stop > 0.0 {
                    if long && next.high > p.trail_ref {
                        let d = p.trail_ref - p.stop;
                        p.trail_ref = next.high;
                        p.stop = next.high - d;
                    } else if !long && next.low < p.trail_ref {
                        let d = p.stop - p.trail_ref;
                        p.trail_ref = next.low;
                        p.stop = next.low + d;
                    }
                }
            }
        }

        // ── look for an entry, using only data up to and including bar i ─────
        if open.is_none() {
            if let Some(side) = signal_at(cfg, market_id, &mut markets, &history, bt) {
                // Fill at the NEXT bar's open, not this bar's close.
                let fill = if side == Side::Buy {
                    next.open * (1.0 + bt.costs.slip())
                } else {
                    next.open * (1.0 - bt.costs.slip())
                };
                equity *= 1.0 - bt.costs.fee();
                let atr = ind::atr(&bars[..=i], bt.atr_period).unwrap_or(0.0);
                let long = side == Side::Buy;
                let stop = if bt.stop_atr_mult > 0.0 && atr > 0.0 {
                    if long { fill - bt.stop_atr_mult * atr } else { fill + bt.stop_atr_mult * atr }
                } else {
                    0.0
                };
                let target = if bt.take_profit_atr_mult > 0.0 && atr > 0.0 {
                    if long { fill + bt.take_profit_atr_mult * atr } else { fill - bt.take_profit_atr_mult * atr }
                } else {
                    0.0
                };
                open = Some(Open {
                    side,
                    entry: fill,
                    entry_ts: next.ts,
                    entry_i: i + 1,
                    mark: fill,
                    stop,
                    target,
                    trail_ref: fill,
                    equity_at_entry: equity,
                });
            }
        }

        bar_returns.push(equity / equity_before - 1.0);
        equity_curve.push(equity);
    }

    // Close anything still open at the last close, so the result reflects a
    // completed sample rather than an open position marked at a hopeful price.
    if let Some(p) = open {
        let last = bars[n - 1];
        let dir = if p.side == Side::Buy { 1.0 } else { -1.0 };
        let fill = if p.side == Side::Buy {
            last.close * (1.0 - bt.costs.slip())
        } else {
            last.close * (1.0 + bt.costs.slip())
        };
        let r = dir * (fill - p.mark) / p.mark;
        equity *= (1.0 + r) * (1.0 - bt.costs.fee());
        trades.push(Trade {
            entry_ts: p.entry_ts,
            exit_ts: last.ts,
            side: p.side,
            entry: p.entry,
            exit: fill,
            ret: equity / p.equity_at_entry - 1.0,
            bars_held: n - 1 - p.entry_i,
            reason: "end of sample".into(),
        });
        if let Some(e) = equity_curve.last_mut() {
            *e = equity;
        }
    }

    if equity_curve.is_empty() {
        equity_curve.push(1.0);
    }
    let trade_returns: Vec<f64> = trades.iter().map(|t| t.ret).collect();
    let mut full_equity = vec![1.0];
    full_equity.extend_from_slice(&equity_curve);
    let stats = metrics::summarize(&bar_returns, &full_equity, &trade_returns, bt.bars_per_year);

    BacktestResult { stats, trades, bar_returns, equity: full_equity }
}

/// Ask the live strategy code for a signal on a closes-only view of history.
///
/// Deliberately routed through `run_strategy` rather than reimplemented: the
/// point of a backtest is to test the thing that will trade, and two
/// implementations of "EMA cross" drift apart the moment either is touched.
fn signal_at(
    cfg: &StrategyConfig,
    market_id: &str,
    markets: &mut HashMap<String, Market>,
    history: &HashMap<String, Vec<f64>>,
    bt: &BacktestConfig,
) -> Option<Side> {
    let closes = history.get(market_id)?;
    let price = *closes.last()?;
    // Regime is what the engine recomputes each tick; mirror it so the regime
    // filter behaves identically here.
    let er = ind::efficiency_ratio(closes, 20);
    let regime = er.map(|e| if e >= 0.4 { Regime::Trending } else { Regime::Ranging });
    {
        let m = markets.get_mut(market_id)?;
        m.price = price;
        m.regime = regime;
        m.trend_strength = er;
    }

    let intent = crate::engine::strategies::run_strategy(cfg, markets, history).into_iter().next()?;

    // The same two gates the live engine applies before sizing an entry.
    if bt.trend_filter {
        if let Some(lt) = ind::roc(closes, 60) {
            if (lt > 0.01 && intent.side == Side::Sell) || (lt < -0.01 && intent.side == Side::Buy) {
                return None;
            }
        }
    }
    if bt.regime_filter && !crate::engine::strategy_regime_ok(cfg.kind, regime) {
        return None;
    }
    Some(intent.side)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::{StrategyKind, StrategyParam, StrategyState};

    fn bars_from(closes: &[f64]) -> Vec<Ohlc> {
        closes
            .iter()
            .enumerate()
            .map(|(i, &c)| Ohlc {
                ts: i as i64 * 86_400_000,
                open: c,
                high: c * 1.005,
                low: c * 0.995,
                close: c,
                volume: 1.0,
            })
            .collect()
    }

    fn ema_cross() -> StrategyConfig {
        StrategyConfig {
            id: "t".into(),
            name: "T".into(),
            kind: StrategyKind::EmaCross,
            venue_class: Venue::Crypto,
            state: StrategyState::Paper,
            universe: vec!["crypto:BTC/USD".into()],
            params: vec![
                StrategyParam { key: "fast".into(), label: "f".into(), value: 9.0, min: 3.0, max: 30.0, step: 1.0 },
                StrategyParam { key: "slow".into(), label: "s".into(), value: 21.0, min: 10.0, max: 100.0, step: 1.0 },
            ],
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

    #[test]
    fn refuses_to_report_on_a_sample_that_is_too_short() {
        let bars = bars_from(&(0..40).map(|i| 100.0 + i as f64).collect::<Vec<_>>());
        let r = run(&ema_cross(), "crypto:BTC/USD", "BTC/USD", &bars, &BacktestConfig::default());
        assert_eq!(r.trades.len(), 0);
        assert_eq!(r.stats.bars, 0, "a handful of bars must produce no claim at all");
    }

    #[test]
    fn a_clean_uptrend_is_profitable_and_costs_still_bite() {
        // 300 bars of steady 0.5%/bar advance: a trend follower should make money.
        let closes: Vec<f64> = (0..300).map(|i| 100.0 * 1.005_f64.powi(i)).collect();
        let bars = bars_from(&closes);

        let free = run(
            &ema_cross(),
            "crypto:BTC/USD",
            "BTC/USD",
            &bars,
            &BacktestConfig { costs: CostModel::frictionless(), ..Default::default() },
        );
        assert!(free.stats.total_return > 0.0, "got {}", free.stats.total_return);

        let costed = run(&ema_cross(), "crypto:BTC/USD", "BTC/USD", &bars, &BacktestConfig::default());
        assert!(
            costed.stats.total_return < free.stats.total_return,
            "costs must reduce the result ({} vs {})",
            costed.stats.total_return,
            free.stats.total_return
        );
    }

    #[test]
    fn entries_fill_on_the_next_bar_open_not_the_signal_close() {
        // Give the bar after each signal a distinctly different open. If the
        // backtester filled at the signal bar's close, entry prices would match
        // the closes instead.
        let closes: Vec<f64> = (0..300).map(|i| 100.0 * 1.004_f64.powi(i)).collect();
        let mut bars = bars_from(&closes);
        for b in bars.iter_mut() {
            b.open = b.close * 1.02; // opens 2% above the previous close level
            b.high = b.open * 1.01;
        }
        let r = run(
            &ema_cross(),
            "crypto:BTC/USD",
            "BTC/USD",
            &bars,
            &BacktestConfig { costs: CostModel::frictionless(), ..Default::default() },
        );
        let t = r.trades.first().expect("a trade");
        let entry_bar = bars.iter().find(|b| b.ts == t.entry_ts).expect("entry bar");
        assert!(
            (t.entry - entry_bar.open).abs() < 1e-6,
            "entry {} should be the bar's open {}, not its close {}",
            t.entry,
            entry_bar.open,
            entry_bar.close
        );
    }

    #[test]
    fn a_stop_inside_the_bar_range_exits_even_if_the_close_recovers() {
        // Long entry, then one bar that spikes down through any plausible stop
        // but closes flat. A close-only backtester would miss this entirely.
        let mut closes: Vec<f64> = (0..200).map(|i| 100.0 * 1.004_f64.powi(i)).collect();
        let plateau = *closes.last().unwrap();
        closes.extend(std::iter::repeat(plateau).take(30));
        let mut bars = bars_from(&closes);
        let crash = bars.len() - 10;
        bars[crash].low = bars[crash].close * 0.2; // −80% wick, full recovery by the close

        let r = run(
            &ema_cross(),
            "crypto:BTC/USD",
            "BTC/USD",
            &bars,
            &BacktestConfig { costs: CostModel::frictionless(), ..Default::default() },
        );
        assert!(
            r.trades.iter().any(|t| t.reason == "stop-loss"),
            "a stop touched intrabar was hit, whatever the close says"
        );
    }

    #[test]
    fn when_stop_and_target_share_a_bar_the_stop_wins() {
        // Both levels reachable in the same bar. From OHLC the path is unknown,
        // so the pessimistic assumption is the only defensible one.
        let closes: Vec<f64> = (0..250).map(|i| 100.0 * 1.004_f64.powi(i)).collect();
        let mut bars = bars_from(&closes);
        for b in bars.iter_mut().skip(200) {
            b.high = b.close * 1.60; // reaches any take-profit
            b.low = b.close * 0.40; // and any stop
        }
        let cfg = BacktestConfig {
            costs: CostModel::frictionless(),
            take_profit_atr_mult: 2.0,
            stop_atr_mult: 2.0,
            trail_atr_mult: 0.0,
            ..Default::default()
        };
        let r = run(&ema_cross(), "crypto:BTC/USD", "BTC/USD", &bars, &cfg);
        let after = r.trades.iter().find(|t| t.exit_ts >= bars[200].ts);
        if let Some(t) = after {
            assert_eq!(t.reason, "stop-loss", "an ambiguous bar must resolve against the trade");
        }
    }

    #[test]
    fn no_open_position_survives_the_end_of_the_sample() {
        let closes: Vec<f64> = (0..300).map(|i| 100.0 * 1.004_f64.powi(i)).collect();
        let bars = bars_from(&closes);
        let r = run(&ema_cross(), "crypto:BTC/USD", "BTC/USD", &bars, &BacktestConfig::default());
        assert!(
            r.trades.iter().any(|t| t.reason == "end of sample"),
            "a still-open position marked at a hopeful price is not a result"
        );
    }
}
