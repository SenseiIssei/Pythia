//! The sovereign risk manager. Every order — paper or live — passes through
//! `evaluate` before routing. It fails closed: any doubt rejects.
//!
//! Besides the per-order checks it holds the portfolio-level arithmetic the
//! engine sizes with:
//!
//! - **Correlation-adjusted exposure.** Ten crypto longs are one trade with
//!   ten names on it. The book is measured as `E = sqrt(w' C w)`, where `w` is
//!   the signed notional per market (long positive, short negative) and `C` the
//!   return correlation matrix, and `evaluate` caps `E` rather than only the
//!   raw sum of notionals. See [`correlated_exposure`].
//! - **Portfolio volatility target.** The same quadratic form with every
//!   position weighted by its market's annual volatility: one standard
//!   deviation of the book's yearly P&L, capped as a share of equity. See
//!   [`portfolio_vol`].

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use super::{RiskDecision, RiskLimits};
use crate::connectors::{OrderRequest, Side};
use crate::marketdata::Ohlc;

/// Live state the risk check needs, supplied by the portfolio ledger.
pub struct RiskContext {
    pub equity: f64,
    pub day_start_equity: f64,
    pub realized_pnl: f64,
    pub unrealized_pnl: f64,
    pub gross_exposure: f64,
    pub position_notional: f64, // for this market, signed (short is negative)
    pub strategy_exposure: f64, // for this strategy
    pub orders_last_min: u32,
    pub data_age_sec: u64,
    /// Correlation-adjusted exposure of the open book, `sqrt(w' C w)`, in quote
    /// currency. See [`correlated_exposure`].
    pub corr_exposure: f64,
    /// `sum_i rho(this market, i) * w_i` over the open book: how far the book
    /// already leans the way a long in this market would. See
    /// [`correlation_loading`].
    pub corr_loading: f64,
    /// One standard deviation of the open book's annual P&L, quote currency.
    /// See [`portfolio_vol`].
    pub vol_exposure: f64,
    /// [`correlation_loading`] over the volatility-weighted book.
    pub vol_loading: f64,
    /// This market's annual volatility (0.8 = 80 % a year).
    pub market_vol: f64,
}

pub fn evaluate(
    order: &OrderRequest,
    price: f64,
    limits: &RiskLimits,
    ctx: &RiskContext,
) -> RiskDecision {
    let reject = |r: &str| RiskDecision { approved: false, qty: 0.0, reason: Some(r.into()) };
    let notional = order.qty * price;

    // 1. Kill switch — only closing (sell) intents pass when tripped.
    if limits.kill_switch && order.side == Side::Buy {
        return reject("kill switch active");
    }
    // 2. Stale data.
    if ctx.data_age_sec > limits.max_data_staleness_sec {
        return reject("stale market data");
    }
    // 3. Daily loss ceiling.
    let day_pnl = ctx.realized_pnl + ctx.unrealized_pnl;
    let day_loss_pct = (-day_pnl / ctx.day_start_equity) * 100.0;
    if day_loss_pct >= limits.max_daily_loss_pct {
        return reject("daily loss limit hit");
    }
    // 4. Rate limit.
    if ctx.orders_last_min >= limits.max_orders_per_min {
        return reject("order rate limit");
    }
    // 5. Per-strategy budget.
    let strat_cap = (limits.per_strategy_budget_pct / 100.0) * ctx.equity;
    if ctx.strategy_exposure + notional > strat_cap {
        return reject("strategy budget exceeded");
    }

    // 6. Per-position cap — reduce qty rather than reject on buys.
    let mut qty = order.qty;
    let pos_cap = (limits.max_position_pct / 100.0) * ctx.equity;
    if order.side == Side::Buy && ctx.position_notional.abs() + notional > pos_cap {
        let room = (pos_cap - ctx.position_notional.abs()).max(0.0);
        if room <= 0.0 {
            return reject("position size cap");
        }
        qty = room / price;
    }
    // 7. Gross exposure ceiling.
    let gross_cap = (limits.max_gross_exposure_pct / 100.0) * ctx.equity;
    if order.side == Side::Buy && ctx.gross_exposure + qty * price > gross_cap {
        let room = (gross_cap - ctx.gross_exposure).max(0.0);
        if room <= 0.0 {
            return reject("gross exposure cap");
        }
        qty = qty.min(room / price);
    }
    // 8. Correlation-adjusted exposure ceiling. Applies to both sides, because
    // the arithmetic is signed: a short that hedges the book lowers it, one
    // that adds to a short cluster raises it. An order that reduces the
    // position it trades is never stopped here, since closing must always pass
    // (closing one leg of a hedge can raise `E`).
    let reduces = ctx.position_notional != 0.0 && (ctx.position_notional > 0.0) != (order.side == Side::Buy);
    if !reduces && limits.max_correlated_exposure_pct > 0.0 {
        let cap = (limits.max_correlated_exposure_pct / 100.0) * ctx.equity;
        let dir = if order.side == Side::Buy { 1.0 } else { -1.0 };
        let lean = dir * ctx.corr_loading;
        let e0 = ctx.corr_exposure.max(0.0);
        let after = exposure_after(e0, lean, qty * price);
        if after > cap + 1e-9 && after > e0 + 1e-9 {
            let room = max_added_notional(e0, lean, cap);
            // Less than a millionth of equity of room is no room.
            if room <= 0.0 || room <= ctx.equity.abs() * 1e-6 {
                let held = if ctx.equity > 0.0 { e0 / ctx.equity * 100.0 } else { 0.0 };
                return RiskDecision {
                    approved: false,
                    qty: 0.0,
                    reason: Some(format!(
                        "correlated exposure cap: the book already counts as {held:.0}% of equity \
                         once correlation is taken into account, limit {:.0}%",
                        limits.max_correlated_exposure_pct
                    )),
                };
            }
            qty = qty.min(room / price);
        }
    }
    // 9. Portfolio volatility target. Step 8's arithmetic in other units: each
    // notional is weighted by its market's annual volatility, so `E` becomes
    // one standard deviation of a year's P&L. A ceiling only; it never sizes
    // anything up. Closing passes for the same reason as above.
    if !reduces && limits.portfolio_vol_target_pct > 0.0 && ctx.market_vol > 0.0 {
        let cap = (limits.portfolio_vol_target_pct / 100.0) * ctx.equity;
        let dir = if order.side == Side::Buy { 1.0 } else { -1.0 };
        let lean = dir * ctx.vol_loading;
        let e0 = ctx.vol_exposure.max(0.0);
        let after = exposure_after(e0, lean, qty * price * ctx.market_vol);
        if after > cap + 1e-9 && after > e0 + 1e-9 {
            let room = max_added_notional(e0, lean, cap) / ctx.market_vol;
            if room <= 0.0 || room <= ctx.equity.abs() * 1e-6 {
                let held = if ctx.equity > 0.0 { e0 / ctx.equity * 100.0 } else { 0.0 };
                return RiskDecision {
                    approved: false,
                    qty: 0.0,
                    reason: Some(format!(
                        "volatility target: the book already swings about {held:.0}% of equity in a \
                         typical year, target {:.0}%",
                        limits.portfolio_vol_target_pct
                    )),
                };
            }
            qty = qty.min(room / price);
        }
    }

    if qty <= 0.0 {
        return reject("sized to zero");
    }
    RiskDecision { approved: true, qty, reason: None }
}

