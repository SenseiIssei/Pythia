import { describe, expect, it } from "vitest";
import { dataStatus, fmtAge, onFallback, venueOf } from "./dataHealth";
import type { DataHealth, KindHealth } from "./types";

function kind(k: Partial<KindHealth> & Pick<KindHealth, "kind">): KindHealth {
  return {
    primary: "kraken",
    active: "kraken",
    sources: [{ source: "kraken", markets: 20, failStreak: 0 }],
    lastUpdateAgeSec: 1,
    oldestUpdateAgeSec: 2,
    failovers24h: 0,
    stale: [],
    markets: 20,
    ...k,
  };
}

function health(over: Partial<DataHealth> = {}): DataHealth {
  return {
    running: true,
    ok: true,
    alerted: false,
    kinds: [
      kind({ kind: "quotes", primary: "kraken-ws", active: "kraken-ws" }),
      kind({ kind: "candles" }),
      kind({ kind: "books" }),
    ],
    stream: { enabled: true, connected: true, reconnects: 0 },
    markets: [],
    rejections: [],
    ...over,
  };
}

describe("data health summary", () => {
  it("says nothing where no feeds run", () => {
    expect(dataStatus(null)).toBeNull();
    expect(dataStatus(health({ running: false }))).toBeNull();
  });

  it("is green when everything is on its first choice", () => {
    const s = dataStatus(health())!;
    expect(s.tone).toBe("green");
    expect(s.detail).toContain("quotes on Kraken stream");
  });

  it("is red with the counts when data is stale", () => {
    const h = health({ ok: false });
    h.kinds[0] = kind({ kind: "quotes", stale: ["crypto:BTC/USD", "crypto:ETH/USD"] });
    const s = dataStatus(h)!;
    expect(s.tone).toBe("red");
    expect(s.label).toBe("DATA STALE");
    expect(s.detail).toContain("quotes stale for 2 of 20 markets");
  });

  it("warns on another venue, but not on the same venue's REST fallback", () => {
    const sameVenue = health();
    sameVenue.kinds[0] = kind({ kind: "quotes", primary: "kraken-ws", active: "kraken" });
    expect(dataStatus(sameVenue)!.tone).toBe("green");

    const otherVenue = health();
    otherVenue.kinds[1] = kind({ kind: "candles", primary: "kraken", active: "binance" });
    const s = dataStatus(otherVenue)!;
    expect(s.tone).toBe("amber");
    expect(s.detail).toContain("Candles on Binance, not Kraken");
  });

  it("warns while a quote is refused", () => {
    const h = health({ markets: [{ market: "crypto:BTC/USD", quotes: "kraken", suspect: "Kraken: 30.0% away from binance" }] });
    expect(dataStatus(h)!.label).toBe("DATA CHECK");
  });

  it("knows which sources share a venue and formats ages", () => {
    expect(venueOf("kraken-ws")).toBe("kraken");
    expect(venueOf("binance-vision")).toBe("binance");
    expect(onFallback(kind({ kind: "books", primary: "binance", active: "binance-vision" }))).toBe(false);
    expect(fmtAge(7)).toBe("7 s");
    expect(fmtAge(240)).toBe("4 min");
    expect(fmtAge(7200)).toBe("2 h");
    expect(fmtAge(null)).toBe("never");
  });
});
