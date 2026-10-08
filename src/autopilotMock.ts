// DEVELOPMENT ONLY. A made-up autopilot so the Autopilot page can be looked at
// before the engine answers for it.
//
// It switches on only when both hold:
//   · this is a Vite dev build (`import.meta.env.DEV`), and
//   · the address has `?mockAutopilot` (optionally `=running`, `=paused`,
//     `=finished`, `=empty` or `=loading`).
// A production build replaces `import.meta.env.DEV` with `false`, the call
// site in the page folds away, and this module is not shipped at all. The page
// also labels every mocked view as sample data.

import { useEffect, useSyncExternalStore } from "react";
import type { AutopilotStart, AutopilotStatus } from "./types";
import { LIVE_PHRASE, floorAtStart } from "./autopilot";

export type MockScenario = "running" | "paused" | "finished" | "empty" | "loading";

export interface MockAutopilot {
  scenario: MockScenario;
  loading: boolean;
  autopilots: AutopilotStatus[];
  /** Hourly Bitcoin bar times and closes, so the "just holding" comparison has something to read. */
  btc: { times: number[]; closes: number[] };
  start: (config: AutopilotStart) => Promise<void>;
  stop: (id: string, flatten: boolean) => Promise<void>;
  pause: (id: string) => Promise<void>;
  resume: (id: string) => Promise<void>;
}

function requested(): MockScenario | null {
  if (!import.meta.env.DEV || typeof window === "undefined") return null;
  const q = new URLSearchParams(window.location.search);
  if (!q.has("mockAutopilot")) return null;
  const v = q.get("mockAutopilot");
  return v === "paused" || v === "finished" || v === "empty" || v === "loading" ? v : "running";
}

const H = 3_600_000;
const DAY = 24 * H;

/** Small deterministic generator, so the fixture looks the same on every reload. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function walk(seed: number, from: number, to: number, step: number, start: number, drift: number, vol: number) {
  const r = rng(seed);
  const out: [number, number][] = [];
  let v = start;
  for (let t = from; t <= to; t += step) {
    out.push([t, v]);
    v *= 1 + drift + (r() - 0.5) * 2 * vol;
  }
  return out;
}

interface State {
  scenario: MockScenario;
  list: AutopilotStatus[];
  btc: { times: number[]; closes: number[] };
  names: Record<string, string>;
}

let state: State | null = null;
let version = 0;
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;

function emit() {
  version++;
  listeners.forEach((fn) => fn());
}

/** A sample status as written above: the engine's optional fields may be left out. */
type MockStatus = Omit<AutopilotStatus, "stopReason" | "pausedReason" | "stoppedMs" | "targetEquity" | "openPositions"> &
  Partial<Pick<AutopilotStatus, "stopReason" | "pausedReason" | "stoppedMs" | "targetEquity" | "openPositions">>;

function summarise(s: MockStatus): AutopilotStatus {
  const equity = s.history.length ? s.history[s.history.length - 1][1] : s.startCapital;
  const peakEquity = Math.max(s.peakEquity, equity);
  const pnl = equity - s.startCapital;
  const trail = s.config.stop.trailingPct;
  const plan = floorAtStart(s.startCapital, s.config.stop);
  const floorEquity = Math.max(plan.floor ?? 0, trail ? peakEquity * (1 - trail / 100) : 0);
  return {
    stopReason: null,
    pausedReason: null,
    stoppedMs: null,
    targetEquity: null,
    openPositions: s.state === "running" || s.state === "paused" ? s.bySleeve.length : 0,
    ...s,
    equity,
    peakEquity,
    pnl,
    pnlPct: (pnl / s.startCapital) * 100,
    drawdownPct: peakEquity > 0 ? ((peakEquity - equity) / peakEquity) * 100 : 0,
    floorEquity,
  };
}

function sleevesFor(start: AutopilotStart, names: Record<string, string>, r: () => number) {
  const picked =
    start.sleeves.length > 0
      ? start.sleeves
      : [
          { strategyId: "multi-tf-1", weight: 0.6 },
          { strategyId: "ema-cross-1", weight: 0.4 },
        ];
  return picked.map((p) => ({
    strategyId: p.strategyId,
    name: names[p.strategyId] ?? p.strategyId,
    weight: p.weight,
    pnl: 0,
    trades: 0,
    markets: [],
    why:
      start.sleeves.length > 0
        ? "You picked it."
        : r() > 0.5
          ? "Prices have been trending, and this one follows trends."
          : "Best record after costs over the last 90 days of the strategies that qualify.",
  }));
}

