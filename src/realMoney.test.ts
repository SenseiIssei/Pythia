import { describe, expect, it } from "vitest";
import { autopilotLine, combineLines, euro, liveFills, pumpfunLine, realMoneyTotal, usdToEur } from "./realMoney";
import type { PumpfunTrade } from "./pumpfunLive";
import type { JournalEntry } from "./types";

const rate = { price: 100, open: 95, t: 0 };
const eurUsd = { price: 1.25, open: 1.2, t: 0 };
const trade = (exitMs: number, pnlSol: number): PumpfunTrade => ({
  mode: "test", rule: "P_pool0", mint: "M", name: null, symbol: "A", signalMs: null, landMs: null, exitMs, exitWhy: "tp",
  stakeSol: 0.1, proceedsSol: 0.1 + pnlSol, pnlSol, ret: pnlSol / 0.1, holdS: 10, latBuyMs: null, slip: null,
});

describe("pumpfunLine", () => {
  it("adds the kept trades up in euro and ends at the bot's total", () => {
    // Total -0.05 SOL, the kept trades add to +0.01: -0.06 came before them.
    const l = pumpfunLine([trade(2_000, -0.01), trade(1_000, 0.02)], -0.05, rate);
    expect(l.map((p) => p[0])).toEqual([999, 1_000, 2_000]);
    expect(l.map((p) => Math.round(p[1] * 100) / 100)).toEqual([-6, -4, -5]);
  });

  it("is empty without a SOL price or a closed trade", () => {
    expect(pumpfunLine([trade(1, 0.1)], 0.1, null)).toEqual([]);
    expect(pumpfunLine([], 0.1, rate)).toEqual([]);
  });
});

describe("autopilotLine and usdToEur", () => {
  it("turns equity into euro P&L over what it was given", () => {
    expect(autopilotLine({ startCapital: 100, history: [[1, 100], [2, 125], [3, 75]] }, eurUsd)).toEqual([[1, 0], [2, 20], [3, -20]]);
    expect(autopilotLine({ startCapital: 100, history: [[1, 110]] }, null)).toEqual([]);
    expect(usdToEur(125, eurUsd)).toBe(100);
    expect(usdToEur(125, null)).toBeNull();
  });
});

describe("combineLines", () => {
  it("sums each line's last value at every step, a finished line keeps its last value", () => {
    const a: [number, number][] = [[1, 10], [3, 20]];
    const b: [number, number][] = [[2, -5], [4, -1]];
    expect(combineLines([a, b, []])).toEqual([[1, 10], [2, 5], [3, 15], [4, 19]]);
    expect(combineLines([])).toEqual([]);
  });
});

describe("realMoneyTotal", () => {
  it("adds the pump.fun bot and the autopilots in euro", () => {
    const t = realMoneyTotal(-0.05, rate, [{ pnl: 25 }, { pnl: -12.5 }], eurUsd);
    expect(t.pumpfunEur).toBeCloseTo(-5);
    expect(t.autopilotsEur).toBeCloseTo(10);
    expect(t.eur).toBeCloseTo(5);
    expect(t.missing).toEqual([]);
  });

  it("says what it left out when a rate is missing", () => {
    const t = realMoneyTotal(-0.05, null, [{ pnl: 25 }], null);
    expect(t.eur).toBe(0);
    expect(t.autopilotsUsd).toBe(25);
    expect(t.missing).toEqual(["pump.fun (no SOL/EUR price)", "the autopilots (no EUR/USD rate)"]);
    expect(realMoneyTotal(null, null, [], null).missing).toEqual([]);
  });
});

describe("liveFills", () => {
  const e = (id: string, kind: JournalEntry["kind"], mode: JournalEntry["mode"], message: string): JournalEntry => ({ id, ts: 1, kind, mode, message });
  it("keeps the journal's real-money fills only", () => {
    const j = [e("1", "fill", "live", "kraken BUY 0.01 BTC"), e("2", "fill", "paper", "paper"), e("3", "fill", "live", "DEMO alpaca"), e("4", "order", "live", "order")];
    expect(liveFills(j).map((x) => x.id)).toEqual(["1"]);
  });
});

describe("euro", () => {
  it("signs and rounds", () => {
    expect(euro(null)).toBe("n/a");
    expect(euro(0.001, true)).not.toMatch(/^[+-]/);
    expect(euro(-3.5, true).startsWith("-")).toBe(true);
    expect(euro(3.5, true).startsWith("+")).toBe(true);
  });
});
