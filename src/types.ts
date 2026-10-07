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
  /** Opened with a real venue fill — closing it needs live routing. */
  live: boolean;
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
  /** Live fills only: fill against arrival price in bps, positive = it cost us. */
  realisedSlippageBps?: number;
  /** Live fills only: what the cost model expected. */
  modelledSlippageBps?: number;
}

// ── costs ────────────────────────────────────────────────────────────────────
/** A key in `config/costs.json`. Crypto is charged as the selected exchange. */
export type CostVenue = "kraken" | "binance" | "bybit" | "okx" | "coinbase" | "alpaca" | "polymarket";

/** Costs for one instrument on one venue. Mirrors Rust `costs::CostModel`. */
export interface CostModel {
  takerBps: number;
  makerBps: number;
  /** Per side: what a taker pays against the mid. */
  halfSpreadBps: number;
  /** Impact in bps when notional equals top-of-book depth; scaled by sqrt(notional / depth). */
  impactCoeff: number;
  borrowBpsYr: number;
  minNotional: number;
  /** Top-of-book depth assumed when no live book is known. */
  defaultDepth: number;
}

/** Gross, costs and net as three figures that always add up. Mirrors Rust `PnlBreakdown`. */
export interface PnlBreakdown {
  gross: number;
  costs: number;
  net: number;
  /** costs / gross, when gross is positive. */
  costShare?: number;
  /** Costs above 40 % of gross, or costs paid on no gross profit. */
  costHeavy: boolean;
}

/** What a strategy has paid to trade, and its forward-test record. Mirrors Rust `StrategyLedger`. */
export interface StrategyLedger {
  fees: number;
  /** Slippage against the reference price on every fill, open positions included. */
  slippage: number;
  /** Realised P&L of the closed trades at reference prices. */
  gross: number;
  pnl: PnlBreakdown;
  paperSince?: number;
  /** Closed paper trades on real prices (demo-simulator trades do not count). */
  forwardTrades: number;
  liveTrades: number;
  /** Closed-trade record in net returns on notional; sizes entries from 30 trades. */
  edge?: EdgeRecord;
}

/** Mirrors Rust `risk::EdgeRecord`. A win is a trade with net return > 0. */
export interface EdgeRecord {
  wins: number;
  losses: number;
  /** Sum of winning net returns, fractions of notional. */
  winReturnSum: number;
  /** Sum of losing net returns as positive fractions of notional. */
  lossReturnSum: number;
}

/** Realised against modelled slippage for one venue. */
export interface SlippageRow {
  venue: string;
  fills: number;
  medianRealisedBps: number;
  medianModelledBps: number;
  ratio?: number;
  /** At least 30 fills behind the medians. */
  enough: boolean;
}

// ── research (real candles, Rust) ───────────────────────────────────────────
/** One window of a sweep. Mirrors Rust `research::WindowSummary`. */
export interface WindowSummary {
  sharpe: number;
  totalReturn: number;
  maxDrawdown: number;
  trades: number;
  bars: number;
  pnl: PnlBreakdown;
}

/** One configuration in the parameter sweep. Mirrors Rust `research::SweepRow`. */
export interface SweepRow {
  /** `[key, value]` pairs, as the Rust tuple serialises. */
  params: [string, number][];
  is: WindowSummary;
  oos: WindowSummary;
  /** Out-of-sample over in-sample Sharpe; absent when in-sample was not positive. */
  oosIsRatio?: number;
  /** Probability the in-sample Sharpe is edge rather than the best of `trials` tries. */
  deflatedSharpe: number;
  pValue: number;
}

export interface SweepReport {
  strategyId: string;
  name: string;
  trials: number;
  isFraction: number;
  markets: number;
  costVenue: CostVenue;
  rows: SweepRow[];
}

// ── the Strategy Passport (PROFIT-PLAN §2) ──────────────────────────────────
export type GateStatus = "pass" | "fail" | "pending";
/** How to read a number: a signed return as %, a share as %, a plain number, or a count. */
export type GateUnit = "pct" | "share" | "number" | "count";

export interface GateFigure {
  label: string;
  value: number;
  unit: GateUnit;
}