function seed(scenario: MockScenario, names: Record<string, string>): State {
  const now = Date.now();
  const btcWalk = walk(7, now - 60 * DAY, now, H, 61_800, 0.00012, 0.006);
  const btc = { times: btcWalk.map((p) => p[0]), closes: btcWalk.map((p) => p[1]) };
  const n = (id: string) => names[id] ?? id;

  // A run that reached its take-profit and stopped, six weeks ago.
  const winStart = now - 58 * DAY;
  const winEnd = now - 17 * DAY;
  const winHist = walk(11, winStart, winEnd, 3 * H, 5_000, 0.0007, 0.009);
  const won = summarise({
    config: {
      id: "mock-won",
      name: "Summer test",
      mode: "paper",
      venue: "kraken",
      capitalUsd: 5_000,
      sleeves: [],
      stop: { maxLossPct: 10, takeProfitPct: 19, onTakeProfit: "stop" },
      flattenOnStop: true,
    },
    state: "finished",
    stopReason: "Reached its take-profit of +19% and sold everything.",
    startedMs: winStart,
    stoppedMs: winEnd,
    startCapital: 5_000,
    equity: 0,
    pnl: 0,
    pnlPct: 0,
    peakEquity: 5_000,
    drawdownPct: 0,
    floorEquity: 0,
    trades: 64,
    fees: 118.4,
    bySleeve: [
      { strategyId: "multi-tf-1", name: n("multi-tf-1"), weight: 0.5, pnl: 742, trades: 31, markets: [], why: "Prices were trending, and this one follows trends." },
      { strategyId: "macd-1", name: n("macd-1"), weight: 0.3, pnl: 301, trades: 22, markets: [], why: "Second-best record after costs when it started." },
      { strategyId: "rsi-1", name: n("rsi-1"), weight: 0.2, pnl: -88, trades: 11, markets: [], why: "Balances the trend followers when prices go sideways." },
    ],
    lastAction: "Sold 0.012 BTC at $68,410 to take the profit.",
    history: winHist,
  });

  // A short run the owner stopped while it was down.
  const lostStart = now - 15 * DAY;
  const lostEnd = now - 12.5 * DAY;
  const lost = summarise({
    config: {
      id: "mock-lost",
      name: "Quick try",
      mode: "demo",
      venue: "alpaca",
      capitalUsd: 2_000,
      sleeves: [{ strategyId: "breakout-1", weight: 1 }],
      stop: { maxLossUsd: 300, onTakeProfit: "stop" },
      flattenOnStop: false,
    },
    state: "stopped",
    stopReason: "Stopped by you. The positions were kept.",
    startedMs: lostStart,
    stoppedMs: lostEnd,
    startCapital: 2_000,
    equity: 0,
    pnl: 0,
    pnlPct: 0,
    peakEquity: 2_000,
    drawdownPct: 0,
    floorEquity: 0,
    trades: 6,
    fees: 4.1,
    bySleeve: [
      { strategyId: "breakout-1", name: n("breakout-1"), weight: 1, pnl: -61.3, trades: 6, markets: [], why: "You picked it." },
    ],
    lastAction: "Bought 3 NVDA at $131.20.",
    history: walk(23, lostStart, lostEnd, H, 2_000, -0.0004, 0.004),
  });

  const list: AutopilotStatus[] = [];
  if (scenario === "running" || scenario === "paused") {
    const start = now - 12 * DAY - 5 * H;
    const hist = walk(5, start, now - H, H, 10_000, 0.00025, 0.004);
    const run = summarise({
      config: {
        id: "mock-run",
        name: "Autopilot 25 Sep",
        mode: "paper",
        venue: "kraken",
        capitalUsd: 10_000,
        sleeves: [],
        stop: { maxLossPct: 15, takeProfitPct: 25, onTakeProfit: "lock", trailingPct: 10 },
        flattenOnStop: true,
      },
      state: scenario,
      startedMs: start,
      startCapital: 10_000,
      equity: 0,
      pnl: 0,
      pnlPct: 0,
      peakEquity: 10_000,
      drawdownPct: 0,
      floorEquity: 0,
      trades: 23,
      fees: 41.7,
      bySleeve: [
        { strategyId: "multi-tf-1", name: n("multi-tf-1"), weight: 0.6, pnl: 0, trades: 14, markets: [], why: "Prices have been trending for two weeks, and this one follows trends." },
        { strategyId: "ema-cross-1", name: n("ema-cross-1"), weight: 0.4, pnl: 0, trades: 9, markets: [], why: "Best record after costs over the last 90 days of the strategies that qualify." },
      ],
      lastAction: "Bought 0.021 BTC at $64,120 because the trend turned up.",
      history: hist,
    });
    const split = run.pnl + run.fees;
    run.bySleeve[0].pnl = split * 0.8 - run.fees * 0.6;
    run.bySleeve[1].pnl = split * 0.2 - run.fees * 0.4;
    list.push(run);
  }
  if (scenario !== "empty") list.push(lost, won);
  return { scenario, list, btc, names };
}

