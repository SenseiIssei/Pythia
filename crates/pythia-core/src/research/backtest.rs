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
//!    slippage on market exits. The costs come from [`crate::costs`], per venue
//!    and per instrument, so a backtest of Kraken pays Kraken's 40 bps taker fee
//!    and a backtest of Binance pays Binance's 10.
//!
//! Every result carries gross, costs and net as three separate figures
//! ([`PnlBreakdown`]). Gross is what the same trades would have made at the
//! reference prices with no fees, spread or impact; the difference to net is
//! exactly what execution cost.
//!
//! Signals come from [`crate::engine::strategies::run_strategy`] — the same
//! code the live engine runs. A backtest that reimplements its own version of
//! the strategy is testing the reimplementation.

use super::metrics::{self, Stats};
use crate::connectors::{Side, Venue};
use crate::costs::{self, CostVenue, PnlBreakdown};
use crate::engine::indicators as ind;
use crate::engine::{Market, MarketKind, Regime, StrategyConfig};
use crate::marketdata::Ohlc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Per-side costs for one market, as fractions, resolved once per run.
#[derive(Debug, Clone, Copy)]
struct SideCosts {
    /// Taker fee, charged on equity at every fill.
    fee: f64,
    /// Half-spread plus impact, applied to the fill price of every market order.
    slip: f64,
}

impl SideCosts {
    fn resolve(bt: &BacktestConfig, symbol: &str) -> SideCosts {
        let m = costs::model_for(bt.venue, symbol).scaled(bt.cost_mult);
        SideCosts {
            fee: m.taker_bps / 10_000.0,
            slip: m.slippage_bps(bt.order_notional, None) / 10_000.0,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BacktestConfig {
    /// Whose costs to charge. Resolved per instrument from the cost table, so
    /// BTC pays a major's spread and an alt pays an alt's.
    pub venue: CostVenue,
    /// Multiplier on every cost component: 1 is the model, 0 is frictionless,
    /// 2 and 3 are the cost-sensitivity gate's stress runs.
    pub cost_mult: f64,
    /// Order size used to estimate market impact, in quote currency.
    pub order_notional: f64,
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
            // Kraken: the venue the price feed and the daily candles come from,
            // and at 40 bps taker the most expensive of the four. Pessimism is
            // the right default for a number people will believe.
            venue: CostVenue::Kraken,
            cost_mult: 1.0,
            // Retail size. Impact is negligible here on purpose; it matters
            // when someone scales a strategy up, and the model says so then.
            order_notional: 1_000.0,
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
    /// The same trade at reference prices with no costs.
    pub gross_ret: f64,
    pub bars_held: usize,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BacktestResult {
    pub stats: Stats,
    /// Gross, costs and net over the whole sample, as fractions of starting
    /// capital (0.12 = 12 %).
    pub pnl: PnlBreakdown,
    pub trades: Vec<Trade>,
    /// Per-bar strategy return, zero while flat.
    pub bar_returns: Vec<f64>,
    /// The same per-bar returns with no costs. Pooling these across markets
    /// gives a portfolio's gross line.
    #[serde(skip)]
    pub gross_bar_returns: Vec<f64>,
    /// Index into the input bars of the decision bar behind `bar_returns[0]`.
    /// `bar_returns[k]` is earned over bar `first_bar + k + 1` on a decision
    /// made at the close of bar `first_bar + k`.
    #[serde(skip)]
    pub first_bar: usize,
    pub equity: Vec<f64>,
}

struct Open {
    side: Side,
    entry: f64,
    entry_ts: i64,
    entry_i: usize,
    mark: f64,
    /// Mark at reference prices, for the gross line.
    gross_mark: f64,
    stop: f64,
    target: f64,
    trail_ref: f64,
    equity_at_entry: f64,
    gross_at_entry: f64,
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
    let c = SideCosts::resolve(bt, symbol);
    let mut equity = 1.0_f64;
    // The same trades at reference prices with no costs. Tracked alongside
    // rather than re-run, so gross and net describe exactly the same trades.
    let mut gross = 1.0_f64;
    let mut equity_curve: Vec<f64> = Vec::with_capacity(n);
    let mut bar_returns: Vec<f64> = Vec::with_capacity(n);
    let mut gross_bar_returns: Vec<f64> = Vec::with_capacity(n);
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
            no_price: None,
            resolves_at: None,
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
            pnl: PnlBreakdown::default(),
            trades,
            bar_returns,
            gross_bar_returns,
            first_bar: warmup,
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
        let gross_before = gross;

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
            // (fill, reference price, reason)
            let exit = if hit_stop {
                // A stop is a market order — it slips.
                let fill = if long { p.stop * (1.0 - c.slip) } else { p.stop * (1.0 + c.slip) };
                Some((fill, p.stop, "stop-loss"))
            } else if hit_target {
                // A target is a resting limit — it fills at its price or not at all.
                Some((p.target, p.target, "take-profit"))
            } else {
                None
            };

            if let Some((fill, reference, reason)) = exit {
                let dir = if long { 1.0 } else { -1.0 };
                let r = dir * (fill - p.mark) / p.mark;
                equity *= (1.0 + r) * (1.0 - c.fee);
                gross *= 1.0 + dir * (reference - p.gross_mark) / p.gross_mark;
                trades.push(Trade {
                    entry_ts: p.entry_ts,
                    exit_ts: next.ts,
                    side: p.side,
                    entry: p.entry,
                    exit: fill,
                    ret: equity / p.equity_at_entry - 1.0,
                    gross_ret: gross / p.gross_at_entry - 1.0,
                    bars_held: i + 1 - p.entry_i,
                    reason: reason.to_string(),
                });
                open = None;
            } else {
                // Mark to the bar's close, then ratchet the trail on its extreme.
                let dir = if long { 1.0 } else { -1.0 };
                let r = dir * (next.close - p.mark) / p.mark;
                equity *= 1.0 + r;
                gross *= 1.0 + dir * (next.close - p.gross_mark) / p.gross_mark;
                p.mark = next.close;
                p.gross_mark = next.close;
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
                    next.open * (1.0 + c.slip)
                } else {
                    next.open * (1.0 - c.slip)
                };
                equity *= 1.0 - c.fee;
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
                    gross_mark: next.open,
                    stop,
                    target,
                    trail_ref: fill,
                    equity_at_entry: equity,
                    gross_at_entry: gross,
                });
            }
        }

