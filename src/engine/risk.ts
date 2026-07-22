import type { Order, RiskLimits } from "../types";

export interface RiskContext {
  equity: number;
  dayStartEquity: number;
  realizedPnl: number;
  unrealizedPnl: number;
  grossExposure: number; // absolute notional across all positions
  positionNotional: (marketId: string) => number;
  ordersLastMin: (strategyId: string) => number;
  strategyExposure: (strategyId: string) => number;
  dataAgeSec: (marketId: string) => number;
}

export interface RiskDecision {
  approved: boolean;
  reason?: string;
  /** possibly-reduced quantity after sizing caps */
  qty: number;
}

export const DEFAULT_LIMITS: RiskLimits = {
  killSwitch: false,
  maxDailyLossPct: 5,
  maxPositionPct: 15,
  maxGrossExposurePct: 60,
  perStrategyBudgetPct: 20,
  kellyFraction: 0.25,
  maxOrdersPerMin: 10,
  maxDataStalenessSec: 30,
  maxDrawdownPct: 15,
  stopAtrMult: 3,
  takeProfitAtrMult: 5,
  trailingAtrMult: 0,
  maxConsecutiveLosses: 4,
  cooldownSec: 300,
  volTargetPct: 0,
  regimeFilter: false,
};

// The risk manager is sovereign: this is the ONLY path from a strategy intent to
// a routed order. It fails closed — any doubt rejects the order.
export function evaluate(
  order: Order,
  price: number,
  limits: RiskLimits,
  ctx: RiskContext
): RiskDecision {
  const notional = order.qty * price;

  // 1. Kill switch — only closing/flatten intents pass when tripped.
  if (limits.killSwitch && order.side === "buy") {
    return { approved: false, qty: 0, reason: "kill switch active" };
  }

  // 2. Stale data gate.
  const age = ctx.dataAgeSec(order.marketId);
  if (age > limits.maxDataStalenessSec) {
    return { approved: false, qty: 0, reason: `stale data (${age.toFixed(0)}s)` };
  }

  // 3. Daily loss ceiling.
  const dayPnl = ctx.realizedPnl + ctx.unrealizedPnl;
  const dayLossPct = (-dayPnl / ctx.dayStartEquity) * 100;
  if (dayLossPct >= limits.maxDailyLossPct) {
    return {
      approved: false,
      qty: 0,
      reason: `daily loss limit hit (${dayLossPct.toFixed(1)}%)`,
    };
  }

  // 4. Rate limit per strategy.
  if (ctx.ordersLastMin(order.strategyId) >= limits.maxOrdersPerMin) {
    return { approved: false, qty: 0, reason: "order rate limit" };
  }

  // 5. Per-strategy budget.
  const stratCap = (limits.perStrategyBudgetPct / 100) * ctx.equity;
  if (ctx.strategyExposure(order.strategyId) + notional > stratCap) {
    return { approved: false, qty: 0, reason: "strategy budget exceeded" };
  }

  // 6. Per-position cap (may reduce qty rather than reject on buys).
  const posCap = (limits.maxPositionPct / 100) * ctx.equity;
  const curPos = Math.abs(ctx.positionNotional(order.marketId));
  let qty = order.qty;
  if (order.side === "buy" && curPos + notional > posCap) {
    const room = Math.max(0, posCap - curPos);
    if (room <= 0) {
      return { approved: false, qty: 0, reason: "position size cap" };
    }
    qty = room / price;
  }

  // 7. Gross exposure ceiling.
  const grossCap = (limits.maxGrossExposurePct / 100) * ctx.equity;
  if (order.side === "buy" && ctx.grossExposure + qty * price > grossCap) {
    const room = Math.max(0, grossCap - ctx.grossExposure);
    if (room <= 0) {
      return { approved: false, qty: 0, reason: "gross exposure cap" };
    }
    qty = Math.min(qty, room / price);
  }

  if (qty <= 0) return { approved: false, qty: 0, reason: "sized to zero" };
  return { approved: true, qty };
}

/** Fractional-Kelly position sizing, bounded to a sane fraction of equity. */
export function kellySize(
  edge: number, // p_win - p_lose style edge, 0..1
  price: number,
  equity: number,
  limits: RiskLimits
): number {
  const f = Math.max(0, Math.min(1, edge)) * limits.kellyFraction;
  const dollars = f * equity;
  return dollars / price;
}
