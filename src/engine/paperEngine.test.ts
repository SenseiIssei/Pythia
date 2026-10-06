import { describe, expect, it } from "vitest";
import { PaperEngine, emptyLedger, strategyRegimeOk } from "./paperEngine";
import { oosIsRatio, median } from "./optimize";

describe("strategyRegimeOk", () => {
  it("blocks mean reversion in trends and trend following in chop", () => {
    expect(strategyRegimeOk("bollinger", "trending")).toBe(false);
    expect(strategyRegimeOk("rsi-reversal", "trending")).toBe(false);
    expect(strategyRegimeOk("ema-cross", "ranging")).toBe(false);
    expect(strategyRegimeOk("breakout", "ranging")).toBe(false);
  });

  it("lets everything through when the regime is unknown or matches", () => {
    expect(strategyRegimeOk("bollinger", "ranging")).toBe(true);
    expect(strategyRegimeOk("ema-cross", "trending")).toBe(true);
    expect(strategyRegimeOk("ema-cross", undefined)).toBe(true);
    expect(strategyRegimeOk("prob-edge", "trending")).toBe(true);
  });
});

describe("PaperEngine", () => {
  const BTC = "crypto:BTC/USD";

  it("charges the cost model on a paper round trip and reports gross, costs and net", () => {
    const e = new PaperEngine();
    expect(e.manualOrder(BTC, "buy", 1_000)).toBe("ok");
    const open = e.strategyList().find((s) => s.id === "manual")?.ledger;
    expect(open?.fees).toBeGreaterThan(0);
    expect(open?.pnl.gross).toBe(0); // nothing closed yet

    e.flatten(BTC);
    expect(e.positionViews().some((p) => p.marketId === BTC)).toBe(false);
    const s = e.strategyList().find((x) => x.id === "manual")!;
    const p = s.ledger!.pnl;
    expect(s.trades).toBe(1);
    // Same quote in and out: no gross, the loss is all costs.
    expect(Math.abs(p.gross)).toBeLessThan(1e-9);
    expect(p.costs).toBeGreaterThan(0);
    expect(p.gross - p.costs - p.net).toBeCloseTo(0, 9);
    expect(p.net).toBeCloseTo(s.pnl - s.ledger!.fees, 9);
    // Kraken's 40 bps taker fee on both sides of ~$1,000.
    expect(s.ledger!.fees).toBeGreaterThan(7);
    expect(s.ledger!.fees).toBeLessThan(9);
  });

  it("refuses Live with a reason, because nothing here can earn a passport", async () => {
    const e = new PaperEngine();
    const pp = e.passports();
    expect(pp.length).toBeGreaterThan(0);
    expect(pp.every((x) => !x.liveReady && x.gates.length === 8)).toBe(true);
    const id = e.strategyList()[0].id;
    await expect(e.setStrategyState(id, "live")).rejects.toThrow(/Not ready for real money/);
    expect(e.strategyList()[0].state).not.toBe("live");
    await e.setStrategyState(id, "paused");
    expect(e.strategyList()[0].state).toBe("paused");
  });

  it("deploys a new strategy in paper with a clean record", () => {
    const e = new PaperEngine();
    const base = e.strategyList()[0];
    e.addStrategy({ ...base, id: "copy", state: "live", ledger: { ...emptyLedger(), forwardTrades: 99 } });
    const copy = e.strategyList().find((s) => s.id === "copy")!;
    expect(copy.state).toBe("paper");
    expect(copy.ledger?.forwardTrades).toBe(0);
  });
});

describe("optimizer helpers", () => {
  it("gives no OOS/IS ratio against a non-positive in-sample Sharpe", () => {
    expect(oosIsRatio(1.2, 0.6)).toBeCloseTo(0.5);
    expect(oosIsRatio(0, 0.6)).toBeUndefined();
    expect(oosIsRatio(-0.5, 0.6)).toBeUndefined();
  });

  it("takes a proper median", () => {
    expect(median([])).toBe(0);
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 3, 2])).toBe(2.5);
  });
});
