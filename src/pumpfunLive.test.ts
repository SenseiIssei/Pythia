import { describe, expect, it, vi } from "vitest";
import {
  ALPHA_PHASE,
  modeWords,
  candles,
  ceilings,
  coinReturn,
  timeStopLeft,
  watchPumpfun,
  type FeedCoin,
  type FeedPoint,
  eur,
  exitWords,
  holdWords,
  limitInput,
  parseLimits,
  short,
  sol,
  solEurChange,
  solscanToken,
  stateLine,
  tradeStats,
  type PumpfunHard,
  type PumpfunTrade,
  type PumpfunView,
} from "./pumpfunLive";

function trade(over: Partial<PumpfunTrade>): PumpfunTrade {
  return {
    mode: "test", rule: "P_pool60", mint: "MINT", name: null, symbol: "AAA", signalMs: null, landMs: null, exitMs: 0, exitWhy: "trail",
    stakeSol: 0.01, proceedsSol: 0.01, pnlSol: 0, ret: 0, holdS: 60, latBuyMs: null, slip: null, ...over,
  };
}

describe("tradeStats", () => {
  it("adds the trades up oldest first, whatever order they come in", () => {
    const s = tradeStats([
      trade({ exitMs: 3, pnlSol: -0.004, proceedsSol: 0.006, ret: -0.4, holdS: 300 }),
      trade({ exitMs: 1, pnlSol: 0.01, proceedsSol: 0.02, ret: 1, holdS: 60, symbol: "WIN" }),
      trade({ exitMs: 2, pnlSol: -0.002, proceedsSol: 0.008, ret: -0.2, holdS: 120, symbol: "LOSS" }),
    ]);
    expect(s.n).toBe(3);
    expect(s.wins).toBe(1);
    expect(s.winRate).toBeCloseTo(1 / 3);
    expect(s.curve.map((x) => Number(x.toFixed(3)))).toEqual([0, 0.01, 0.008, 0.004]);
    expect(s.pnlSol).toBeCloseTo(0.004);
    expect(s.stakeSol).toBeCloseTo(0.03);
    expect(s.proceedsSol).toBeCloseTo(0.034);
    expect(s.avgRet).toBeCloseTo(0.4 / 3);
    expect(s.best?.symbol).toBe("WIN");
    expect(s.worst?.exitMs).toBe(3);
    expect(s.avgHoldS).toBeCloseTo(160);
  });

  it("is empty without trades", () => {
    const s = tradeStats([]);
    expect(s).toMatchObject({ n: 0, wins: 0, winRate: null, avgRet: null, best: null, worst: null, avgHoldS: null, curve: [0] });
  });
});

describe("eur", () => {
  const rate = { price: 93.08, open: 90, t: 0 };
  it("turns SOL into euro at the live rate, signed when asked", () => {
    const plain = (s: string) => s.replace(/[^0-9,.+-]/g, "");
    expect(plain(eur(0.1, rate))).toMatch(/^9[.,]31$/);
    expect(plain(eur(-0.0063, rate, true))).toMatch(/^-0[.,]59$/);
    expect(plain(eur(0.0109, rate, true))).toMatch(/^\+1[.,]01$/);
    expect(plain(eur(0.00001, rate, true))).toMatch(/^0[.,]00$/);
    expect(eur(0.1, null)).toBe("");
    expect(eur(null, rate)).toBe("");
  });

  it("knows the move since today's open", () => {
    expect(solEurChange(rate)).toBeCloseTo(0.0342, 3);
    expect(solEurChange(null)).toBeNull();
  });
});

describe("holdWords and solscanToken", () => {
  it("read like a person would say them", () => {
    expect(holdWords(42)).toBe("42 s");
    expect(holdWords(720)).toBe("12 min");
    expect(holdWords(3 * 3600 + 5 * 60)).toBe("3 h 05 min");
    expect(holdWords(null)).toBe("n/a");
    expect(solscanToken("88cjts6PyeAmnVmngQGaW23UDyTQUKKqjtNnynQMpump")).toBe("https://solscan.io/token/88cjts6PyeAmnVmngQGaW23UDyTQUKKqjtNnynQMpump");
  });
});

const HARD: PumpfunHard = { testMaxTotalSol: 2, testMaxDailyLossSol: 0.5, testMaxTradeSol: 0.05, fullMaxDailyLossSol: 1, fullMaxTradeSol: 0.1, maxOpen: 5 };
const ACK = { mode: "test" as const, strategy: "auto", maxTotalSol: 1, maxDailyLossSol: 0.3, maxTradeSol: 0.02 };