        bar_returns.push(equity / equity_before - 1.0);
        gross_bar_returns.push(gross / gross_before - 1.0);
        equity_curve.push(equity);
    }

    // Close anything still open at the last close, so the result reflects a
    // completed sample rather than an open position marked at a hopeful price.
    if let Some(p) = open {
        let last = bars[n - 1];
        let dir = if p.side == Side::Buy { 1.0 } else { -1.0 };
        let fill = if p.side == Side::Buy {
            last.close * (1.0 - c.slip)
        } else {
            last.close * (1.0 + c.slip)
        };
        let r = dir * (fill - p.mark) / p.mark;
        let before = equity;
        let gross_before = gross;
        equity *= (1.0 + r) * (1.0 - c.fee);
        gross *= 1.0 + dir * (last.close - p.gross_mark) / p.gross_mark;
        trades.push(Trade {
            entry_ts: p.entry_ts,
            exit_ts: last.ts,
            side: p.side,
            entry: p.entry,
            exit: fill,
            ret: equity / p.equity_at_entry - 1.0,
            gross_ret: gross / p.gross_at_entry - 1.0,
            bars_held: n - 1 - p.entry_i,
            reason: "end of sample".into(),
        });
        if let Some(e) = equity_curve.last_mut() {
            *e = equity;
        }
        // Fold the forced exit into the last bar's return, so the per-bar
        // series compounds to the same final equity the curve shows.
        if let Some(r) = bar_returns.last_mut() {
            *r = (1.0 + *r) * (equity / before) - 1.0;
        }
        if let Some(r) = gross_bar_returns.last_mut() {
            *r = (1.0 + *r) * (gross / gross_before) - 1.0;
        }
    }

    if equity_curve.is_empty() {
        equity_curve.push(1.0);
    }
    let trade_returns: Vec<f64> = trades.iter().map(|t| t.ret).collect();
    let mut full_equity = vec![1.0];
    full_equity.extend_from_slice(&equity_curve);
    let stats = metrics::summarize(&bar_returns, &full_equity, &trade_returns, bt.bars_per_year);
    let pnl = PnlBreakdown::new(gross - 1.0, gross - equity);

    BacktestResult {
        stats,
        pnl,
        trades,
        bar_returns,
        gross_bar_returns,
        first_bar: warmup,
        equity: full_equity,
    }
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
            ledger: Default::default(),
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
            &BacktestConfig { cost_mult: 0.0, ..Default::default() },
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

    fn choppy(n: usize) -> Vec<Ohlc> {
        // Trend with regular reversals, so a trend follower trades repeatedly.
        let closes: Vec<f64> = (0..n)
            .map(|i| {
                let leg = (i / 40) % 2;
                let t = (i % 40) as f64;
                let base = 100.0 * 1.0015_f64.powi(i as i32);
                if leg == 0 { base * (1.0 + 0.004 * t) } else { base * (1.16 - 0.004 * t) }
            })
            .collect();
        bars_from(&closes)
    }

    #[test]
    fn gross_costs_and_net_are_reported_separately_and_add_up() {
        let bars = choppy(600);
        let r = run(&ema_cross(), "crypto:BTC/USD", "BTC/USD", &bars, &BacktestConfig::default());
        assert!(r.trades.len() >= 2, "the fixture must trade, got {}", r.trades.len());
        assert!(r.pnl.costs > 0.0, "every trade pays something");
        assert!((r.pnl.gross - r.pnl.costs - r.pnl.net).abs() < 1e-12);
        assert!(
            (r.pnl.net - r.stats.total_return).abs() < 1e-9,
            "net is the equity curve's own result: {} vs {}",
            r.pnl.net,
            r.stats.total_return
        );
        // With costs switched off, gross and net are the same number.
        let free = run(
            &ema_cross(),
            "crypto:BTC/USD",
            "BTC/USD",
            &bars,
            &BacktestConfig { cost_mult: 0.0, ..Default::default() },
        );
        assert!(free.pnl.costs.abs() < 1e-12);
        assert!((free.pnl.gross - free.pnl.net).abs() < 1e-12);
    }

    #[test]
    fn the_per_bar_series_compounds_to_the_reported_result() {
        // The forced end-of-sample exit used to be missing from `bar_returns`,
        // so anything pooled from them skipped one exit's costs.
        let bars = choppy(500);
        let r = run(&ema_cross(), "crypto:BTC/USD", "BTC/USD", &bars, &BacktestConfig::default());
        let compounded = r.bar_returns.iter().fold(1.0, |e, x| e * (1.0 + x)) - 1.0;
        assert!((compounded - r.pnl.net).abs() < 1e-9, "{compounded} vs {}", r.pnl.net);
        let gross = r.gross_bar_returns.iter().fold(1.0, |e, x| e * (1.0 + x)) - 1.0;
        assert!((gross - r.pnl.gross).abs() < 1e-9, "{gross} vs {}", r.pnl.gross);
    }

    #[test]
    fn kraken_costs_more_than_binance_and_double_costs_cost_more() {
        let bars = choppy(600);
        let kraken = run(&ema_cross(), "crypto:BTC/USD", "BTC/USD", &bars, &BacktestConfig::default());
        let binance = run(
            &ema_cross(),
            "crypto:BTC/USD",
            "BTC/USD",
            &bars,
            &BacktestConfig { venue: CostVenue::Binance, ..Default::default() },
        );
        assert!(kraken.pnl.costs > binance.pnl.costs, "40 bps taker vs 10");
        let doubled = run(
            &ema_cross(),
            "crypto:BTC/USD",
            "BTC/USD",
            &bars,
            &BacktestConfig { cost_mult: 2.0, ..Default::default() },
        );
        assert!(doubled.pnl.costs > kraken.pnl.costs * 1.9);
        assert!(doubled.pnl.net < kraken.pnl.net);
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
            &BacktestConfig { cost_mult: 0.0, ..Default::default() },
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
            &BacktestConfig { cost_mult: 0.0, ..Default::default() },
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
            cost_mult: 0.0,
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