/// Fractional-Kelly sizing, bounded by the caps in `evaluate`.
pub fn kelly_size(edge: f64, price: f64, equity: f64, limits: &RiskLimits) -> f64 {
    let f = edge.clamp(0.0, 1.0) * limits.kelly_fraction;
    (f * equity) / price
}

// ── correlation-adjusted exposure ───────────────────────────────────────────

/// Closes per market the correlation is measured on: the last 60, the same
/// window the Correlation page gets through `EngineState::history`, so the
/// page and the risk manager look at the same numbers.
pub const CORR_WINDOW: usize = 60;
/// Below this many closes a correlation is unknown. The page hides a market
/// until it has 20 closes; the risk manager does not hide it, it assumes the
/// worst (see [`UNKNOWN_CORRELATION`]).
pub const CORR_MIN_CLOSES: usize = 20;
/// What a correlation the engine cannot measure counts as. 1.0 fails closed:
/// a market without enough history, or whose price has not moved in the
/// window, is treated as the same trade as everything else held.
pub const UNKNOWN_CORRELATION: f64 = 1.0;

/// Simple returns of the last [`CORR_WINDOW`] closes.
fn window_returns(closes: &[f64]) -> Vec<f64> {
    let tail = &closes[closes.len().saturating_sub(CORR_WINDOW)..];
    tail.windows(2).filter(|w| w[0] != 0.0).map(|w| w[1] / w[0] - 1.0).collect()
}

/// Pearson correlation of two markets' simple returns over the last
/// [`CORR_WINDOW`] closes, aligned on their shared tail. The same computation
/// as `src/lib/correlation.ts`, which draws the Correlation page.
///
/// `None` when either series has fewer than [`CORR_MIN_CLOSES`] closes or no
/// variance. The page draws those as 0; the risk manager does not guess low.
pub fn return_correlation(a: &[f64], b: &[f64]) -> Option<f64> {
    let window = |s: &[f64]| s.len().min(CORR_WINDOW);
    if window(a) < CORR_MIN_CLOSES || window(b) < CORR_MIN_CLOSES {
        return None;
    }
    let (ra, rb) = (window_returns(a), window_returns(b));
    let n = ra.len().min(rb.len());
    if n < 3 {
        return None;
    }
    let (ra, rb) = (&ra[ra.len() - n..], &rb[rb.len() - n..]);
    let ma = ra.iter().sum::<f64>() / n as f64;
    let mb = rb.iter().sum::<f64>() / n as f64;
    let (mut cov, mut va, mut vb) = (0.0, 0.0, 0.0);
    for (x, y) in ra.iter().zip(rb) {
        let (dx, dy) = (x - ma, y - mb);
        cov += dx * dy;
        va += dx * dx;
        vb += dy * dy;
    }
    if va == 0.0 || vb == 0.0 {
        return None;
    }
    Some((cov / (va * vb).sqrt()).clamp(-1.0, 1.0))
}

/// Correlation between two markets as the risk manager uses it: 1 on the
/// diagonal, the measured return correlation where there is one, and
/// [`UNKNOWN_CORRELATION`] where there is not.
pub fn pair_correlation(history: &HashMap<String, Vec<f64>>, a: &str, b: &str) -> f64 {
    if a == b {
        return 1.0;
    }
    match (history.get(a), history.get(b)) {
        (Some(x), Some(y)) => return_correlation(x, y).unwrap_or(UNKNOWN_CORRELATION),
        _ => UNKNOWN_CORRELATION,
    }
}

