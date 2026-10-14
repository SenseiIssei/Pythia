import { describe, expect, it } from "vitest";
import { ALPACA_CRYPTO_DEMO, alpacaMaker, alpacaMakerStats, makerShare, makerSummary, makerWindowLine } from "./maker";
import type { LiveStatus, MakerWindow } from "../types";

describe("maker execution in the UI", () => {
  it("reads the Alpaca crypto demo route's setting and says what it does", () => {
    const live = {
      makerRoutes: { [ALPACA_CRYPTO_DEMO]: { enabled: true, restSec: 20, maxTries: 3, fallbackBandBps: 50 } },
    } as unknown as LiveStatus;
    const s = alpacaMaker(live);
    expect(s?.enabled).toBe(true);
    expect(makerSummary(s)).toBe(
      "maker limits at the touch, re-priced every 20s, 3 tries, then a marketable limit up to 50 bps past the touch"
    );
    expect(makerSummary({ ...s!, enabled: false })).toContain("off");
    expect(makerSummary(undefined)).toBe("market orders");
    expect(alpacaMaker({} as LiveStatus)).toBeUndefined();
  });

  it("shows the maker share only for maker-route orders that filled", () => {
    expect(makerShare({ makerQty: 0.8, takerQty: 0.2 })).toBe("80% maker");
    expect(makerShare({ makerQty: 0, takerQty: 1 })).toBe("0% maker");
    expect(makerShare({ makerQty: 0, takerQty: 0 })).toBeNull();
    expect(makerShare({})).toBeNull();
  });

  it("says in one line how maker orders did over a window", () => {
    const w: MakerWindow = {
      days: 7,
      orders: 12,
      filledOrders: 12,
      makerFillRateQty: 0.834,
      makerFillRateOrders: 0.75,
      avgRestSec: 41.4,
      realisedBps: 16.23,
      modelledBps: 27,
      fallbacks: 3,
      noBookFallbacks: 1,
    };
    expect(makerWindowLine(w)).toBe(
      "7d: 12 orders, 83% maker by qty (75% of orders), rests 41s, cost 16.2 vs 27.0 bps modelled, 3 fallbacks (1 without a book)"
    );
    expect(makerWindowLine({ days: 30, orders: 0, filledOrders: 0, fallbacks: 0, noBookFallbacks: 0 })).toBe(
      "30d: no maker orders yet"
    );
    expect(makerWindowLine({ days: 30, orders: 1, filledOrders: 0, avgRestSec: 60, fallbacks: 1, noBookFallbacks: 0 })).toBe(
      "30d: 1 order, rests 60s, 1 fallback"
    );
    const live = { makerStats: [{ route: ALPACA_CRYPTO_DEMO, enabled: true, d7: w, d30: w }] } as unknown as LiveStatus;
    expect(alpacaMakerStats(live)?.d7.orders).toBe(12);
    expect(alpacaMakerStats({} as LiveStatus)).toBeUndefined();
  });
});
