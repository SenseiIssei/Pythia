import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { getEngine } from "./engine";
import type {
  AiPolicy,
  AiSpend,
  AiView,
  AutopilotConfig,
  AutopilotStatus,
  CoherenceBreak,
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
  SlippageRow,
  StrategyConfig,
  Track,
} from "./types";

interface Store {
  portfolio: PortfolioSnapshot;
  markets: Market[];
  positions: PositionView[];
  orders: Order[];
  journal: JournalEntry[];
  strategies: StrategyConfig[];
  limits: RiskLimits;
  history: Record<string, number[]>;
  /** Bar times for the candle markets in `history`; ticks have none. */
  historyTimes: Record<string, number[]>;
  live: LiveStatus;
  forecasts: MarketForecast[];
  tracks: Track[];
  coherence: CoherenceBreak[];
  forecastStats: ForecastStats;
  execution: PolicyRow[];
  adaptiveExecution: boolean;
  /** Realised against modelled slippage per venue (live fills only). */
  slippage: SlippageRow[];
  /** Strategy Passport per strategy id. */
  passports: Map<string, Passport>;
  /** The Rust risk manager's live numbers; null in the browser paper build. */
  riskStatus: RiskStatus | null;
  /** Feed sources, freshness and failovers; null in the browser paper build. */
  dataHealth: DataHealth | null;
  /** Market ids running on real exchange candles rather than the simulator. */
  barBacked: Set<string>;
  aiViews: AiView[];
  aiPolicy: AiPolicy;
  aiSpend: AiSpend;
  /** Every autopilot: running, paused and the most recent stopped ones. */
  autopilots: AutopilotStatus[];
  // actions
  toggleKill: () => void;
  setLimits: (l: Partial<RiskLimits>) => void;
  /** Rejects with a plain-language reason when Live is refused. */
  setStrategyState: (id: string, s: StrategyConfig["state"]) => Promise<void>;
  setStrategyParam: (id: string, key: string, value: number) => void;
  addStrategy: (cfg: StrategyConfig) => void;
  manualOrder: (marketId: string, side: "buy" | "sell", notional: number) => string;
  flatten: (marketId: string) => void;
  setAdaptiveExecution: (on: boolean) => void;
  /** Give an amount to an autopilot. `confirm` is the owner's typed
   *  confirmation, which live needs. Rejects with a plain sentence. */
  startAutopilot: (config: AutopilotConfig, confirm?: boolean) => Promise<void>;
  /** `flatten` overrides the autopilot's own `flattenOnStop`. */
  stopAutopilot: (id: string, flatten?: boolean) => Promise<void>;
  pauseAutopilot: (id: string) => Promise<void>;
  resumeAutopilot: (id: string) => Promise<void>;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const engine = useMemo(() => getEngine(), []);

  const subscribe = useMemo(() => engine.subscribe.bind(engine), [engine]);
  // A single monotonic version counter drives re-renders; components read fresh
  // views from the engine on each render.
  const version = useSyncExternalStore(
    subscribe,
    () => engine.getVersion()
  );

  const value: Store = useMemo(
    () => ({
      portfolio: engine.snapshot(),
      markets: engine.markets(),
      positions: engine.positionViews(),
      orders: engine.orderList(),
      journal: engine.journalList(),
      strategies: engine.strategyList(),
      limits: engine.getLimits(),
      history: engine.history(),
      historyTimes: engine.historyTimes(),
      live: engine.liveStatus(),
      forecasts: engine.forecasts(),
      tracks: engine.tracks(),
      coherence: engine.coherence(),
      forecastStats: engine.forecastStats(),
      execution: engine.execution(),
      adaptiveExecution: engine.adaptiveExecution(),
      slippage: engine.slippage(),
      passports: new Map(engine.passports().map((p) => [p.strategyId, p])),
      riskStatus: engine.riskStatus(),
      dataHealth: engine.dataHealth(),
      barBacked: new Set(engine.barBacked()),
      aiViews: engine.aiViews(),
      aiPolicy: engine.aiPolicy(),
      aiSpend: engine.aiSpend(),
      autopilots: engine.autopilots(),
      toggleKill: () => engine.toggleKill(),
      setLimits: (l) => engine.setLimits(l),
      setStrategyState: (id, s) => engine.setStrategyState(id, s),
      setStrategyParam: (id, key, v) => engine.setStrategyParam(id, key, v),
      addStrategy: (cfg) => engine.addStrategy(cfg),
      manualOrder: (m, side, n) => engine.manualOrder(m, side, n),
      flatten: (m) => engine.flatten(m),
      setAdaptiveExecution: (on) => engine.setAdaptiveExecution(on),
      startAutopilot: (config, confirm) => engine.startAutopilot(config, confirm),
      stopAutopilot: (id, flatten) => engine.stopAutopilot(id, flatten),
      pauseAutopilot: (id) => engine.pauseAutopilot(id),
      resumeAutopilot: (id) => engine.resumeAutopilot(id),
    }),
    // rebuild views whenever the engine emits (version changes)
    [engine, version]
  );

  // Keep the engine ticking for the app's lifetime. start() is idempotent, so
  // React StrictMode's mount→cleanup→mount cycle can't leave it stopped.
  useEffect(() => {
    engine.start();
  }, [engine]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore must be used within StoreProvider");
  return s;
}
