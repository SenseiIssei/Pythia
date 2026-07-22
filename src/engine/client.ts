import type {
  JournalEntry,
  Market,
  Order,
  PortfolioSnapshot,
  PositionView,
  RiskLimits,
  Side,
  StrategyConfig,
  StrategyState,
} from "../types";

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

  toggleKill(): void;
  setLimits(l: Partial<RiskLimits>): void;
  setStrategyState(id: string, s: StrategyState): void;
  setStrategyParam(id: string, key: string, value: number): void;
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
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