/** One validation gate. Mirrors Rust `validation::Gate`. */
export interface Gate {
  /** 1 to 8. */
  id: number;
  name: string;
  status: GateStatus;
  /** Plain language: why it passed, failed or is pending. */
  reason: string;
  /** The number it was judged on. */
  value?: number;
  measure: string;
  unit: GateUnit;
  figures?: GateFigure[];
}

/** The eight gates for one strategy. Mirrors Rust `validation::Passport`. */
export interface Passport {
  strategyId: string;
  gates: Gate[];
  /** Gates 1 to 7 pass: the strategy may be set to Live. */
  liveReady: boolean;
  /** Why it may not, in plain language. */
  blockedReason?: string;
  /** When gates 1 to 6 were last computed (epoch ms). */
  checkedAt?: number;
  /** The checks were run with other parameters than the strategy has now. */
  stale: boolean;
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
  /** Cap on correlation-adjusted exposure sqrt(w'Cw), % of equity (0 = off). */
  maxCorrelatedExposurePct: number;
  /** Ceiling on the whole book's volatility: one standard deviation of a year's
   *  P&L, % of equity (0 = off). Enforced by the Rust engine. */
  portfolioVolTargetPct: number;
  /** Trim every position back to the volatility target once the book has
   *  stayed above this many times the target for 30 minutes (0 = off).
   *  Closing only, at most once an hour. Enforced by the Rust engine. */
  volSpikeTrimMult: number;
}

/** What the risk manager is doing right now. Mirrors Rust `risk::RiskStatus`. */
export interface RiskStatus {
  /** Correlation-adjusted exposure of the open book, sqrt(w'Cw), quote currency. */
  correlatedExposure: number;
  /** The same as % of equity, next to `maxCorrelatedExposurePct`. */
  correlatedExposurePct: number;
  /** How each strategy's entries are sized. */
  sizing: StrategySizing[];
  /** Peak-to-now equity drawdown, %, the one the breaker watches. */
  drawdownPct: number;
  /** New entries are multiplied by this: 1 - drawdown / maxDrawdownPct, clamped to 0..1. */
  deriskFactor: number;
  /** One standard deviation of the book's annual P&L, quote currency. */
  portfolioVol: number;
  /** The same as % of equity, next to `portfolioVolTargetPct`. */
  portfolioVolPct: number;
  /** Open markets whose volatility is assumed (5 % a day), not measured from candles. */
  volAssumed: string[];
  /** Held pairs that cannot be compared in time (candles against live ticks).
   *  Counted as the worst case: moving together, or against a short. */
  unalignedPairs?: [string, string][];
  /** When the book went over the spike-trim trigger, if it is over it now (epoch ms). */
  volSpikeSince?: number;
  /** When the book was last trimmed for a volatility spike (epoch ms). */
  lastVolTrim?: number;
}

/** confidence: under 30 trades, sized off signal strength. measured: sized on
 *  its own win rate and payoff. noEdge: the record shows no edge, size zero. */
export type SizingMode = "confidence" | "measured" | "noEdge";

