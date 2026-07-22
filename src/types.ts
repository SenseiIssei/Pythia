// ── Pythia domain model ───────────────────────────────────────────────────
// Shared between the client-side paper engine and (eventually) the Rust core.
// The Rust DTOs mirror these shapes so the IPC layer is a drop-in swap.

export type Venue = "polymarket" | "crypto" | "alpaca";
export type Mode = "paper" | "live";
export type Side = "buy" | "sell";
export type OrderType = "market" | "limit";
export type OrderStatus = "pending" | "filled" | "partial" | "rejected" | "cancelled";
export type StrategyState = "paper" | "live" | "paused";

export interface Market {
  id: string; // venue-qualified, e.g. "polymarket:will-x-happen"
  venue: Venue;
  symbol: string; // human label, e.g. "BTC/USD" or "Will X win?"
  kind: "prediction" | "crypto" | "equity";
  // For prediction markets, `price` is the implied probability (0..1).
  // For crypto/equity, `price` is the last trade price.
  price: number;
  change24h: number; // fractional, e.g. 0.023 = +2.3%
  // Prediction-only: your current model probability estimate, if any.
  modelProb?: number;
  liquidity?: number;
  regime?: Regime;
  trendStrength?: number; // efficiency ratio 0..1
  updatedAt: number;
}

export type Regime = "trending" | "ranging";

export interface PositionView {
  marketId: string;
  venue: Venue;
  symbol: string;
  qty: number;
  avgPrice: number;
  lastPrice: number;
  unrealized: number;
  mode: Mode;
}

export interface Order {
  id: string;
  ts: number;
  strategyId: string;
  marketId: string;
  venue: Venue;
  side: Side;
  type: OrderType;
  qty: number;
  limitPrice?: number;
  status: OrderStatus;
  filledQty: number;
  avgFillPrice?: number;
  mode: Mode;
  rejectReason?: string;
}

export interface RiskLimits {
  killSwitch: boolean;
  maxDailyLossPct: number; // % of equity
  maxPositionPct: number; // % of equity per market
  maxGrossExposurePct: number; // aggregate across venues
  perStrategyBudgetPct: number; // allowance per strategy
  kellyFraction: number; // 0..1, default 0.25
  maxOrdersPerMin: number;
  maxDataStalenessSec: number;
  // advanced controls
  maxDrawdownPct: number; // peak-to-trough; breach trips the kill switch
  stopAtrMult: number; // per-position stop-loss in ATR units (0 = off)
  takeProfitAtrMult: number; // per-position take-profit in ATR units (0 = off)
  trailingAtrMult: number; // trailing-stop distance in ATR units (0 = off)
  maxConsecutiveLosses: number; // per strategy before cooldown (0 = off)
  cooldownSec: number; // cooldown after the loss streak
  volTargetPct: number; // volatility-targeted sizing: target per-bar vol % (0 = off)
  regimeFilter: boolean; // block mean-reversion in trends & trend strategies in chop
  adaptiveAllocation: boolean; // auto-weight strategy budgets by recent performance
}

export interface StrategyParam {
  key: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
}

export type StrategyKind =
  | "ema-cross"
  | "bollinger"
  | "rsi-reversal"
  | "macd-trend"
  | "breakout"
  | "multi-tf"
  | "pairs"
  | "prob-edge"
  | "composed"
  | "arb"
  | "manual";

// ── composed (user-built rule) strategies ──────────────────────────────────
export type IndKind = "price" | "rsi" | "ema" | "sma" | "zscore" | "roc" | "macdHist" | "atr";

export interface Operand {
  kind: IndKind;
  period: number;
}

export interface Rule {
  left: Operand;
  op: "<" | ">";
  rightMode: "const" | "indicator";
  rightConst: number;
  rightOperand: Operand;
}

export interface Composed {
  direction: "long" | "short";
  rules: Rule[];
}

export interface StrategyConfig {
  id: string;
  name: string;
  kind: StrategyKind;
  venueClass: Venue;
  state: StrategyState;
  universe: string[]; // market ids
  params: StrategyParam[];
  budgetPct: number;
  // running stats
  pnl: number;
  trades: number;
  winRate: number;
  maxDrawdown: number;
  profitFactor: number;
  equityCurve: number[];
  rules?: Composed; // present only for kind === "composed"
}

export type JournalKind =
  | "signal"
  | "order"
  | "fill"
  | "reject"
  | "risk"
  | "system";

export interface JournalEntry {
  id: string;
  ts: number;
  kind: JournalKind;
  strategyId?: string;
  marketId?: string;
  message: string;
  mode: Mode;
}

export interface VenueBalance {
  venue: Venue;
  connected: boolean;
  cash: number;
  equity: number;
  mode: Mode;
}

export interface PortfolioSnapshot {
  mode: Mode;
  cash: number;
  equity: number;
  dayStartEquity: number;
  realizedPnl: number;
  unrealizedPnl: number;
  grossExposure: number;
  equityCurve: number[];
  balances: VenueBalance[];
}
