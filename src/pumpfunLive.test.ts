import { describe, expect, it } from "vitest";
import { ceilings, exitWords, limitInput, parseLimits, short, sol, stateLine, type PumpfunHard, type PumpfunView } from "./pumpfunLive";

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
    expect(stateLine(view()).label).toBe("Trading real money (test)");
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
