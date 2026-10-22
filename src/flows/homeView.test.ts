import { describe, expect, it } from "vitest";
import { autopilotsWords, change, combinedCurve, combinedHoldings, inRange, positionHoldings, usefulRanges, type Point } from "./homeView";
import type { AutopilotStatus, PositionView } from "../types";

const H = 3_600_000;
const D = 24 * H;

function ap(over: Partial<AutopilotStatus> & { id?: string } = {}): AutopilotStatus {
  const { id = "a", ...rest } = over;
  return {
    config: { id, name: id, mode: "paper", venue: "kraken", capitalUsd: 1000, sleeves: [], stop: { onTakeProfit: "stop" }, flattenOnStop: true },
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
    ...rest,
  } as AutopilotStatus;
}

function pos(over: Partial<PositionView>): PositionView {
  return { marketId: "m", venue: "crypto", symbol: "BTC/USD", qty: 1, avgPrice: 100, lastPrice: 110, unrealized: 10, mode: "paper", live: false, ...over };
}

describe("combinedCurve", () => {
  it("is empty without an active autopilot", () => {
    expect(combinedCurve([ap({ state: "stopped" })], 10)).toEqual([]);
  });

  it("passes a single autopilot's curve through", () => {
    const one = ap({ history: [[0, 1000], [H, 1010]], equity: 1010 });
    expect(combinedCurve([one], H)).toEqual([[0, 1000], [H, 1010]]);
  });

  it("adds gains on top of what all were given, so a new start is no jump", () => {
    const a = ap({ id: "a", history: [[0, 1000], [2 * H, 1100]], equity: 1100 });
    const b = ap({ id: "b", startedMs: H, startCapital: 500, history: [[H, 500], [2 * H, 450]], equity: 450 });
    const c = combinedCurve([a, b], 2 * H);
    expect(c[0]).toEqual([0, 1500]);
    // b starting at its own capital adds nothing.
    expect(c[1]).toEqual([H, 1500]);
    // Ends at the sum of both values.
    expect(c[c.length - 1]).toEqual([2 * H, 1550]);
  });
});

describe("inRange", () => {
  const pts: Point[] = [
    [0, 100],
    [5 * D, 120],
    [9 * D, 130],
    [10 * D, 125],
  ];
  it("keeps everything for Max", () => {
    expect(inRange(pts, "Max", 10 * D)).toBe(pts);
  });
  it("starts the range at the value it had then", () => {
    const w = inRange(pts, "1W", 10 * D);
    expect(w[0]).toEqual([3 * D, 100]);
    expect(w.slice(1)).toEqual([pts[1], pts[2], pts[3]]);
  });
  it("still draws a line when nothing moved inside the range", () => {
    const d = inRange(pts, "1D", 20 * D);
    expect(d).toEqual([
      [19 * D, 125],
      [20 * D, 125],
    ]);
  });
  it("does not invent a start before the first point", () => {
    expect(inRange(pts, "1Y", 10 * D)[0]).toEqual([0, 100]);
  });
});

describe("usefulRanges", () => {
  it("stops at the first range that shows everything", () => {
    expect(usefulRanges([[0, 1], [3 * D, 2]], 3 * D)).toEqual(["1D", "1W", "Max"]);
    expect(usefulRanges([[0, 1], [H, 2]], H)).toEqual(["1D", "Max"]);
    expect(usefulRanges([[0, 1], [400 * D, 2]], 400 * D)).toEqual(["1D", "1W", "1M", "1Y", "Max"]);
    expect(usefulRanges([], 0)).toEqual(["Max"]);
  });
});

describe("change", () => {
  it("measures first to last", () => {
    expect(change([[0, 200], [1, 250]])).toEqual({ abs: 50, pct: 25 });
    expect(change([[0, 200]])).toEqual({ abs: 0, pct: null });
  });
});

describe("holdings", () => {
  it("lists each asset once across autopilots", () => {
    const a = ap({ id: "a", held: ["m"] });
    const b = ap({ id: "b", held: ["m", "e"] });
    const list = combinedHoldings([a, b], [pos({ marketId: "m" }), pos({ marketId: "e", symbol: "ETH/USD", qty: 2, lastPrice: 200, avgPrice: 150, unrealized: 100 })]);
    expect(list.map((h) => h.marketId)).toEqual(["e", "m"]);
  });

  it("falls back to the account's positions", () => {
    const list = positionHoldings([pos({ qty: 0 }), pos({ marketId: "x", qty: 2 })]);
    expect(list).toHaveLength(1);
    expect(list[0].value).toBe(220);
    expect(list[0].pnlPct).toBeCloseTo(5);
  });
});

describe("the home portfolio's label", () => {
  it("says practice once real money runs beside it", () => {
    expect(autopilotsWords(1, false)).toBe("Your autopilot");
    expect(autopilotsWords(3, false)).toBe("Your 3 autopilots");
    expect(autopilotsWords(1, true)).toBe("Your practice autopilot");
    expect(autopilotsWords(2, true)).toBe("Your 2 practice autopilots");
  });
});
