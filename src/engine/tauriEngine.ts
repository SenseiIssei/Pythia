import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
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
import { DISARMED, type EngineClient, type EngineState } from "./client";
import { DEFAULT_LIMITS } from "./risk";

const EMPTY: EngineState = {
  portfolio: {
    mode: "paper",
    cash: 0,
    equity: 0,
    dayStartEquity: 0,
    realizedPnl: 0,
    unrealizedPnl: 0,
    grossExposure: 0,
    equityCurve: [],
    balances: [],
  },
  markets: [],
  positions: [],
  orders: [],
  journal: [],
  strategies: [],
  limits: DEFAULT_LIMITS,
  history: {},
  live: DISARMED,
};

// Thin proxy to the Rust engine daemon. It caches the last EngineState pushed
// over the "engine://state" Tauri event and forwards every mutation to a Rust
// command. The Rust side owns the tick loop, portfolio, risk checks and journal.
export class TauriEngineClient implements EngineClient {
  private state: EngineState = EMPTY;
  private listeners = new Set<() => void>();
  private version = 0;
  private unlisten: UnlistenFn | null = null;
  private started = false;

  async init() {
    if (this.started) return;
    this.started = true;
    // subscribe to pushed state first, then seed so we never miss an update
    this.unlisten = await listen<EngineState>("engine://state", (ev) => {
      this.state = ev.payload;
      this.bump();
    });
    try {
      this.state = await invoke<EngineState>("get_state");
      this.bump();
    } catch {
      /* daemon not ready yet; the event will deliver state shortly */
    }
  }

  start() {
    void this.init();
  }
  stop() {
    this.unlisten?.();
    this.unlisten = null;
  }
  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
  private bump() {
    this.version++;
    for (const l of this.listeners) l();
  }
  getVersion(): number {
    return this.version;
  }

  snapshot(): PortfolioSnapshot {
    return this.state.portfolio;
  }
  markets(): Market[] {
    return this.state.markets;
  }
  positionViews(): PositionView[] {
    return this.state.positions;
  }
  orderList(): Order[] {
    return this.state.orders;
  }
  journalList(): JournalEntry[] {
    return this.state.journal;
  }
  strategyList(): StrategyConfig[] {
    return this.state.strategies;
  }
  getLimits(): RiskLimits {
    return this.state.limits;
  }
  history(): Record<string, number[]> {
    return this.state.history ?? {};
  }
  liveStatus() {
    return this.state.live ?? DISARMED;
  }

  toggleKill() {
    void invoke("toggle_kill");
  }
  setLimits(l: Partial<RiskLimits>) {
    void invoke("set_limits", { patch: { ...this.state.limits, ...l } });
  }
  setStrategyState(id: string, s: StrategyState) {
    void invoke("set_strategy_state", { id, state: s });
  }
  setStrategyParam(id: string, key: string, value: number) {
    void invoke("set_strategy_param", { id, key, value });
  }
  addStrategy(cfg: StrategyConfig) {
    void invoke("add_strategy", { cfg });
  }
  manualOrder(marketId: string, side: Side, notional: number): string {
    void invoke("manual_order", { marketId, side, notional });
    return "ok"; // rejections surface in the journal pushed back from Rust
  }
  flatten(marketId: string) {
    void invoke("flatten", { marketId });
  }
}