function update(id: string, fn: (s: AutopilotStatus) => AutopilotStatus) {
  if (!state) return;
  state = { ...state, list: state.list.map((s) => (s.config.id === id ? fn(s) : s)) };
  emit();
}

/** Move every running autopilot one step: a new equity point, now and then a trade. */
function tick() {
  if (!state) return;
  const now = Date.now();
  const r = Math.random;
  let changed = false;
  const list = state.list.map((s) => {
    if (s.state !== "running") return s;
    changed = true;
    const last = s.history[s.history.length - 1]?.[1] ?? s.startCapital;
    const next = last * (1 + (r() - 0.48) * 0.004);
    let out: AutopilotStatus = { ...s, history: [...s.history, [now, next] as [number, number]] };
    if (r() < 0.25) {
      const i = Math.floor(r() * out.bySleeve.length);
      const fee = 0.6 + r();
      out = {
        ...out,
        trades: out.trades + 1,
        fees: out.fees + fee,
        bySleeve: out.bySleeve.map((b, j) => (j === i ? { ...b, trades: b.trades + 1, pnl: b.pnl + (next - last) - fee } : b)),
        lastAction: `${r() > 0.5 ? "Bought" : "Sold"} ${(r() * 0.02).toFixed(4)} BTC at $${Math.round(64_000 + r() * 400).toLocaleString("en-US")} (${out.bySleeve[i]?.name ?? "a strategy"}).`,
      };
    }
    out = summarise(out);
    if (out.floorEquity !== null && out.floorEquity > 0 && out.equity <= out.floorEquity) {
      out = { ...out, state: "stopped", stoppedMs: now, stopReason: "Reached its floor and stopped." };
    }
    return out;
  });
  if (changed) {
    state = { ...state, list };
    emit();
  }
}

function ensureTimer() {
  if (timer || !state) return;
  timer = setInterval(tick, 2_000);
}

const api = {
  start(config: AutopilotStart): Promise<void> {
    if (!state) return Promise.reject(new Error("The sample autopilot is not loaded."));
    if (config.mode === "live" && config.confirm !== LIVE_PHRASE) {
      return Promise.reject(new Error(`A real-money start has to be confirmed by typing ${LIVE_PHRASE}.`));
    }
    if (!(config.capitalUsd > 0)) return Promise.reject(new Error("The amount has to be more than zero."));
    const now = Date.now();
    const { confirm: _confirm, ...cfg } = config;
    const s = summarise({
      config: cfg,
      state: "running",
      startedMs: now,
      startCapital: cfg.capitalUsd,
      equity: cfg.capitalUsd,
      pnl: 0,
      pnlPct: 0,
      peakEquity: cfg.capitalUsd,
      drawdownPct: 0,
      floorEquity: 0,
      trades: 0,
      fees: 0,
      bySleeve: sleevesFor(config, state.names, rng(now)),
      lastAction: "Started. Waiting for the first signal.",
      history: [[now, cfg.capitalUsd]],
    });
    state = { ...state, list: [s, ...state.list] };
    emit();
    return new Promise((res) => setTimeout(res, 400));
  },
  stop(id: string, flatten: boolean): Promise<void> {
    update(id, (s) => ({
      ...s,
      state: "stopped",
      stoppedMs: Date.now(),
      stopReason: flatten ? "Stopped by you. Everything it held was sold." : "Stopped by you. The positions were kept.",
    }));
    return Promise.resolve();
  },
  pause(id: string): Promise<void> {
    update(id, (s) => ({ ...s, state: "paused", lastAction: "Paused by you. Holding what it has, opening nothing new." }));
    return Promise.resolve();
  },
  resume(id: string): Promise<void> {
    update(id, (s) => ({ ...s, state: "running", lastAction: "Resumed by you." }));
    return Promise.resolve();
  },
};

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

const noop = () => () => {};

/**
 * The sample autopilot, or null when it was not asked for. `names` labels the
 * strategies with what the store calls them.
 */
export function useMockAutopilot(names: Record<string, string>): MockAutopilot | null {
  const scenario = requested();
  if (scenario && !state) state = seed(scenario, names);
  const v = useSyncExternalStore(scenario ? subscribe : noop, () => (scenario ? version : -1));
  // Every page stays mounted, so the sample ticks for as long as the tab is open.
  useEffect(() => {
    if (scenario) ensureTimer();
  }, [scenario]);
  if (!scenario || !state) return null;
  void v;
  return {
    scenario,
    loading: scenario === "loading",
    autopilots: scenario === "loading" ? [] : state.list,
    btc: state.btc,
    ...api,
  };
}
