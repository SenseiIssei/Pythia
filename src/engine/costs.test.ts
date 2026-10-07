import { describe, expect, it } from "vitest";
import { breakdown, costVenueFor, impactBps, modelFor, paperFill, roundTripBps, scaled, slippageBps } from "./costs";
import type { CostModel } from "../types";

describe("the shared cost file", () => {
  it("carries the same public fees the Rust tests pin", () => {
    expect(modelFor("kraken", "BTC/USD").takerBps).toBe(40);
    expect(modelFor("kraken", "BTC/USD").makerBps).toBe(25);
    expect(modelFor("binance", "ETH/USD").takerBps).toBe(10);
    expect(modelFor("okx", "BTC/USD").makerBps).toBe(8);
    expect(modelFor("alpaca", "AAPL").takerBps).toBe(0);
  });

  it("gives majors tighter spreads than alts, and Binance tighter than Kraken", () => {
    const kBtc = modelFor("kraken", "BTC/USD").halfSpreadBps;
    expect(kBtc).toBeLessThan(modelFor("kraken", "DOT/USD").halfSpreadBps);
    expect(modelFor("binance", "BTC/USD").halfSpreadBps).toBeLessThan(kBtc);
    // Unlisted instruments get the venue default.
    expect(modelFor("kraken", "SHIB/USD").halfSpreadBps).toBe(25);
  });

  it("charges crypto as the configured exchange, Kraken by default", () => {
    expect(costVenueFor("crypto")).toBe("kraken");
    expect(costVenueFor("crypto", "binance")).toBe("binance");
    expect(costVenueFor("alpaca", "binance")).toBe("alpaca");
  });
});

describe("the cost model", () => {
  const m: CostModel = {
    takerBps: 10,
    makerBps: 2,
    halfSpreadBps: 3,
    impactCoeff: 4,
    borrowBpsYr: 0,
    minNotional: 1,
    defaultDepth: 10_000,
  };

  it("follows the square-root law for impact", () => {
    expect(impactBps(m, 10_000)).toBeCloseTo(4);
    expect(impactBps(m, 2_500)).toBeCloseTo(2);
    expect(impactBps(m, 10_000, 40_000)).toBeCloseTo(2);
    expect(impactBps({ ...m, defaultDepth: 0 }, 1e6)).toBe(0);
  });

  it("prices a round trip as two taker sides", () => {
    expect(slippageBps(m, 10_000)).toBeCloseTo(7);
    expect(roundTripBps(m, 10_000)).toBeCloseTo(34);
    expect(roundTripBps(scaled(m, 2), 10_000)).toBeCloseTo(68);
    expect(roundTripBps(scaled(m, 0), 10_000)).toBe(0);
  });

  it("fills a paper buy above and a sell below the quote, with the taker fee", () => {
    const buy = paperFill(m, "buy", 1, 10_000);
    expect(buy.price).toBeCloseTo(10_000 * (1 + 7 / 10_000));
    expect(buy.fee).toBeCloseTo(buy.price * 0.001);
    expect(buy.slippage).toBeCloseTo(7);
    const sell = paperFill(m, "sell", 1, 10_000);
    expect(sell.price).toBeLessThan(10_000);
  });

  it("keeps prediction-market fills inside (0, 1)", () => {
    const wide: CostModel = { ...m, halfSpreadBps: 5_000 };
    expect(paperFill(wide, "buy", 10, 0.98, true).price).toBeLessThanOrEqual(0.999);
    expect(paperFill(wide, "sell", 10, 0.01, true).price).toBeGreaterThanOrEqual(0.001);
  });
});

describe("breakdown", () => {
  it("always adds up and flags costs above 40 % of gross", () => {
    const ok = breakdown(100, 30);
    expect(ok.net).toBe(70);
    expect(ok.costHeavy).toBe(false);
    expect(breakdown(100, 41).costHeavy).toBe(true);
    const losing = breakdown(-5, 10);
    expect(losing.net).toBe(-15);
    expect(losing.costShare).toBeUndefined();
    expect(losing.costHeavy).toBe(true);
    expect(breakdown(10, -1).net).toBe(11);
  });
});