/// Correlation-adjusted exposure of a book of signed notionals:
///
/// ```text
/// E = sqrt( max(0, sum_i sum_j w_i * w_j * rho_ij) )
/// ```
///
/// with `w_i` the signed notional in market `i` and `rho_ij` from
/// [`pair_correlation`]. Ten equal longs of size `x` give `E = 10x` when they
/// move as one (rho = 1, the raw gross), `sqrt(10) * x` when independent, and
/// a long hedged by a short in a market that moves with it gives close to 0.
/// The pairwise matrix is estimated pair by pair with fallbacks, so it is not
/// guaranteed positive semi-definite; the `max(0, ..)` keeps `E` real.
pub fn correlated_exposure(book: &[(String, f64)], history: &HashMap<String, Vec<f64>>) -> f64 {
    let mut q = 0.0;
    for (i, (a, wa)) in book.iter().enumerate() {
        q += wa * wa;
        for (b, wb) in &book[i + 1..] {
            q += 2.0 * wa * wb * pair_correlation(history, a, b);
        }
    }
    q.max(0.0).sqrt()
}

/// `sum_i rho(market, i) * w_i` over the book. Adding a signed notional `t` in
/// `market` moves the quadratic form from `E^2` to `E^2 + 2 t L + t^2`, where
/// `L` is this loading (it includes the market's own position with rho = 1).
pub fn correlation_loading(book: &[(String, f64)], market: &str, history: &HashMap<String, Vec<f64>>) -> f64 {
    book.iter().map(|(id, w)| pair_correlation(history, market, id) * w).sum()
}

/// `E` after adding notional `t >= 0` in the direction whose loading is `lean`.
fn exposure_after(e0: f64, lean: f64, t: f64) -> f64 {
    (e0 * e0 + 2.0 * lean * t + t * t).max(0.0).sqrt()
}

/// The largest notional `t >= 0` that keeps `E` at or below `max(cap, E0)`:
/// solves `t^2 + 2 lean t + E0^2 - L^2 = 0` with `L = max(cap, E0)`, which
/// gives `t = -lean + sqrt(lean^2 + L^2 - E0^2)`. Above the cap already, that
/// leaves only orders that bring `E` down (`t <= -2 lean`, a hedge).
fn max_added_notional(e0: f64, lean: f64, cap: f64) -> f64 {
    let l = cap.max(e0);
    (-lean + (lean * lean + l * l - e0 * e0).max(0.0).sqrt()).max(0.0)
}

// ── Portfolio volatility target ─────────────────────────────────────────────
//
// The per-position target (`volTargetPct`) sizes each entry on its own
// market's swings. It cannot see that ten coins at a comfortable size each
// still swing the account like one large coin when they move together. This
// one measures the book:
//
//   u_i      = w_i * sigma_i      signed notional times the market's annual vol
//   sigma_p  = sqrt(u' C u)       C: the same correlations as the cap above
//
// sigma_p is one standard deviation of the book's P&L over a year, in quote
// currency; over equity it is how much the account swings in a typical year.
// A 30 % target means a bad year (two standard deviations) costs about 60 %,
// a bad month about 17 %.

/// Daily volatility assumed for a market whose own cannot be measured yet (no
/// real candles): 5 % a day, a typical altcoin. Like an unmeasurable
/// correlation it errs toward caution.
pub const UNKNOWN_DAILY_VOL: f64 = 0.05;
const DAY_MS: f64 = 86_400_000.0;

/// Annual volatility assumed when it cannot be measured.
pub fn unknown_annual_vol() -> f64 {
    UNKNOWN_DAILY_VOL * 365f64.sqrt()
}

/// Trading time in a year, in milliseconds: crypto never closes, US equities
/// have 252 sessions of 6.5 hours. Scaling a bar's volatility by wall-clock
/// time would count every night and weekend as a bar that never happened.
fn trading_ms_per_year(always_open: bool) -> f64 {
    if always_open { 365.0 * DAY_MS } else { 252.0 * 6.5 * 3_600_000.0 }
}

/// Annual volatility of a market from its real candles: the standard
/// deviation of bar returns over the last [`CORR_WINDOW`] bars, times the
/// square root of bars per trading year. The bar length is the median gap
/// between bar times, so a missing bar does not change the scale. `None`
/// below [`CORR_MIN_CLOSES`] bars.
pub fn annual_vol(bars: &[Ohlc], always_open: bool) -> Option<f64> {
    let tail = &bars[bars.len().saturating_sub(CORR_WINDOW)..];
    if tail.len() < CORR_MIN_CLOSES {
        return None;
    }
    let mut gaps: Vec<f64> = tail.windows(2).map(|w| (w[1].ts - w[0].ts) as f64).filter(|g| *g > 0.0).collect();
    if gaps.is_empty() {
        return None;
    }
    gaps.sort_by(|a, b| a.total_cmp(b));
    let bar_ms = gaps[gaps.len() / 2];
    let closes: Vec<f64> = tail.iter().map(|b| b.close).collect();
    let rets = window_returns(&closes);
    let n = rets.len() as f64;
    let mean = rets.iter().sum::<f64>() / n;
    let var = rets.iter().map(|r| (r - mean) * (r - mean)).sum::<f64>() / n;
    let vol = (var * trading_ms_per_year(always_open) / bar_ms).sqrt();
    (vol.is_finite() && vol > 0.0).then_some(vol)
}

/// The book with each notional multiplied by its market's annual volatility;
/// a market missing from `vols` gets [`unknown_annual_vol`].
pub fn vol_weighted(book: &[(String, f64)], vols: &HashMap<String, f64>) -> Vec<(String, f64)> {
    book.iter()
        .map(|(id, w)| (id.clone(), w * vols.get(id).copied().unwrap_or_else(unknown_annual_vol)))
        .collect()
}

