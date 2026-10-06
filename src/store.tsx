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
  CoherenceBreak,
  ForecastStats,
  JournalEntry,
  LiveStatus,
  Market,
  MarketForecast,
  Order,
  PolicyRow,
  PortfolioSnapshot,
  PositionView,
  RiskLimits,
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
  live: LiveStatus;
  forecasts: MarketForecast[];
  tracks: Track[];
  coherence: CoherenceBreak[];
  forecastStats: ForecastStats;
  execution: PolicyRow[];
  adaptiveExecution: boolean;
  /** Realised against modelled slippage per venue (live fills only). */
  slippage: SlippageRow[];
  /** Market ids running on real exchange candles rather than the simulator. */
  barBacked: Set<string>;
  aiViews: AiView[];
  aiPolicy: AiPolicy;
  aiSpend: AiSpend;
  // actions
  toggleKill: () => void;
  setLimits: (l: Partial<RiskLimits>) => void;
  setStrategyState: (id: string, s: StrategyConfig["state"]) => void;
  setStrategyParam: (id: string, key: string, value: number) => void;
  addStrategy: (cfg: StrategyConfig) => void;
  manualOrder: (marketId: string, side: "buy" | "sell", notional: number) => string;
  flatten: (marketId: string) => void;
  setAdaptiveExecution: (on: boolean) => void;
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
      live: engine.liveStatus(),
      forecasts: engine.forecasts(),
      tracks: engine.tracks(),
      coherence: engine.coherence(),
      forecastStats: engine.forecastStats(),
      execution: engine.execution(),
      adaptiveExecution: engine.adaptiveExecution(),
      slippage: engine.slippage(),
      barBacked: new Set(engine.barBacked()),
      aiViews: engine.aiViews(),
      aiPolicy: engine.aiPolicy(),
      aiSpend: engine.aiSpend(),
      toggleKill: () => engine.toggleKill(),
      setLimits: (l) => engine.setLimits(l),
      setStrategyState: (id, s) => engine.setStrategyState(id, s),
      setStrategyParam: (id, key, v) => engine.setStrategyParam(id, key, v),
      addStrategy: (cfg) => engine.addStrategy(cfg),
      manualOrder: (m, side, n) => engine.manualOrder(m, side, n),
      flatten: (m) => engine.flatten(m),
      setAdaptiveExecution: (on) => engine.setAdaptiveExecution(on),
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
