import { describe, expect, it } from "vitest";
import { levelWord, num, pct, plural, share, usage } from "./format";

describe("numbers", () => {
  it("uses a real minus sign and no minus on zero", () => {
    expect(num(-0.4)).toBe("−0.40");
    expect(num(-0.0001)).toBe("0.00");
    expect(num(12.345, 1)).toBe("12.3");
    expect(num(1234.5)).toBe("1,234.50");
  });
  it("says n/a for what it cannot show", () => {
    expect(num(undefined)).toBe("n/a");
    expect(num(NaN)).toBe("n/a");
    expect(pct(null)).toBe("n/a");
    expect(share(Infinity)).toBe("n/a");
  });
  it("formats percents", () => {
    expect(pct(12.345)).toBe("12.3%");
    expect(pct(-3, 0)).toBe("−3%");
    expect(share(0.55)).toBe("55%");
    expect(share(0.1234, 1)).toBe("12.3%");
  });
});

describe("plural", () => {
  it("picks the word by count", () => {
    expect(plural(1, "trade")).toBe("1 trade");
    expect(plural(3, "trade")).toBe("3 trades");
    expect(plural(0, "entry", "entries")).toBe("0 entries");
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
  it("says each level in words", () => {
    expect(levelWord("off")).toBe("Off");
    expect(levelWord("ok")).toBe("Within the limit");
    expect(levelWord("near")).toBe("Close to the limit");
    expect(levelWord("over")).toBe("At the limit");
  });
});