/// One standard deviation of the book's annual P&L, `sqrt(u' C u)`, in quote
/// currency. See the section comment above.
pub fn portfolio_vol(book: &[(String, f64)], vols: &HashMap<String, f64>, history: &HashMap<String, Vec<f64>>) -> f64 {
    correlated_exposure(&vol_weighted(book, vols), history)
}

// ── Kelly on measured edge ──────────────────────────────────────────────────
//
// A strategy's signal strength (`SignalIntent::confidence`) is an indicator
// reading, not a win probability. Once a strategy has a record, it is sized
// on that record instead:
//
//   p      = wins / n                      (a win is a trade with net return > 0)
//   b      = avg win / avg loss            (net returns on entry notional)
//   f      = p - (1 - p) / b               (full Kelly, the share of equity an
//                                           average loss may cost)
//   f_s    = f * n / (n + 30)              (shrunk toward a prior of no edge;
//                                           at 30 trades it is half the measured
//                                           value, at 90 three quarters)
//   stake  = min(kellyFraction, 0.25) * f_s * equity
//   entry  = stake / avg loss / universe size
//
// The stake is what an average losing trade is allowed to cost, so the
// notional is the stake divided by the average loss on notional. It is split
// across the strategy's universe because those positions run at the same
// time, the same way the budget is. The engine then takes the smaller of this
// and what today's sizing would give at full confidence, so measured edge can
// only keep or cut a position, never grow it past the per-strategy budget.
//
// Below 30 trades nothing changes: the confidence-based sizing runs as before.
// `f_s <= 0` means the strategy has no measured edge and is sized to zero.

/// Closed trades a strategy needs before it is sized on its own record.
pub const MIN_EDGE_TRADES: u32 = 30;
/// Weight of the no-edge prior, in trades: the measured Kelly is multiplied by
/// `n / (n + EDGE_PRIOR_TRADES)`.
pub const EDGE_PRIOR_TRADES: f64 = 30.0;
/// The largest share of measured Kelly ever applied: quarter Kelly, whatever
/// `kellyFraction` is set to.
pub const MAX_KELLY_FRACTION: f64 = 0.25;

/// A strategy's closed-trade record in the units Kelly needs: how often it
/// won, and how much it made or lost per unit of notional when it did.
///
/// Returns are net: realised P&L at fill prices (slippage included) minus an
/// estimated round-trip fee, over the entry notional of the part that closed.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct EdgeRecord {
    pub wins: u32,
    pub losses: u32,
    /// Sum of the winning trades' net returns (fractions of notional).
    pub win_return_sum: f64,
    /// Sum of the losing trades' net losses, as positive fractions of notional.
    pub loss_return_sum: f64,
}

impl EdgeRecord {
    /// Book one closed trade's net return on its entry notional.
    pub fn record(&mut self, net_return: f64) {
        if !net_return.is_finite() {
            return;
        }
        if net_return > 0.0 {
            self.wins += 1;
            self.win_return_sum += net_return;
        } else {
            self.losses += 1;
            self.loss_return_sum += -net_return;
        }
    }

    pub fn trades(&self) -> u32 {
        self.wins + self.losses
    }

    /// The Kelly numbers for this record, whatever its size. `edge_sizing`
    /// decides whether there are enough trades to use them.
    pub fn estimate(&self) -> Option<KellyEstimate> {
        let n = self.trades();
        if n == 0 {
            return None;
        }
        let p = self.wins as f64 / n as f64;
        let avg_win = if self.wins > 0 { self.win_return_sum / self.wins as f64 } else { 0.0 };
        let avg_loss = if self.losses > 0 { self.loss_return_sum / self.losses as f64 } else { 0.0 };
        let (payoff, raw) = if avg_loss <= 0.0 {
            // Nothing lost yet: b is unbounded and f = p.
            (None, p)
        } else if avg_win <= 0.0 {
            // Nothing won: every bet loses.
            (Some(0.0), -1.0)
        } else {
            let b = avg_win / avg_loss;
            (Some(b), (p - (1.0 - p) / b).max(-1.0))
        };
        let shrunk = raw * n as f64 / (n as f64 + EDGE_PRIOR_TRADES);
        Some(KellyEstimate { trades: n, win_rate: p, payoff, avg_loss, raw, shrunk })
    }
}

/// Kelly numbers for one strategy's record.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct KellyEstimate {
    pub trades: u32,
    pub win_rate: f64,
    /// Average win over average loss; `None` while there has been no loss.
    pub payoff: Option<f64>,
    /// Average net loss on notional, positive (0 while there has been none).
    pub avg_loss: f64,
    /// `p - (1 - p) / b`.
    pub raw: f64,
    /// `raw * n / (n + 30)`.
    pub shrunk: f64,
}

/// How a strategy's entries are sized right now.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum SizingMode {
    /// Fewer than 30 closed trades: sized off signal strength, as before.
    Confidence,
    /// Sized on the measured win rate and payoff.
    Measured,
    /// A record that shows no edge: entries are sized to zero.
    NoEdge,
}

/// Which sizing applies to a record, with the numbers behind it.
pub fn edge_sizing(edge: &EdgeRecord) -> (SizingMode, Option<KellyEstimate>) {
    let est = edge.estimate();
    match est {
        Some(k) if k.trades >= MIN_EDGE_TRADES => {
            let mode = if k.shrunk > 0.0 { SizingMode::Measured } else { SizingMode::NoEdge };
            (mode, est)
        }
        _ => (SizingMode::Confidence, est),
    }
}

