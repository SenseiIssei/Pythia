import type {
  AiPolicy,
  AiSpend,
  AiView,
  JournalEntry,
  LiveStatus,
  Market,
  Order,
  PortfolioSnapshot,
  PositionView,
  RiskLimits,
  Side,
  StrategyConfig,
  StrategyState,
} from "../types";

const DISARMED: LiveStatus = { armed: false, paper: true, dryRun: false, alpacaConnected: false, pending: 0 };

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
  /** Live-execution status (arm state, endpoint, pending live orders, session gate). */
  liveStatus(): LiveStatus;
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
  setStrategyState(id: string, s: StrategyState): void;
  setStrategyParam(id: string, key: string, value: number): void;
  addStrategy(cfg: StrategyConfig): void;
  manualOrder(marketId: string, side: Side, notional: number): string;
  flatten(marketId: string): void;
}

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
  live: LiveStatus;
  barBacked?: string[];
  aiViews?: AiView[];
  aiPolicy?: AiPolicy;
  aiSpend?: AiSpend;
}

export { AI_OFF, DISARMED, NO_SPEND };

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
