import { describe, expect, it } from "vitest";
import { estimatedFeeTotal, pairsToShow, qty9, reconcileHeadline } from "./demoReconcile";
import type { DemoReconcile, PairCheck } from "./types";

const pair = (symbol: string, status: PairCheck["status"], diffUsd = 0): PairCheck => ({
  symbol,
  markets: [`crypto:${symbol}`],
  pythia: 1,
  alpaca: 1,
  diff: 0,
  diffUsd,
  status,
  note: "",
});

const base: DemoReconcile = {
  checkedAt: 1_000_000,
  pairs: [],
  mismatches: 0,
  openOrders: 0,
  strayOrders: [],
  estimatedFees: [],
};

describe("demo reconcile on the Live page", () => {
  it("says when it ran and whether the pairs match", () => {
    const ok = { ...base, pairs: [pair("BTC/USD", "ok"), pair("PEPE/USD", "ok")] };
    expect(reconcileHeadline(ok, 1_000_000 + 5 * 60_000)).toBe("Checked 5 min ago: all 2 pairs match Alpaca paper");
    const off = { ...ok, mismatches: 1 };
    expect(reconcileHeadline(off, 1_000_000)).toBe("Checked just now: 1 of 2 pairs differ from Alpaca paper");
    const failed = { ...ok, error: "network error", failedAt: 2_000_000 };
    expect(reconcileHeadline(failed, 2_000_000)).toContain("last read failed: network error");
    expect(reconcileHeadline({ ...base, checkedAt: 0, error: "no keys" }, 0)).toBe("Alpaca paper not read yet: no keys");
  });

  it("shows what needs a look first and leaves plain matches out", () => {
    const d = {
      ...base,
      pairs: [pair("BTC/USD", "ok"), pair("ETH/USD", "corrected", 5), pair("SOL/USD", "mismatch", 2), pair("DOGE/USD", "untracked", 9)],
    };
    expect(pairsToShow(d).map((p) => p.symbol)).toEqual(["DOGE/USD", "SOL/USD", "ETH/USD"]);
  });

  it("adds up the estimated fees and writes quantities with up to 9 decimals", () => {
    const fee = { orderId: "o", marketId: "m", symbol: "BTC/USD", side: "buy" as const, strategyId: "s", notional: 1000, rateBps: 25, ts: 0, paper: true };
    expect(estimatedFeeTotal({ ...base, estimatedFees: [{ ...fee, usd: 2.5 }, { ...fee, usd: 1.25 }] })).toBe(3.75);
    expect(qty9(49452471.482889)).toBe("49452471.482889");
    expect(qty9(0.007471)).toBe("0.007471");
    expect(qty9(2)).toBe("2");
  });
});