/// Entry notional a measured edge supports (see the comment above
/// [`MIN_EDGE_TRADES`]). Zero without an edge, unbounded when the record has
/// no losses to size against, in which case the engine's cap decides.
pub fn kelly_notional(est: &KellyEstimate, equity: f64, kelly_fraction: f64, slots: f64) -> f64 {
    if est.shrunk <= 0.0 || equity <= 0.0 {
        return 0.0;
    }
    if est.avg_loss <= 0.0 {
        return f64::INFINITY;
    }
    let frac = kelly_fraction.clamp(0.0, MAX_KELLY_FRACTION);
    frac * est.shrunk * equity / est.avg_loss / slots.max(1.0)
}

// ── drawdown de-risking ─────────────────────────────────────────────────────

/// Size multiplier for new entries while the book is in a drawdown. Linear in
/// how much of the drawdown limit is used up:
///
/// ```text
/// factor = clamp(1 - drawdown / maxDrawdown, 0, 1)
/// ```
///
/// Full size at the equity peak, half at 50 % of the limit, a quarter at 75 %,
/// and nothing new at the breaker, which trips the kill switch there anyway.
/// This is the proportional rule (exposure in proportion to the cushion left
/// above the floor) rather than steps, so there is no cliff where the size
/// halves between two ticks. `maxDrawdown <= 0` turns it off with the breaker.
pub fn derisk_factor(drawdown_pct: f64, max_drawdown_pct: f64) -> f64 {
    if max_drawdown_pct <= 0.0 || !drawdown_pct.is_finite() {
        return 1.0;
    }
    (1.0 - drawdown_pct.max(0.0) / max_drawdown_pct).clamp(0.0, 1.0)
}

/// One strategy's sizing, for the Risk page.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StrategySizing {
    pub strategy_id: String,
    pub mode: SizingMode,
    /// Closed trades on the edge record.
    pub trades: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub win_rate: Option<f64>,
    /// Average win over average loss; absent while there has been no loss.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub payoff: Option<f64>,
    /// Full Kelly from the record, `p - (1 - p) / b`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kelly: Option<f64>,
    /// After shrinking toward no edge, `kelly * n / (n + 30)`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kelly_shrunk: Option<f64>,
}

impl StrategySizing {
    pub fn of(strategy_id: &str, edge: &EdgeRecord) -> Self {
        let (mode, est) = edge_sizing(edge);
        Self {
            strategy_id: strategy_id.to_string(),
            mode,
            trades: edge.trades(),
            win_rate: est.map(|k| k.win_rate),
            payoff: est.and_then(|k| k.payoff),
            kelly: est.map(|k| k.raw),
            kelly_shrunk: est.map(|k| k.shrunk),
        }
    }
}

/// What the risk manager is doing right now, for the Risk page.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RiskStatus {
    /// Correlation-adjusted exposure of the open book, quote currency.
    pub correlated_exposure: f64,
    /// The same as a percentage of equity, next to `maxCorrelatedExposurePct`.
    pub correlated_exposure_pct: f64,
    /// How each strategy's entries are sized.
    #[serde(default)]
    pub sizing: Vec<StrategySizing>,
    /// Peak-to-now equity drawdown, % (the one the breaker watches).
    #[serde(default)]
    pub drawdown_pct: f64,
    /// What new entries are multiplied by because of it, see [`derisk_factor`].
    #[serde(default = "one")]
    pub derisk_factor: f64,
    /// One standard deviation of the book's annual P&L, quote currency.
    #[serde(default)]
    pub portfolio_vol: f64,
    /// The same as % of equity, next to `portfolioVolTargetPct`.
    #[serde(default)]
    pub portfolio_vol_pct: f64,
    /// Open markets whose volatility is assumed, not measured (no candles).
    #[serde(default)]
    pub vol_assumed: Vec<String>,
}

fn one() -> f64 {
    1.0
}

