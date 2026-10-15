import { describe, expect, it } from "vitest";
import {
  amountText,
  canArmNow,
  dataBadge,
  heldBalances,
  liveMood,
  liveMoodWords,
  phraseMatches,
  readyCount,
  realExposure,
  secondsSince,
  shortAddress,
  signedBps,
  trimQty,
  walletCounts,
} from "./money";

describe("live state", () => {
  it("only an armed, non-paper, non-dry-run engine spends real money", () => {
    expect(liveMood({ armed: false, paper: false, dryRun: false })).toBe("off");
    expect(liveMood({ armed: true, paper: true, dryRun: false })).toBe("paper");
    expect(liveMood({ armed: true, paper: false, dryRun: true })).toBe("dry");
    expect(liveMood({ armed: true, paper: true, dryRun: true })).toBe("dry");
    expect(liveMood({ armed: true, paper: false, dryRun: false })).toBe("real");
  });

  it("says real money in words", () => {
    expect(liveMoodWords("real").badge).toBe("Real money");
    expect(liveMoodWords("real").detail).toMatch(/live account/);
    expect(liveMoodWords("off").value).toBe("Off");
    expect(liveMoodWords("paper").detail).toMatch(/no real money/);
  });

  it("sums only the real positions", () => {
    const r = realExposure([
      { live: true, qty: 2, lastPrice: 10, unrealized: 3 },
      { live: true, qty: -1, lastPrice: 5, unrealized: -1 },
      { live: false, qty: 100, lastPrice: 100, unrealized: 50 },
    ]);
    expect(r).toEqual({ count: 2, value: 25, unrealized: 2 });
    expect(realExposure([])).toEqual({ count: 0, value: 0, unrealized: 0 });
  });
});

describe("arming", () => {
  it("matches the phrase ignoring case and spaces, and nothing looser", () => {
    expect(phraseMatches("  arm live ", "ARM LIVE")).toBe(true);
    expect(phraseMatches("ARM", "ARM LIVE")).toBe(false);
    expect(phraseMatches("ARMLIVE", "ARM LIVE")).toBe(false);
  });

  it("needs the phrase, a disarmed engine and a venue", () => {
    expect(canArmNow("ARM LIVE", "ARM LIVE", false, 1)).toBe(true);
    expect(canArmNow("ARM LIVE", "ARM LIVE", true, 1)).toBe(false);
    expect(canArmNow("ARM LIVE", "ARM LIVE", false, 0)).toBe(false);
    expect(canArmNow("", "ARM LIVE", false, 2)).toBe(false);
  });

  it("counts checklist steps", () => {
    expect(readyCount([{ ok: true }, { ok: false }, { ok: true }])).toEqual({ done: 2, total: 3, all: false });
    expect(readyCount([{ ok: true }])).toEqual({ done: 1, total: 1, all: true });
    expect(readyCount([]).all).toBe(false);
  });
});

describe("numbers", () => {
  it("counts seconds and never goes negative", () => {
    expect(secondsSince(1000, 6000)).toBe(5);
    expect(secondsSince(9000, 6000)).toBe(0);
  });

  it("reads broker amounts sent as text", () => {
    expect(amountText("1234.5")).toBe("$1,234.50");
    expect(amountText("-20")).toBe("−$20.00");
    expect(amountText("n/a")).toBe("n/a");
    expect(amountText("")).toBe("");
  });

  it("signs basis points with the real minus", () => {
    expect(signedBps(1.234)).toBe("+1.2 bps");
    expect(signedBps(-0.44)).toBe("−0.4 bps");
    expect(signedBps(0.01)).toBe("0.0 bps");
    expect(signedBps(NaN)).toBe("n/a");
  });

  it("trims crypto amounts", () => {
    expect(trimQty(0)).toBe("0");
    expect(trimQty(0.00012)).toBe("0.00012");
    expect(trimQty(1234.56789)).toBe("1,234.5679");
    expect(trimQty(-0.5)).toBe("−0.5");
  });
});

describe("market data badge", () => {
  it("maps the status to a calm word", () => {
    expect(dataBadge(null)).toBeNull();
    expect(dataBadge({ tone: "red", label: "DATA STALE", detail: "" })).toEqual({ tone: "bad", word: "Stale" });
    expect(dataBadge({ tone: "amber", label: "DATA FAILOVER", detail: "" })?.word).toBe("On a fallback");
    expect(dataBadge({ tone: "amber", label: "DATA CHECK", detail: "" })?.word).toBe("Check");
    expect(dataBadge({ tone: "amber", label: "DATA", detail: "" })?.word).toBe("Partly stale");
    expect(dataBadge({ tone: "green", label: "DATA", detail: "" })).toEqual({ tone: "good", word: "Fresh" });
  });
});

describe("accounts", () => {
  it("keeps only the coins held", () => {
    expect(
      heldBalances([
        { asset: "BTC", free: 0, total: 0.1 },
        { asset: "ETH", free: 0, total: 0 },
      ]).map((b) => b.asset)
    ).toEqual(["BTC"]);
  });

  it("splits accounts by what Pythia may do there", () => {
    expect(walletCounts([{ canTrade: true }, { canTrade: false }, { canTrade: false, error: "timeout" }])).toEqual({
      total: 3,
      canTrade: 1,
      watchOnly: 2,
      failed: 1,
    });
  });

  it("cuts long addresses", () => {
    expect(shortAddress("0x1234567890abcdef")).toBe("0x12345678…");
    expect(shortAddress("short")).toBe("short");
  });
});
