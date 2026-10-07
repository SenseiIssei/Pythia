import { describe, expect, it } from "vitest";
import {
  DAY_MS,
  analyse,
  breakdown,
  compareWithHold,
  curve,
  floorAtStart,
  maturity,
  worstDip,
} from "./autopilot";
import type { AutopilotStatus } from "./types";

function status(over: Partial<AutopilotStatus> = {}): AutopilotStatus {
  return {
    config: {
      id: "a",
      name: "A",
      mode: "paper",
      venue: "crypto",
      capitalUsd: 10_000,
      sleeves: [],
      stop: { onTakeProfit: "stop" },
      flattenOnStop: true,
    },
    state: "running",
    startedMs: 0,
    startCapital: 10_000,
    equity: 10_000,
    pnl: 0,
    pnlPct: 0,
    peakEquity: 10_000,
    drawdownPct: 0,
    floorEquity: 0,
    trades: 0,
    fees: 0,
    bySleeve: [],
    history: [],
    ...over,
  };
}

describe("floorAtStart", () => {
  it("has no floor when no loss rule is set", () => {
    expect(floorAtStart(10_000, { onTakeProfit: "stop" }).floor).toBeNull();
  });

  it("takes the highest of the loss rules, because that one is hit first", () => {
    const p = floorAtStart(10_000, { maxLossPct: 15, maxLossUsd: 1_000, trailingPct: 20, onTakeProfit: "stop" });
    expect(p.floor).toBe(9_000);
    expect(p.by).toBe("lossUsd");
  });

  it("ignores empty and zero limits", () => {
    expect(floorAtStart(10_000, { maxLossPct: 0, maxLossUsd: NaN, onTakeProfit: "stop" }).floor).toBeNull();
  });

  it("never goes below zero and reports the take-profit level", () => {
    const p = floorAtStart(500, { maxLossUsd: 900, takeProfitPct: 20, onTakeProfit: "lock" });
    expect(p.floor).toBe(0);
    expect(p.takeProfitAt).toBe(600);
  });
});

describe("worstDip", () => {
  it("finds the deepest fall from a high to a later low", () => {
    const d = worstDip([
      [0, 100],
      [1, 120],
      [2, 90],
      [3, 130],
      [4, 110],
    ]);
    expect(d?.pct).toBeCloseTo(25);
    expect(d?.usd).toBe(30);
    expect(d?.peakMs).toBe(1);
    expect(d?.troughMs).toBe(2);
  });

  it("is null for a curve that only rises", () => {
    expect(worstDip([[0, 1], [1, 2], [2, 3]])).toBeNull();
  });
});

describe("breakdown", () => {
  it("treats pnl as net of fees and reports the cost share of gross", () => {
    const b = breakdown(status({ pnl: 900, fees: 100 }));
    expect(b.gross).toBe(1_000);
    expect(b.costShare).toBeCloseTo(0.1);
    expect(b.costHeavy).toBe(false);
  });

  it("flags fees paid on no gross profit", () => {
    const b = breakdown(status({ pnl: -150, fees: 50 }));
    expect(b.costShare).toBeUndefined();
    expect(b.costHeavy).toBe(true);
  });
});

describe("maturity", () => {
  it("needs both 30 days and 30 trades", () => {
    expect(maturity(40, 12)).toMatchObject({ enough: false, daysLeft: 0, tradesLeft: 18 });
    expect(maturity(29.2, 50)).toMatchObject({ enough: false, daysLeft: 1, tradesLeft: 0 });
    expect(maturity(30, 30).enough).toBe(true);
  });
});

describe("curve", () => {
  it("ends at the current equity", () => {
    const pts = curve(status({ history: [[0, 10_000], [10, 10_100]], equity: 10_200 }), 20);
    expect(pts[pts.length - 1]).toEqual([20, 10_200]);
  });

  it("draws start to now when there is no history yet", () => {
    expect(curve(status({ startedMs: 5, equity: 9_900 }), 50)).toEqual([[5, 10_000], [50, 9_900]]);
  });
});

describe("compareWithHold", () => {
  const times = [0, 10, 20, 30, 40];
  const closes = [100, 110, 105, 120, 130];
  const run: [number, number][] = [[0, 1_000], [20, 1_050], [40, 1_020]];

  it("compares the same window", () => {
    const c = compareWithHold(run, times, closes, 0, 40);
    expect(c?.holdPct).toBeCloseTo(30);
    expect(c?.runPct).toBeCloseTo(2);
    expect(c?.partial).toBe(false);
  });

  it("says when the price history does not reach back to the start", () => {
    const c = compareWithHold(run, [20, 30, 40], [105, 120, 130], 0, 40);
    expect(c?.fromMs).toBe(20);
    expect(c?.partial).toBe(true);
    expect(c?.runPct).toBeCloseTo((1_020 / 1_050 - 1) * 100);
  });

  it("refuses to guess without bar times", () => {
    expect(compareWithHold(run, undefined, closes, 0, 40)).toBeNull();
    expect(compareWithHold(run, [100, 110], [1, 2], 0, 40)).toBeNull();
  });
});

describe("analyse", () => {
  it("reports trades per day and sorts strategies best first", () => {
    const a = analyse(
      status({
        startedMs: 0,
        stoppedMs: 4 * DAY_MS,
        state: "stopped",
        trades: 10,
        bySleeve: [
          { strategyId: "x", name: "X", weight: 0.5, pnl: -5, trades: 4, why: "" },
          { strategyId: "y", name: "Y", weight: 0.5, pnl: 20, trades: 6, why: "" },
        ],
      }),
      99 * DAY_MS,
    );
    expect(a.days).toBe(4);
    expect(a.tradesPerDay).toBe(2.5);
    expect(a.sleeves.map((s) => s.strategyId)).toEqual(["y", "x"]);
  });

  it("does not invent a daily rate in the first hour", () => {
    expect(analyse(status({ trades: 3 }), 10 * 60_000).tradesPerDay).toBeNull();
  });
});
