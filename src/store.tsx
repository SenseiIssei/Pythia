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
  JournalEntry,
  Market,
  Order,
  PortfolioSnapshot,
  PositionView,
  RiskLimits,
  StrategyConfig,
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
  // actions
  toggleKill: () => void;
  setLimits: (l: Partial<RiskLimits>) => void;
  setStrategyState: (id: string, s: StrategyConfig["state"]) => void;
  setStrategyParam: (id: string, key: string, value: number) => void;
  addStrategy: (cfg: StrategyConfig) => void;
  manualOrder: (marketId: string, side: "buy" | "sell", notional: number) => string;
  flatten: (marketId: string) => void;
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
      toggleKill: () => engine.toggleKill(),
      setLimits: (l) => engine.setLimits(l),
      setStrategyState: (id, s) => engine.setStrategyState(id, s),
      setStrategyParam: (id, key, v) => engine.setStrategyParam(id, key, v),
      addStrategy: (cfg) => engine.addStrategy(cfg),
      manualOrder: (m, side, n) => engine.manualOrder(m, side, n),
      flatten: (m) => engine.flatten(m),
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