function view(over: Partial<PumpfunView> = {}, status: Partial<NonNullable<PumpfunView["status"]>> = {}): PumpfunView {
  return {
    running: true,
    address: "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
    settings: { maxTotalSol: null, maxDailyLossSol: null, maxTradeSol: null, maxOpen: null, updatedMs: 0 },
    killFile: false,
    trades: [],
    execution: null,
    hard: HARD,
    nowMs: 0,
    status: {
      t: 0, running: true, on: true, mode: "test", rule: "P_pool60", address: null, balanceSol: 1, balanceT: 0, holdings: [], positions: [], leftovers: [],
      pnlTodaySol: 0, tradesToday: 0, winsToday: 0, pnlTotalSol: 0, tradesTotal: 0, sinceMs: null, gate: [], refusing: null, ack: ACK, limits: null,
      stops: { daily: false, total: false }, kill: false, simulate: null, exposureSol: 0, skipped: {}, ...status,
    },
    ...over,
  };
}

describe("stateLine", () => {
  it("puts the kill switch first, then whether the service runs, then the stops", () => {
    expect(stateLine(view({ killFile: true })).level).toBe("bad");
    expect(stateLine(view({ killFile: true })).detail).toContain("Delete reports/pumpfun_rt/KILL");
    expect(stateLine(view({ running: false })).label).toBe("Live service not running");
    expect(stateLine(view({}, { stops: { daily: false, total: true } })).label).toBe("Total budget used up");
    expect(stateLine(view({}, { stops: { daily: true, total: false } })).level).toBe("warn");
    expect(stateLine(view()).label).toBe("Trading real money (Alpha phase)");
    expect(stateLine(view({}, { on: false, gate: ["no successful simulation yet"] })).detail).toBe("no successful simulation yet");
  });
});

describe("limits", () => {
  it("are capped by the confirmation file and by the code", () => {
    expect(ceilings(ACK, HARD)).toEqual({ maxTotalSol: 1, maxDailyLossSol: 0.3, maxTradeSol: 0.02, maxOpen: 5 });
    expect(ceilings({ ...ACK, maxTotalSol: 9, maxTradeSol: 1 }, HARD)?.maxTradeSol).toBe(0.05);
    expect(ceilings({ ...ACK, mode: "full", maxDailyLossSol: 0.4 }, HARD)).toEqual({ maxTotalSol: null, maxDailyLossSol: 0.4, maxTradeSol: 0.1, maxOpen: 5 });
    expect(ceilings(null, HARD)).toBeNull();
  });

  it("can only be lowered; empty means the file's value", () => {
    const c = ceilings(ACK, HARD);
    const ok = parseLimits({ maxTotalSol: "0,5", maxDailyLossSol: "", maxTradeSol: "0.01", maxOpen: "2" }, c);
    expect(ok.errors).toEqual({});
    expect(ok.patch).toEqual({ maxTotalSol: 0.5, maxDailyLossSol: null, maxTradeSol: 0.01, maxOpen: 2 });
    const bad = parseLimits({ maxTotalSol: "1.5", maxDailyLossSol: "-1", maxTradeSol: "abc", maxOpen: "9" }, c);
    expect(Object.keys(bad.errors).sort()).toEqual(["maxDailyLossSol", "maxOpen", "maxTotalSol", "maxTradeSol"]);
    expect(bad.errors.maxTotalSol).toContain("at most 1 SOL");
    expect(parseLimits({ maxTotalSol: "0.5", maxDailyLossSol: "", maxTradeSol: "", maxOpen: "" }, null).errors.maxTotalSol).toContain("Start the live service");
    expect(limitInput({ maxTotalSol: 0.5, maxDailyLossSol: null, maxTradeSol: null, maxOpen: 3, updatedMs: 1 })).toEqual({ maxTotalSol: "0.5", maxDailyLossSol: "", maxTradeSol: "", maxOpen: "3" });
  });
});

describe("words", () => {
  it("formats SOL, exits and addresses", () => {
    expect(sol(0.0123)).toBe("0.0123 SOL");
    expect(sol(-0.5, true)).toBe("-0.5000 SOL");
    expect(sol(0.25, true)).toBe("+0.2500 SOL");
    expect(sol(null)).toBe("n/a");
    expect(exitWords("pull")).toBe("liquidity pulled");
    expect(short("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU")).toBe("7xKX...gAsU");
  });
});

