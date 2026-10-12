import { describe, expect, it } from "vitest";
import { ALPACA_CRYPTO_DEMO, alpacaMaker, makerShare, makerSummary } from "./maker";
import type { LiveStatus } from "../types";

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
});
