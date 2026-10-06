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

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use super::{RiskDecision, RiskLimits};
use crate::connectors::{OrderRequest, Side};

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

/// What the risk manager is doing right now, for the Risk page.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RiskStatus {
    /// Correlation-adjusted exposure of the open book, quote currency.
    pub correlated_exposure: f64,
    /// The same as a percentage of equity, next to `maxCorrelatedExposurePct`.
    pub correlated_exposure_pct: f64,
}

impl Default for RiskStatus {
    fn default() -> Self {
        Self { correlated_exposure: 0.0, correlated_exposure_pct: 0.0 }
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

    #[test]
    fn the_largest_entry_lands_exactly_on_the_cap() {
        for (e0, lean) in [(0.0, 0.0), (20_000.0, 5_000.0), (30_000.0, -10_000.0), (39_000.0, 39_000.0)] {
            let t = max_added_notional(e0, lean, 40_000.0);
            assert!((exposure_after(e0, lean, t) - 40_000.0).abs() < 1e-6, "e0 {e0} lean {lean} t {t}");
        }
    }
}