describe("the live chart's numbers", () => {
  const T = 1_792_700_000_000;
  const coin = (over: Partial<FeedCoin> = {}): FeedCoin => ({
    mint: "Coin1pump", pid: 1, rule: "P_pool0", symbol: "TST", name: "Test", venue: "pool", state: "open",
    signal_ms: T - 500, land_ms: T, entry_price: 2e-6, signal_price: 1.9e-6, cost_sol: 0.1, mark_sol: 0.11,
    tp: 0.3, sl: 0.2, time_s: 300, exit: null, points: [], ...over,
  });

  it("makes candles that open at the previous close and stay flat without trades", () => {
    const pts: FeedPoint[] = [[T + 1_000, 2, 0.5, 1], [T + 2_000, 3, 0.1, 0], [T + 3_000, 1.5, 0.2, 1], [T + 11_000, 4, 1, 1]];
    const c = candles(pts, 5_000);
    expect(c.map((b) => b.t)).toEqual([T, T + 5_000, T + 10_000]);
    expect(c[0]).toMatchObject({ open: 2, high: 3, low: 1.5, close: 1.5, buys: 0.7, sells: 0.1 });
    expect(c[1]).toMatchObject({ open: 1.5, high: 1.5, low: 1.5, close: 1.5, buys: 0, sells: 0 });
    expect(c[2]).toMatchObject({ open: 1.5, high: 4, low: 1.5, close: 4 });
    expect(candles(pts, 5_000, T + 21_000)).toHaveLength(5);                  // runs on to now
    expect(candles([], 5_000)).toEqual([]);
  });

  it("reads the return from the mark, the exit or the last trade", () => {
    expect(coinReturn(coin())).toBeCloseTo(0.1);
    expect(coinReturn(coin({ exit: { ms: T, price: 1, why: "tp", ret: 0.32, pnl_sol: 0.032 } }))).toBe(0.32);
    expect(coinReturn(coin({ mark_sol: null, points: [[T, 2.5e-6, 0.1, 1]] }))).toBeCloseTo(0.25);
    expect(coinReturn(coin({ mark_sol: null }))).toBeNull();
  });

  it("counts the time stop down and stops counting once sold", () => {
    expect(timeStopLeft(coin(), T + 60_000)).toBe(240);
    expect(timeStopLeft(coin(), T + 400_000)).toBe(0);
    expect(timeStopLeft(coin({ exit: { ms: T, price: 1, why: "time", ret: 0, pnl_sol: 0 } }), T)).toBeNull();
    expect(timeStopLeft(coin({ land_ms: null }), T)).toBeNull();
  });
});

describe("keeping the page current", () => {
  it("reads every 1.5 s when the socket never opens (a proxy without upgrades)", async () => {
    vi.useFakeTimers();
    vi.stubEnv("VITE_PYTHIA_SERVER", "/api/pythia");
    vi.stubGlobal("location", { origin: "https://panel.example.com" });
    const made: string[] = [];
    class NoSocket {
      onopen: (() => void) | null = null;
      onmessage: ((e: { data: string }) => void) | null = null;
      onclose: (() => void) | null = null;
      constructor(url: string) {
        made.push(url);
        setTimeout(() => this.onclose?.(), 10);           // refused before it ever opens
      }
      close() {}
    }
    vi.stubGlobal("WebSocket", NoSocket);
    const asked: string[] = [];
    vi.stubGlobal("fetch", async (u: string) => {
      asked.push(String(u));
      const body = String(u).endsWith("/feed") ? { t: asked.length, coins: [] } : { running: true, status: null, trades: [] };
      return new Response(JSON.stringify(body), { status: 200 });
    });
    const states: string[] = [];
    const feeds: unknown[] = [];
    const stop = watchPumpfun({ onView: () => {}, onFeed: (f) => feeds.push(f), onState: (s) => states.push(s) });
    await vi.advanceTimersByTimeAsync(50);                  // try 1 fails at once
    await vi.advanceTimersByTimeAsync(1_100);               // try 2 after 1 s, fails: polling starts
    expect(made).toEqual(["wss://panel.example.com/api/pythia/api/pumpfun/live/ws", expect.any(String)]);
    expect(asked.some((u) => u.endsWith("/api/pythia/api/pumpfun/live/feed"))).toBe(true);
    expect(states).toContain("polling");
    const n = asked.length;
    await vi.advanceTimersByTimeAsync(1_600);
    expect(asked.length).toBeGreaterThan(n);                 // and keeps reading
    expect(feeds.length).toBeGreaterThan(1);                 // each new feed handed on
    stop();
    const m = asked.length;
    await vi.advanceTimersByTimeAsync(5_000);
    expect(asked.length).toBe(m);                            // stopped with the page
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.useRealTimers();
  });
});

describe("modeWords", () => {
  it("calls the live test the Alpha phase; the files keep mode test", () => {
    expect(modeWords("test")).toBe("Alpha phase");
    expect(ALPHA_PHASE).toBe("Alpha phase");
    expect(modeWords("full")).toBe("Full");
    expect(modeWords(null)).toBe("");
  });
});