impl Default for RiskStatus {
    fn default() -> Self {
        Self {
            correlated_exposure: 0.0,
            correlated_exposure_pct: 0.0,
            sizing: Vec::new(),
            drawdown_pct: 0.0,
            derisk_factor: 1.0,
            portfolio_vol: 0.0,
            portfolio_vol_pct: 0.0,
            vol_assumed: Vec::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::connectors::OrderType;

    fn ctx() -> RiskContext {
        RiskContext {
            equity: 100_000.0,
            day_start_equity: 100_000.0,
            realized_pnl: 0.0,
            unrealized_pnl: 0.0,
            gross_exposure: 0.0,
            position_notional: 0.0,
            strategy_exposure: 0.0,
            orders_last_min: 0,
            data_age_sec: 0,
            corr_exposure: 0.0,
            corr_loading: 0.0,
            vol_exposure: 0.0,
            vol_loading: 0.0,
            market_vol: 0.0,
        }
    }

    fn buy(qty: f64) -> OrderRequest {
        order(Side::Buy, qty)
    }

    fn order(side: Side, qty: f64) -> OrderRequest {
        OrderRequest {
            symbol: "X".into(),
            side,
            order_type: OrderType::Market,
            qty,
            limit_price: None,
            ref_price: Some(1.0),
            client_order_id: None,
            reduce_only: false,
        }
    }

    /// A series whose returns are `shock(i)` with a common trend underneath.
    fn series(n: usize, shock: impl Fn(usize) -> f64) -> Vec<f64> {
        let mut p = 100.0;
        (0..n)
            .map(|i| {
                p *= 1.0 + shock(i);
                p
            })
            .collect()
    }

    fn wiggle(i: usize) -> f64 {
        // deterministic, irregular, mean roughly zero
        ((i as f64 * 1.7).sin() + (i as f64 * 0.31).cos() * 0.5) * 0.01
    }

    fn other_wiggle(i: usize) -> f64 {
        ((i as f64 * 2.9 + 1.0).sin() - (i as f64 * 0.77).cos() * 0.4) * 0.01
    }

    #[test]
    fn correlation_matches_the_page_on_identical_and_opposite_moves() {
        let a = series(60, wiggle);
        let b = series(60, wiggle);
        let c = series(60, |i| -wiggle(i));
        assert!((return_correlation(&a, &b).unwrap() - 1.0).abs() < 1e-9);
        assert!(return_correlation(&a, &c).unwrap() < -0.99);
    }

    #[test]
    fn a_short_or_flat_history_is_unknown_and_counts_as_fully_correlated() {
        let mut h = HashMap::new();
        h.insert("a".to_string(), series(60, wiggle));
        h.insert("short".to_string(), series(10, wiggle));
        h.insert("flat".to_string(), vec![100.0; 60]);
        assert!(return_correlation(&h["a"], &h["short"]).is_none());
        assert!(return_correlation(&h["a"], &h["flat"]).is_none());
        assert_eq!(pair_correlation(&h, "a", "short"), UNKNOWN_CORRELATION);
        assert_eq!(pair_correlation(&h, "a", "flat"), UNKNOWN_CORRELATION);
        assert_eq!(pair_correlation(&h, "a", "missing"), UNKNOWN_CORRELATION);
        assert_eq!(pair_correlation(&h, "a", "a"), 1.0);
    }

    #[test]
    fn ten_longs_that_move_together_are_one_trade() {
        let mut h = HashMap::new();
        let book: Vec<(String, f64)> = (0..10)
            .map(|i| {
                let id = format!("coin{i}");
                h.insert(id.clone(), series(60, wiggle));
                (id, 5_000.0)
            })
            .collect();
        // Moving as one, the book is its gross: 50k.
        assert!((correlated_exposure(&book, &h) - 50_000.0).abs() < 1.0);
    }

    #[test]
    fn independent_positions_add_up_like_a_square_root() {
        let mut h = HashMap::new();
        h.insert("a".to_string(), series(60, wiggle));
        h.insert("b".to_string(), series(60, other_wiggle));
        let rho = pair_correlation(&h, "a", "b");
        assert!(rho.abs() < 0.5, "test series should be close to independent, got {rho}");
        let book = vec![("a".to_string(), 3_000.0), ("b".to_string(), 4_000.0)];
        let want = (9e6 + 16e6 + 2.0 * 12e6 * rho).sqrt();
        assert!((correlated_exposure(&book, &h) - want).abs() < 1e-6);
    }

    #[test]
    fn a_hedge_cancels_out() {
        let mut h = HashMap::new();
        h.insert("a".to_string(), series(60, wiggle));
        h.insert("b".to_string(), series(60, wiggle));
        let book = vec![("a".to_string(), 10_000.0), ("b".to_string(), -10_000.0)];
        assert!(correlated_exposure(&book, &h) < 1.0);
    }

    #[test]
    fn an_entry_into_a_correlated_book_is_downsized_to_the_cap() {
        // Book: 35k of longs that move as one with the new market. Cap 40%
        // of 100k = 40k, so only 5k more fits.
        let mut c = ctx();
        c.gross_exposure = 35_000.0;
        c.corr_exposure = 35_000.0;
        c.corr_loading = 35_000.0;
        let limits = RiskLimits::default();
        let d = evaluate(&buy(10_000.0), 1.0, &limits, &c);
        assert!(d.approved);
        assert!((d.qty - 5_000.0).abs() < 1e-6, "got {}", d.qty);
    }

    #[test]
    fn a_full_correlated_book_refuses_with_a_reason() {
        let mut c = ctx();
        c.gross_exposure = 45_000.0;
        c.corr_exposure = 45_000.0;
        c.corr_loading = 45_000.0;
        let d = evaluate(&buy(1_000.0), 1.0, &RiskLimits::default(), &c);
        assert!(!d.approved);
        let why = d.reason.unwrap();
        assert!(why.starts_with("correlated exposure cap"), "{why}");
        assert!(why.contains("45%") && why.contains("40%"), "{why}");
    }

    #[test]
    fn an_uncorrelated_entry_passes_where_the_raw_sum_would_bind() {
        // 35k held in something unrelated (loading 0): adding 10k gives
        // sqrt(35^2 + 10^2) = 36.4k, under the 40k cap.
        let mut c = ctx();
        c.gross_exposure = 35_000.0;
        c.corr_exposure = 35_000.0;
        c.corr_loading = 0.0;
        let d = evaluate(&buy(10_000.0), 1.0, &RiskLimits::default(), &c);
        assert!(d.approved);
        assert!((d.qty - 10_000.0).abs() < 1e-9);
    }

    #[test]
    fn a_hedging_short_passes_even_above_the_cap() {
        let mut c = ctx();
        c.corr_exposure = 50_000.0;
        c.corr_loading = 50_000.0; // the new market moves with the book
        let d = evaluate(&order(Side::Sell, 10_000.0), 1.0, &RiskLimits::default(), &c);
        assert!(d.approved, "{:?}", d.reason);
        assert!((d.qty - 10_000.0).abs() < 1e-9);
    }

    /// A book of `held` notional at 80 % a year that moves as one with the
    /// market being bought (loading equals exposure).
    fn vol_book(held: f64) -> RiskContext {
        let mut c = ctx();
        c.gross_exposure = held;
        c.vol_exposure = held * 0.8;
        c.vol_loading = held * 0.8;
        c.market_vol = 0.8;
        c
    }

    #[test]
    fn an_entry_that_would_lift_the_book_over_its_vol_target_is_downsized() {
        // 30k at 80 % swings 24k a year; the target is 30 % of 100k = 30k, so
        // 6k of swing is left, which is 7.5k of notional at 80 %.
        let d = evaluate(&buy(10_000.0), 1.0, &RiskLimits::default(), &vol_book(30_000.0));
        assert!(d.approved);
        assert!((d.qty - 7_500.0).abs() < 1e-6, "got {}", d.qty);
    }

    #[test]
    fn a_calm_market_fits_where_a_wild_one_does_not() {
        // Same book, but the new market moves 20 % a year: 6k of swing is
        // 30k of notional, so the whole 10k order passes.
        let mut c = vol_book(30_000.0);
        c.market_vol = 0.2;
        c.vol_loading = 30_000.0 * 0.2; // rho 1 against the book, in its own units
        let d = evaluate(&buy(10_000.0), 1.0, &RiskLimits::default(), &c);
        assert!(d.approved);
        assert!((d.qty - 10_000.0).abs() < 1e-9, "got {}", d.qty);
    }

    #[test]
    fn a_book_at_its_vol_target_refuses_new_risk_with_a_reason() {
        let mut c = ctx();
        c.vol_exposure = 35_000.0;
        c.vol_loading = 35_000.0;
        c.market_vol = 0.8;
        let d = evaluate(&buy(1_000.0), 1.0, &RiskLimits::default(), &c);
        assert!(!d.approved);
        let why = d.reason.unwrap();
        assert!(why.starts_with("volatility target"), "{why}");
        assert!(why.contains("35%") && why.contains("30%"), "{why}");
    }

    #[test]
    fn closing_and_a_zero_target_are_never_stopped_by_the_vol_target() {
        let mut c = ctx();
        c.position_notional = 10_000.0;
        c.vol_exposure = 60_000.0;
        c.vol_loading = 60_000.0;
        c.market_vol = 0.8;
        let d = evaluate(&order(Side::Sell, 10_000.0), 1.0, &RiskLimits::default(), &c);
        assert!(d.approved, "{:?}", d.reason);

        let off = RiskLimits { portfolio_vol_target_pct: 0.0, ..RiskLimits::default() };
        c.position_notional = 0.0;
        let d = evaluate(&buy(1_000.0), 1.0, &off, &c);
        assert!(d.approved, "{:?}", d.reason);
    }

    /// Bars `gap_ms` apart whose returns alternate between +r and -r exactly.
    fn zigzag(n: usize, r: f64, gap_ms: i64) -> Vec<Ohlc> {
        let mut p = 100.0;
        (0..n)
            .map(|i| {
                if i > 0 {
                    p *= if i % 2 == 1 { 1.0 + r } else { 1.0 - r };
                }
                Ohlc { ts: i as i64 * gap_ms, open: p, high: p, low: p, close: p, volume: 1.0 }
            })
            .collect()
    }

    #[test]
    fn annual_vol_scales_bar_vol_by_trading_time_not_wall_clock() {
        let five_min = 300_000;
        let bars = zigzag(61, 0.002, five_min);
        // 60 returns of +-0.2 %: per-bar sd 0.2 %. Crypto: 105,120 bars a year.
        let crypto = annual_vol(&bars, true).unwrap();
        assert!((crypto - 0.002 * 105_120f64.sqrt()).abs() < 1e-3, "{crypto}");
        // Equities trade 252 x 6.5 h, so the same bars are fewer per year.
        let equity = annual_vol(&bars, false).unwrap();
        let ratio = crypto / equity;
        assert!((ratio - (365.0 * 24.0 / (252.0 * 6.5f64)).sqrt()).abs() < 1e-9, "{ratio}");
    }

    #[test]
    fn a_missing_bar_does_not_change_the_bar_length() {
        let mut bars = zigzag(61, 0.002, 300_000);
        let whole = annual_vol(&bars, true).unwrap();
        for b in bars.iter_mut().skip(30) {
            b.ts += 300_000; // one bar never arrived
        }
        assert!((annual_vol(&bars, true).unwrap() - whole).abs() < 1e-12);
        assert!(annual_vol(&bars[..10], true).is_none(), "too few bars is unknown, not zero");
    }

    #[test]
    fn portfolio_vol_weights_each_position_by_its_market() {
        let moves = series(60, wiggle);
        let history: HashMap<String, Vec<f64>> =
            [("a".to_string(), moves.clone()), ("b".to_string(), moves)].into_iter().collect();
        let book = vec![("a".to_string(), 10_000.0), ("b".to_string(), 10_000.0)];
        let vols: HashMap<String, f64> = [("a".to_string(), 0.5), ("b".to_string(), 1.0)].into_iter().collect();
        // They move as one: 10k x 0.5 + 10k x 1.0.
        assert!((portfolio_vol(&book, &vols, &history) - 15_000.0).abs() < 1e-6);
        // Without a measurement, a market counts as 5 % a day.
        let only_a: HashMap<String, f64> = [("a".to_string(), 0.5)].into_iter().collect();
        let assumed = 5_000.0 + 10_000.0 * unknown_annual_vol();
        assert!((portfolio_vol(&book, &only_a, &history) - assumed).abs() < 1e-6);
    }

    #[test]
    fn closing_is_never_stopped_by_the_correlation_cap() {
        // Selling a held long: even if it is one leg of a hedge, it passes.
        let mut c = ctx();
        c.position_notional = 10_000.0;
        c.corr_exposure = 60_000.0;
        c.corr_loading = -50_000.0;
        let d = evaluate(&order(Side::Sell, 10_000.0), 1.0, &RiskLimits::default(), &c);
        assert!(d.approved, "{:?}", d.reason);
    }

    #[test]
    fn zero_turns_the_correlation_cap_off() {
        let mut c = ctx();
        c.corr_exposure = 90_000.0;
        c.corr_loading = 90_000.0;
        let limits = RiskLimits { max_correlated_exposure_pct: 0.0, max_gross_exposure_pct: 100.0, ..RiskLimits::default() };
        assert!(evaluate(&buy(1_000.0), 1.0, &limits, &c).approved);
    }

    fn record(wins: u32, avg_win: f64, losses: u32, avg_loss: f64) -> EdgeRecord {
        let mut r = EdgeRecord::default();
        for _ in 0..wins {
            r.record(avg_win);
        }
        for _ in 0..losses {
            r.record(-avg_loss);
        }
        r
    }

    #[test]
    fn kelly_is_p_minus_q_over_b_shrunk_by_n_over_n_plus_30() {
        // 60% wins, wins twice the size of losses: f = 0.6 - 0.4 / 2 = 0.4.
        let k = record(18, 0.04, 12, 0.02).estimate().unwrap();
        assert_eq!(k.trades, 30);
        assert!((k.win_rate - 0.6).abs() < 1e-12);
        assert!((k.payoff.unwrap() - 2.0).abs() < 1e-9);
        assert!((k.raw - 0.4).abs() < 1e-9);
        assert!((k.shrunk - 0.2).abs() < 1e-9, "30 trades is half weight");
        let k90 = record(54, 0.04, 36, 0.02).estimate().unwrap();
        assert!((k90.shrunk - 0.3).abs() < 1e-9, "90 trades is three quarters weight");
    }

    #[test]
    fn below_thirty_trades_sizing_stays_on_confidence() {
        let (mode, est) = edge_sizing(&record(17, 0.04, 12, 0.02));
        assert_eq!(mode, SizingMode::Confidence);
        assert!(est.is_some(), "the numbers are still shown");
        assert_eq!(edge_sizing(&EdgeRecord::default()).0, SizingMode::Confidence);
    }

    #[test]
    fn a_negative_measured_kelly_is_no_edge_and_sizes_to_zero() {
        // 40% wins at the same size as the losses: f = 0.4 - 0.6 = -0.2.
        let r = record(12, 0.02, 18, 0.02);
        let (mode, est) = edge_sizing(&r);
        assert_eq!(mode, SizingMode::NoEdge);
        let k = est.unwrap();
        assert!((k.raw + 0.2).abs() < 1e-9);
        assert_eq!(kelly_notional(&k, 100_000.0, 0.25, 1.0), 0.0);
        // Never a winner at all is no edge either.
        assert_eq!(edge_sizing(&record(0, 0.0, 30, 0.01)).0, SizingMode::NoEdge);
    }

    #[test]
    fn kelly_notional_is_the_stake_over_the_average_loss_split_across_the_universe() {
        let k = record(18, 0.04, 12, 0.02).estimate().unwrap(); // shrunk 0.2, avg loss 2%
        // quarter Kelly: 0.25 * 0.2 * 100k = 5k at risk, / 2% = 250k, / 5 slots = 50k
        assert!((kelly_notional(&k, 100_000.0, 0.25, 5.0) - 50_000.0).abs() < 1e-6);
        // a lower fraction is honoured
        assert!((kelly_notional(&k, 100_000.0, 0.1, 5.0) - 20_000.0).abs() < 1e-6);
        // a higher one is not: quarter Kelly is the ceiling
        assert!((kelly_notional(&k, 100_000.0, 1.0, 5.0) - 50_000.0).abs() < 1e-6);
    }

    #[test]
    fn a_record_without_losses_leaves_the_size_to_the_cap() {
        let k = record(30, 0.01, 0, 0.0).estimate().unwrap();
        assert_eq!(k.payoff, None);
        assert!((k.raw - 1.0).abs() < 1e-12);
        assert!(kelly_notional(&k, 100_000.0, 0.25, 5.0).is_infinite());
    }

    #[test]
    fn a_breakeven_trade_counts_as_a_loss() {
        let mut r = EdgeRecord::default();
        r.record(0.0);
        r.record(f64::NAN);
        assert_eq!((r.wins, r.losses), (0, 1));
    }

    #[test]
    fn size_halves_at_half_the_drawdown_limit_and_reaches_zero_at_the_breaker() {
        assert_eq!(derisk_factor(0.0, 15.0), 1.0);
        assert!((derisk_factor(3.75, 15.0) - 0.75).abs() < 1e-12);
        assert!((derisk_factor(7.5, 15.0) - 0.5).abs() < 1e-12);
        assert!((derisk_factor(11.25, 15.0) - 0.25).abs() < 1e-12);
        assert_eq!(derisk_factor(15.0, 15.0), 0.0);
        assert_eq!(derisk_factor(20.0, 15.0), 0.0);
        // a new high (negative drawdown) is full size, and no limit is no de-risking
        assert_eq!(derisk_factor(-1.0, 15.0), 1.0);
        assert_eq!(derisk_factor(10.0, 0.0), 1.0);
    }

    #[test]
    fn the_largest_entry_lands_exactly_on_the_cap() {
        for (e0, lean) in [(0.0, 0.0), (20_000.0, 5_000.0), (30_000.0, -10_000.0), (39_000.0, 39_000.0)] {
            let t = max_added_notional(e0, lean, 40_000.0);
            assert!((exposure_after(e0, lean, t) - 40_000.0).abs() < 1e-6, "e0 {e0} lean {lean} t {t}");
        }
    }
}
