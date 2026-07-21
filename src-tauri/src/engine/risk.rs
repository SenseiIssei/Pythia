//! The sovereign risk manager. Every order — paper or live — passes through
//! `evaluate` before routing. It fails closed: any doubt rejects.

use super::{RiskDecision, RiskLimits};
use crate::connectors::{OrderRequest, Side};

/// Live state the risk check needs, supplied by the portfolio ledger.
pub struct RiskContext {
    pub equity: f64,
    pub day_start_equity: f64,
    pub realized_pnl: f64,
    pub unrealized_pnl: f64,
    pub gross_exposure: f64,
    pub position_notional: f64, // for this market
    pub strategy_exposure: f64, // for this strategy
    pub orders_last_min: u32,
    pub data_age_sec: u64,
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
