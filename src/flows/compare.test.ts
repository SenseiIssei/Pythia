import { describe, expect, it } from "vitest";
import { MAX_SERIES, chartFrame, combinedSeries, compareRows, fmtPct, leaderLine, niceStep, valueAt } from "./compare";
import { holdings } from "../practice";
import type { AutopilotStatus, PositionView } from "../types";

const DAY = 86_400_000;

function status(id: string, over: Partial<AutopilotStatus> = {}): AutopilotStatus {
  return {
    config: {
      id,
      name: `AP ${id}`,
      mode: "demo",
      venue: "alpaca",
      assetClass: "crypto",
      capitalUsd: 1000,
      sleeves: [],
      stop: { onTakeProfit: "stop" },
      flattenOnStop: true,
    },
    state: "running",
    stopReason: null,
    pausedReason: null,
    stoppedMs: null,
    targetEquity: null,
    openPositions: 0,
    lastAction: null,
    startedMs: 0,
    startCapital: 1000,
    equity: 1000,
    pnl: 0,
    pnlPct: 0,
    peakEquity: 1000,
    drawdownPct: 0,
    floorEquity: null,
    trades: 0,
    fees: 0,
    bySleeve: [],
    history: [],
    ...over,
  };
}

describe("compareRows", () => {
  const a = status("a", {
    startedMs: 0,
    startCapital: 10_000,
    equity: 10_500,
    pnl: 500,
    pnlPct: 5,
    drawdownPct: 1,
    maxDrawdownPct: 4,
    trades: 12,
    fees: 25,
    cash: 2_000,
    benchmark: { symbol: "BTC/USD", name: "BTC buy and hold", returnPct: 8, excessPct: -3 },
  });
  const b = status("b", {
    startedMs: 5 * DAY,
    startCapital: 2_000,
    equity: 1_900,
    pnl: -100,
    pnlPct: -5,
    trades: 3,
    fees: 4,
    benchmark: { symbol: "SPY", name: "SPY buy and hold", returnPct: 1, excessPct: -6 },
    history: [
      [5 * DAY, 2_000],
      [6 * DAY, 2_200],
      [7 * DAY, 1_900],
    ],
  });

  it("puts every number of each autopilot side by side", () => {
    const [ra, rb] = compareRows([a, b], 10 * DAY);
    expect(ra).toMatchObject({ id: "a", returnPct: 5, benchLabel: "Bitcoin", benchPct: 8, vsBenchPts: -3, maxDrawdownPct: 4, trades: 12, fees: 25, cash: 2_000 });
    expect(ra.feesPct).toBeCloseTo(0.25);
    expect(ra.days).toBeCloseTo(10);
    expect(rb).toMatchObject({ benchLabel: "SPY", benchPct: 1, vsBenchPts: -6, cash: null });
    // No engine figure: the deepest fall comes from its own history.
    expect(rb.maxDrawdownPct).toBeCloseTo((300 / 2_200) * 100);
  });

  it("keeps an autopilot's colour by its start, whatever the list order", () => {
    const rows = compareRows([b, a], 10 * DAY);
    expect(rows.map((r) => [r.id, r.slot])).toEqual([
      ["b", 1],
      ["a", 0],
    ]);
    const many = Array.from({ length: MAX_SERIES + 2 }, (_, i) => status(`x${i}`, { startedMs: i }));
    const slots = compareRows(many, 1).map((r) => r.slot);
    expect(slots.filter((s) => s === null)).toHaveLength(2);
    expect(new Set(slots.filter((s) => s !== null)).size).toBe(MAX_SERIES);
  });

  it("says who leads, and that a young comparison says little", () => {
    expect(leaderLine(compareRows([a, b], 20 * DAY))).toBe("AP a leads at +5.00%, AP b trails at −5.00%.");
    expect(leaderLine(compareRows([a, b], 6 * DAY))).toContain("Under a week of running says little yet");
    expect(leaderLine(compareRows([a], 10 * DAY))).toBeNull();
  });
});

describe("combinedSeries", () => {
  it("puts different amounts on one axis as a return from each one's own amount", () => {
    const a = status("a", { startCapital: 10_000, equity: 11_000, history: [[0, 10_000], [DAY, 10_500]] });
    const b = status("b", { startedMs: DAY / 2, startCapital: 500, equity: 450, history: [[DAY / 2, 500]] });
    const [sa, sb] = combinedSeries([b, a], 2 * DAY);
    expect(sa.id).toBe("a");
    expect(sa.points.map((p) => p[0])).toEqual([0, DAY, 2 * DAY]);
    sa.points.map((p) => p[1]).forEach((v, i) => expect(v).toBeCloseTo([0, 5, 10][i], 9));
    expect(sb.points[sb.points.length - 1][1]).toBeCloseTo(-10);
    const f = chartFrame([sa, sb])!;
    expect(f.lo).toBeLessThanOrEqual(-10);
    expect(f.hi).toBeGreaterThanOrEqual(10);
    expect(f.ticks).toContain(0);
    expect(valueAt(sb.points, DAY / 4)).toBeNull();
    expect(valueAt(sa.points, 1.5 * DAY)).toBeCloseTo(5, 9);
  });

  it("rounds the axis to plain steps", () => {
    expect(niceStep(0.3)).toBeCloseTo(0.5);
    expect(niceStep(3)).toBe(5);
    expect(niceStep(12)).toBe(20);
    expect(fmtPct(-0.001)).toBe("0.00%");
  });
});

describe("holdings with books", () => {
  it("shows each autopilot only what its own book holds, though both hold BTC", () => {
    const base = { venue: "crypto" as const, symbol: "BTC/USD", avgPrice: 100, lastPrice: 110, mode: "paper" as const, live: false };
    const positions: PositionView[] = [
      { ...base, key: "a|crypto:BTC/USD", book: "a", marketId: "crypto:BTC/USD", qty: 2, unrealized: 20 },
      { ...base, key: "b|crypto:BTC/USD", book: "b", marketId: "crypto:BTC/USD", qty: 1, unrealized: 10 },
      { ...base, key: "crypto:BTC/USD", marketId: "crypto:BTC/USD", qty: 5, unrealized: 50 },
    ];
    const held = ["crypto:BTC/USD"];
    expect(holdings(status("a", { held }), positions).map((h) => h.qty)).toEqual([2]);
    expect(holdings(status("b", { held }), positions).map((h) => h.qty)).toEqual([1]);
    // An older engine has no books: its markets decide.
    const old = positions.map(({ key: _k, book: _b, ...p }) => p).slice(2);
    expect(holdings(status("a", { held }), old).map((h) => h.qty)).toEqual([5]);
  });
});