/** Mirrors Rust `risk::StrategySizing`. */
export interface StrategySizing {
  strategyId: string;
  mode: SizingMode;
  trades: number;
  winRate?: number;
  /** Average win over average loss; absent while there has been no loss. */
  payoff?: number;
  /** Full Kelly, p - (1 - p) / b. */
  kelly?: number;
  /** kelly * n / (n + 30). */
  kellyShrunk?: number;
  /** When a parameter change last started the record over (epoch ms). */
  since?: number;
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
  | "manual"
  /** Target weights decided in the research lab, executed by the engine. */
  | "lab-targets";

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
  /** Costs paid and forward-test record. Absent on configs that never traded. */
  ledger?: StrategyLedger;
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

// ── AI signal provider (multi-LLM) ───────────────────────────────────────────
export type LlmDirection = "long" | "short" | "neutral";

export interface LlmProviderInfo {
  id: string;
  label: string;
  defaultModel: string;
  suggestedModels: string[];
  envKey: string;
  needsKey: boolean;
  /** whether a key is available in the current runtime (vault or env) */
  configured: boolean;
}

export interface LlmSignal {
  probability: number;
  direction: LlmDirection;
  confidence: number;
  rationale: string;
  /** Forecast protocol only: the reference-class rate, committed to first. */
  baseRate?: number;
  keyDrivers?: string[];
  evidenceFor?: string[];
  evidenceAgainst?: string[];
  provider: string;
  model: string;
  /** Round-trip latency; a signal that arrives after its bar is visibly late. */
  latencyMs?: number;
  inputTokens?: number;
  outputTokens?: number;
  /** Which model actually answered (differs from `model` after a server-side fallback). */
  servedBy?: string;
}

// ── live execution ───────────────────────────────────────────────────────────
/** What the broker (Alpaca) says about the session and the account. */
export interface BrokerStatus {
  marketOpen: boolean;
  /** Inside the pre-market / after-hours session (~04:00–20:00 ET). */
  extendedOpen: boolean;
  /** Exchange-local end of today's extended session, when one is running. */
  sessionEnd?: string;
  nextOpen?: string;
  /** FINRA pattern-day-trader ceiling reached (3 day trades / 5 sessions under $25k). */
  dayTradeLimitReached: boolean;
  /** Set when the account itself refuses orders (blocked, not yet active…). */
  restricted?: string;
  equity: number;
  buyingPower: number;
  checkedAt: number;
}

export interface LiveStatus {
  armed: boolean;
  paper: boolean;
  dryRun: boolean;
  /** Venues allowed to route live. Empty ⇒ nothing routes, whatever `armed` says. */
  venues: Venue[];
  /** Seconds a working order may sit before it is cancelled at the venue. */
  timeoutSec: number;
  /** Venues with usable credentials in this runtime. */
  connected: Venue[];
  /** Alpaca entries allowed during the pre-market / after-hours session. */
  extendedHours: boolean;
  alpacaConnected: boolean;
  pending: number;
  /** Positions held via a real venue fill — these cannot be closed by the simulator. */
  livePositions: number;
  broker?: BrokerStatus;
  /**
   * Why a live Alpaca *entry* would be refused right now. `undefined` means the
   * path is clear. Surfaced so an armed engine placing no trades explains itself
   * instead of looking broken.
   */
  blockedReason?: string;
}

/** What the arm flow sends. Mirrors the Rust `LiveConfig`. */
export interface LiveConfig {
  armed: boolean;
  paper: boolean;
  dryRun: boolean;
  venues: Venue[];
  timeoutSec: number;
  /** Opt-in for the pre/post-market session; used only when the broker reports one running. */
  extendedHours: boolean;
}

/** One model's view of one market. Advisory only — see `AiPolicy`. */
export interface AiView {
  marketId: string;
  direction: "long" | "short" | "neutral";
  probability: number;
  confidence: number;
  rationale: string;
  model: string;
  ts: number;
  latencyMs: number;
}

/**
 * How much authority the AI overlay has. A model may shrink or veto a trade the
 * rules already decided to make; it can never originate one.
 */
export interface AiPolicy {
  enabled: boolean;
  ttlSec: number;
  vetoConfidence: number;
  maxBoost: number;
}

export interface AiSpend {
  calls: number;
  inputTokens: number;
  outputTokens: number;
  errors: number;
}

// ── forecasting ──────────────────────────────────────────────────────────────
/** `outcome` = will the event happen. `direction` = will this price be higher. */
export type ForecastKind = "outcome" | "direction";
export type ForecastAction = "buy" | "sell" | "hold";

/** Three-level skill estimate: global → source → source × market class. */
export interface HierarchicalSkill {
  /** Every source pooled, on this question type — what a newcomer inherits. */
  global: number;
  /** This source across all market classes, shrunk toward `global`. */
  source: number;
  /** This source on this market class, shrunk toward `source`. Used for trust. */
  pooled: number;
  /** Unpooled skill at the finest level, so the shrinkage is visible. */
  raw: number;
  n: number;
  nSource: number;
}

export interface SourceView {
  source: string;
  /** What the source said. */
  rawP: number;
  /** After its learned recalibration. */
  p: number;
  /** Weight actually pooled: `rawWeight` after the redundancy adjustment. */
  weight: number;
  /** Trust floored at the bootstrap value, before redundancy. */
  rawWeight: number;
  /** Measured trust from the track record. 0 = unproven. */
  trust: number;
  /** Resolved forecasts behind that number. */
  n: number;
  skill: HierarchicalSkill;
  rationale: string;
}

export interface MarketForecast {
  marketId: string;
  symbol: string;
  kind: ForecastKind;
  /** The market's own view. 0.5 for a price market — a random walk's answer. */
  marketP: number;
  sources: SourceView[];
  /** Pooled sources, before shrinking toward the market. */
  modelP: number;
  /** The number Pythia actually uses. */
  ensembleP: number;
  trust: number;
  disagreement: number;
  effectiveSources: number;
  edge: number;
  edgeBps: number;
  costBps: number;
  netEdgeBps: number;
  kelly: number;
  action: ForecastAction;
  reason: string;
  ts: number;
}

export interface Score {
  n: number;
  brier: number;
  logLoss: number;
  meanForecast: number;
  meanOutcome: number;
}

export interface Recalibration {
  slope: number;
  intercept: number;
  n: number;
}

export interface ReliabilityBin {
  lo: number;
  hi: number;
  n: number;
  meanForecast: number;
  observed: number;
}

export interface Track {
  source: string;
  kind: ForecastKind;
  /** Market class this row scores — `prediction`, `crypto`, `equity`. */
  category: string;
  skill: HierarchicalSkill;
  score: Score;
  /** The market's score on the same questions — the only fair comparison. */
  marketScore: Score;
  brierSkill: number;
  trust: number;
  recalibration: Recalibration;
  reliability: ReliabilityBin[];
}

export interface CoherenceLeg {
  marketId: string;
  outcome: string;
  price: number;
}

export interface CoherenceBreak {
  eventId: string;
  title: string;
  kind: "underpriced" | "overpriced";
  sum: number;
  gapBps: number;
  netBps: number;
  actionable: boolean;
  legs: CoherenceLeg[];
}

export interface ForecastStats {
  recorded: number;
  resolved: number;
  pending: number;
  trustedSources: number;
}

export interface ForecastConfig {
  horizonBars: number;
  horizonMs: number;
  longshotK: number;
  momentumBeta: number;
  driftTrust: number;
  sharpen: number;
  bootstrapTrust: number;
  kellyFraction: number;
  costBps: number;
  minEdgeBps: number;
  /** Error correlation assumed for a pair with no shared history. */
  assumedCorrelation: number;
}

// ── adaptive execution ───────────────────────────────────────────────────────
/** How hard one order pushed: rest inside the spread, sit at the touch, or take. */
export type ExecStyle = "passive" | "join" | "cross";

export interface PolicyRow {
  /** Venue plus urgency, e.g. `Alpaca:normal`. */
  context: string;
  style: ExecStyle;
  /** Mean realised cost against the arrival price. Lower is better; negative is
   *  better than arrival. Non-fills are charged a penalty. */
  meanCostBps: number;
  fills: number;
  misses: number;
}

export interface EnsembleRun {
  marketId: string;
  asked: number;
  answered: number;
  errors: string[];
}

// ── exchanges & wallets ──────────────────────────────────────────────────────
export type ExchangeId = "kraken" | "binance" | "bybit" | "okx" | "coinbase";

export interface ExchangeInfo {
  id: ExchangeId;
  label: string;
  /** OKX and Coinbase need an API passphrase alongside key + secret. */
  needsPassphrase: boolean;
  /** Whether order routing is implemented for this venue. */
  canTrade: boolean;
  configured: boolean;
}

export type Chain =
  | "ethereum"
  | "polygon"
  | "arbitrum"
  | "optimism"
  | "base"
  | "bsc"
  | "solana"
  | "bitcoin";

/** A watch-only address. Pythia never holds a key for these. */
export interface WatchedAddress {
  chain: Chain;
  address: string;
  label: string;
}

export interface Balance {
  asset: string;
  free: number;
  total: number;
  usdValue?: number;
}

export type WalletKind = "broker" | "exchange" | "onchain";

export interface WalletAccount {
  id: string;
  kind: WalletKind;
  provider: string;
  label: string;
  connected: boolean;
  canTrade: boolean;
  balances: Balance[];
  usdTotal: number;
  error?: string;
}

export interface WalletsSnapshot {
  accounts: WalletAccount[];
  usdTotal: number;
  /** Assets held but not priced — excluded from `usdTotal` rather than counted as 0. */
  unpriced: string[];
  updatedAt: number;
}
