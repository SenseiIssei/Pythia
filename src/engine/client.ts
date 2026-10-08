import type {
  AiPolicy,
  AiSpend,
  AiView,
  AutopilotConfig,
  AutopilotStatus,
  CoherenceBreak,
  CostVenue,
  DataHealth,
  ForecastStats,
  JournalEntry,
  LiveStatus,
  Market,
  MarketForecast,
  Order,
  Passport,
  PolicyRow,
  PortfolioSnapshot,
  PositionView,
  RiskLimits,
  RiskStatus,
  Side,
  SlippageRow,
  StrategyConfig,
  StrategyState,
  Track,
} from "../types";

/** Nothing forecast yet — what the browser paper build reports. */
export const NO_FORECASTS: ForecastStats = { recorded: 0, resolved: 0, pending: 0, trustedSources: 0 };

/** The safe default every runtime starts from: nothing armed, nothing routing. */
const DISARMED: LiveStatus = {
  armed: false,
  paper: true,
  dryRun: false,
  venues: [],
  timeoutSec: 120,
  connected: [],
  extendedHours: false,
  alpacaConnected: false,
  pending: 0,
  livePositions: 0,
};

/** Overlay off, matching the Rust default — nothing AI-driven without opt-in. */
const AI_OFF: AiPolicy = { enabled: false, ttlSec: 900, vetoConfidence: 0.7, maxBoost: 1.25 };
const NO_SPEND: AiSpend = { calls: 0, inputTokens: 0, outputTokens: 0, errors: 0 };

// The one interface the UI depends on. Two implementations satisfy it:
//   · PaperEngine        — pure TypeScript, runs in the browser (dev / web app)
//   · TauriEngineClient  — thin proxy to the Rust engine daemon (native app)
// The store never knows which one is answering.
export interface EngineClient {
  start(): void;
  stop(): void;
  subscribe(fn: () => void): () => void;
  getVersion(): number;

  snapshot(): PortfolioSnapshot;
  markets(): Market[];
  positionViews(): PositionView[];
  orderList(): Order[];
  journalList(): JournalEntry[];
  strategyList(): StrategyConfig[];
  getLimits(): RiskLimits;
  /** Recent close-price history per tradable market (for correlation analysis). */
  history(): Record<string, number[]>;
  /** Bar open times (epoch ms) for the closes in `history`, for markets on
   *  real candles only. A market missing here is on ticks, which have no
   *  times, and cannot be correlated against a candle market. */
  historyTimes(): Record<string, number[]>;
  /** Live-execution status (arm state, endpoint, pending live orders, session gate). */
  liveStatus(): LiveStatus;
  /** The forecasting layer's view: per-market ensembles, source scoreboard,
   *  and any market whose own outcomes fail to price to 1. */
  forecasts(): MarketForecast[];
  tracks(): Track[];
  coherence(): CoherenceBreak[];
  forecastStats(): ForecastStats;
  /** What adaptive execution has learned, per (venue+urgency, style). */
  execution(): PolicyRow[];
  adaptiveExecution(): boolean;
  /** Realised against modelled slippage per venue, once there are live fills. */
  slippage(): SlippageRow[];
  /** The Strategy Passport (eight validation gates) of every strategy. */
  passports(): Passport[];
  /**
   * Correlation-adjusted exposure, drawdown de-risking and per-strategy
   * sizing from the Rust risk manager. Null where no Rust engine answers
   * (the browser paper build).
   */
  riskStatus(): RiskStatus | null;
  /** Where the crypto data comes from and whether it is fresh. Null where no
   *  Rust engine runs the feeds (the browser paper build). */
  dataHealth(): DataHealth | null;
  /** The exchange crypto is charged and routed on (Settings), e.g. "kraken". */
  cryptoCostVenue(): CostVenue;
  /**
   * Market ids whose indicators run on real exchange candles rather than the
   * simulator. Anything not in here is a demo, and the UI says so.
   */
  barBacked(): string[];
  /** Latest model view per market (advisory). */
  aiViews(): AiView[];
  aiPolicy(): AiPolicy;
  aiSpend(): AiSpend;

  toggleKill(): void;
  setLimits(l: Partial<RiskLimits>): void;
  /** Rejects with a plain-language reason when Live is refused by the passport. */
  setStrategyState(id: string, s: StrategyState): Promise<void>;
  setStrategyParam(id: string, key: string, value: number): void;
  addStrategy(cfg: StrategyConfig): void;
  manualOrder(marketId: string, side: Side, notional: number): string;
  flatten(marketId: string): void;
  setAdaptiveExecution(on: boolean): void;

  /** Every autopilot: running, paused and the most recent stopped ones. */
  autopilots(): AutopilotStatus[];
  /**
   * Give an amount to an autopilot. `confirm` is the owner's typed
   * confirmation; live is refused without it. Rejects with a plain sentence
   * (why live was refused, a market conflict, a bad amount).
   */
  startAutopilot(config: AutopilotConfig, confirm?: boolean): Promise<void>;
  /** `flatten` overrides the autopilot's own `flattenOnStop`. */
  stopAutopilot(id: string, flatten?: boolean): Promise<void>;
  pauseAutopilot(id: string): Promise<void>;
  resumeAutopilot(id: string): Promise<void>;
}

/** What the browser build says when asked to run an autopilot. */
export const AUTOPILOT_NEEDS_ENGINE =
  "The autopilot needs the desktop app or the Pythia server: this browser build runs a demo engine only.";

// The full engine state the Rust daemon pushes to the UI each tick, and the
// shape TauriEngineClient caches locally.
export interface EngineState {
  portfolio: PortfolioSnapshot;
  markets: Market[];
  positions: PositionView[];
  orders: Order[];
  journal: JournalEntry[];
  strategies: StrategyConfig[];
  limits: RiskLimits;
  history: Record<string, number[]>;
  historyTs?: Record<string, number[]>;
  live: LiveStatus;
  barBacked?: string[];
  aiViews?: AiView[];
  aiPolicy?: AiPolicy;
  aiSpend?: AiSpend;
  forecasts: MarketForecast[];
  tracks: Track[];
  coherence: CoherenceBreak[];
  forecastStats: ForecastStats;
  execution: PolicyRow[];
  adaptiveExecution: boolean;
  slippage?: SlippageRow[];
  cryptoCostVenue?: CostVenue;
  passports?: Passport[];
  risk?: RiskStatus;
  dataHealth?: DataHealth | null;
  autopilots?: AutopilotStatus[];
}

export { AI_OFF, DISARMED, NO_SPEND };

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
