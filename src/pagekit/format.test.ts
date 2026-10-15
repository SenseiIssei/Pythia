import { describe, expect, it } from "vitest";
import { num, pct, plural, signedRatio, since, toneOf, usage, usd, usdShort } from "./format";

describe("toneOf", () => {
  it("reads up, down and flat with an epsilon", () => {
    expect(toneOf(1)).toBe("up");
    expect(toneOf(-1)).toBe("down");
    expect(toneOf(0.001)).toBe("flat");
    expect(toneOf(-0.004)).toBe("flat");
    expect(toneOf(0.2, 0.5)).toBe("flat");
  });
  it("calls missing numbers flat", () => {
    expect(toneOf(null)).toBe("flat");
    expect(toneOf(undefined)).toBe("flat");
    expect(toneOf(NaN)).toBe("flat");
  });
});

describe("amounts", () => {
  it("uses a real minus sign and no minus on zero", () => {
    expect(usd(-5)).toBe("−$5.00");
    expect(usd(1234.5)).toBe("$1,234.50");
    expect(usd(-0.001)).toBe("$0.00");
    expect(num(-0.4)).toBe("−0.40");
    expect(num(-0.0001)).toBe("0.00");
    expect(num(12.345, 1)).toBe("12.3");
  });
  it("says n/a for what it cannot show", () => {
    expect(usd(NaN)).toBe("n/a");
    expect(num(undefined)).toBe("n/a");
    expect(pct(null)).toBe("n/a");
    expect(signedRatio(Infinity)).toBe("n/a");
    expect(usdShort(NaN)).toBe("n/a");
  });
  it("shortens big amounts", () => {
    expect(usdShort(950)).toBe("$950");
    expect(usdShort(12_340)).toBe("$12.3k");
    expect(usdShort(4_100_000)).toBe("$4.1M");
    expect(usdShort(-2_500_000_000)).toBe("−$2.5B");
  });
  it("formats percents", () => {
    expect(pct(12.345)).toBe("12.3%");
    expect(signedRatio(0.0123)).toBe("+1.2%");
    expect(signedRatio(-0.004, 1)).toBe("−0.4%");
    expect(signedRatio(0.00001)).toBe("0.0%");
  });
});

describe("plural", () => {
  it("picks the word by count", () => {
    expect(plural(1, "trade")).toBe("1 trade");
    expect(plural(3, "trade")).toBe("3 trades");
    expect(plural(2, "pair", "pairs")).toBe("2 pairs");
    expect(plural(1200, "bar")).toBe("1,200 bars");
  });
});

describe("usage", () => {
  it("is off without a cap", () => {
    expect(usage(5, 0)).toEqual({ pct: 0, level: "off" });
    expect(usage(5, -1).level).toBe("off");
    expect(usage(NaN, 10).level).toBe("off");
  });
  it("climbs from ok to near to over", () => {
    expect(usage(5, 10)).toEqual({ pct: 50, level: "ok" });
    expect(usage(8, 10).level).toBe("near");
    expect(usage(10, 10).level).toBe("over");
    expect(usage(-3, 10)).toEqual({ pct: 0, level: "ok" });
  });
});

describe("since", () => {
  const now = 1_000_000_000;
  it("says it in words", () => {
    expect(since(now - 10_000, now)).toBe("just now");
    expect(since(now - 5 * 60_000, now)).toBe("5 min ago");
    expect(since(now - 3 * 3_600_000, now)).toBe("3 h ago");
    expect(since(now - 72 * 3_600_000, now)).toBe("3 days ago");
    expect(since(now + 60_000, now)).toBe("just now");
  });
});
