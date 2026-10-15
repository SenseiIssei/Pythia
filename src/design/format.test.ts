import { describe, expect, it } from "vitest";
import { ago, changeTone, compactMoney, money, price, seriesChange, signedMoney, signedPct, signedRatio, tickerHue, tickerOf } from "./format";
import { chartGeometry, nearestIndex, smoothPath, thin } from "./chartPath";

const M = "−";

describe("money", () => {
  it("formats dollars with two decimals and grouping", () => {
    expect(money(1234.5)).toBe("$1,234.50");
    expect(money(0)).toBe("$0.00");
    expect(money(12, 0)).toBe("$12");
  });
  it("uses the real minus sign and never shows a negative zero", () => {
    expect(money(-5)).toBe(`${M}$5.00`);
    expect(money(-0.001)).toBe("$0.00");
  });
  it("reads n/a for numbers that are not numbers", () => {
    expect(money(NaN)).toBe("n/a");
    expect(money(Infinity)).toBe("n/a");
  });
});

describe("signed amounts", () => {
  it("puts a plus on gains and a minus on losses", () => {
    expect(signedMoney(12.345)).toBe("+$12.35");
    expect(signedMoney(-5)).toBe(`${M}$5.00`);
    expect(signedMoney(0.004)).toBe("$0.00");
    expect(signedMoney(NaN)).toBe("n/a");
  });
  it("formats percents in percent units", () => {
    expect(signedPct(1.234)).toBe("+1.23%");
    expect(signedPct(-0.4)).toBe(`${M}0.40%`);
    expect(signedPct(0.001)).toBe("0.00%");
    expect(signedPct(null)).toBe("n/a");
    expect(signedPct(2, 0)).toBe("+2%");
  });
  it("formats fractions as percents", () => {
    expect(signedRatio(0.0123)).toBe("+1.23%");
    expect(signedRatio(-0.5, 0)).toBe(`${M}50%`);
    expect(signedRatio(undefined)).toBe("n/a");
  });
});

describe("compact and price", () => {
  it("shortens big amounts", () => {
    expect(compactMoney(950)).toBe("$950");
    expect(compactMoney(1234)).toBe("$1.2K");
    expect(compactMoney(56_000)).toBe("$56K");
    expect(compactMoney(3_400_000)).toBe("$3.4M");
    expect(compactMoney(-2_000_000_000)).toBe(`${M}$2.0B`);
    expect(compactMoney(9.5)).toBe("$9.50");
  });
  it("gives tiny prices enough decimals to move", () => {
    expect(price(64_123.4)).toBe("$64,123.40");
    expect(price(1.5)).toBe("$1.50");
    expect(price(0.1234)).toBe("$0.1234");
    expect(price(0.00001234)).toBe("$0.000012");
  });
});

describe("change tone", () => {
  it("has a dead band around zero", () => {
    expect(changeTone(1)).toBe("up");
    expect(changeTone(-1)).toBe("down");
    expect(changeTone(0.001)).toBe("flat");
    expect(changeTone(null)).toBe("flat");
    expect(changeTone(NaN)).toBe("flat");
  });
  it("measures a series from first to last point", () => {
    expect(seriesChange([100, 90, 110])).toEqual({ abs: 10, pct: 10, tone: "up" });
    const down = seriesChange([200, 150]);
    expect(down.tone).toBe("down");
    expect(down.pct).toBe(-25);
    expect(seriesChange([5])).toEqual({ abs: 0, pct: null, tone: "flat" });
    expect(seriesChange([0, 5]).pct).toBeNull();
    expect(seriesChange([NaN, 10, 12]).abs).toBe(2);
  });
});

describe("tickers", () => {
  it("takes the base of a pair", () => {
    expect(tickerOf("BTC/USD")).toBe("BTC");
    expect(tickerOf("eth-usdt")).toBe("ETH");
    expect(tickerOf("AAPL")).toBe("AAPL");
    expect(tickerOf("DOGECOIN")).toBe("DOGE");
    expect(tickerOf("")).toBe("?");
  });
  it("gives a ticker the same hue every time, whatever the quote", () => {
    expect(tickerHue("BTC/USD")).toBe(tickerHue("BTC/USDT"));
    expect(tickerHue("BTC")).toBeGreaterThanOrEqual(0);
    expect(tickerHue("BTC")).toBeLessThan(360);
  });
});

describe("ago", () => {
  const now = 1_000_000_000_000;
  it("reads like a person would say it", () => {
    expect(ago(now - 10_000, now)).toBe("just now");
    expect(ago(now - 5 * 60_000, now)).toBe("5 min ago");
    expect(ago(now - 3 * 3_600_000, now)).toBe("3 h ago");
    expect(ago(now - 3 * 86_400_000, now)).toBe("3 d ago");
    expect(ago(now + 60_000, now)).toBe("just now");
  });
});

describe("chart geometry", () => {
  it("thins long series but keeps both ends", () => {
    const k = thin(10_000, 100);
    expect(k.length).toBeLessThanOrEqual(100);
    expect(k[0]).toBe(0);
    expect(k[k.length - 1]).toBe(9_999);
    expect(thin(5, 100)).toEqual([0, 1, 2, 3, 4]);
  });

  it("needs two finite points", () => {
    expect(chartGeometry([1], 100, 50)).toBeNull();
    expect(chartGeometry([NaN, 1, NaN], 100, 50)).toBeNull();
  });

  it("spans the width and keeps the line inside the padding", () => {
    const g = chartGeometry([1, 3, 2, 5], 100, 50, 5)!;
    expect(g.xs[0]).toBe(0);
    expect(g.xs[g.xs.length - 1]).toBe(100);
    for (const y of g.ys) {
      expect(y).toBeGreaterThanOrEqual(5);
      expect(y).toBeLessThanOrEqual(45);
    }
    // The highest value sits at the top.
    expect(g.ys[3]).toBe(5);
    expect(g.area.endsWith("L100,50L0,50Z")).toBe(true);
  });

  it("maps kept points back to the original indices", () => {
    const g = chartGeometry([NaN, 2, 3, NaN, 4], 100, 50)!;
    expect(g.index).toEqual([1, 2, 4]);
  });

  it("widens the range to include a baseline", () => {
    const g = chartGeometry([10, 11], 100, 50, 0, 100, [5])!;
    expect(g.min).toBe(5);
    expect(g.yOf(5)).toBe(50);
  });

  it("draws a flat series in the middle instead of dividing by zero", () => {
    const g = chartGeometry([7, 7, 7], 100, 50, 0)!;
    for (const y of g.ys) expect(Number.isFinite(y)).toBe(true);
  });

  it("never overshoots between points (monotone)", () => {
    const p = smoothPath([0, 1, 2, 3], [0, 10, 10, 0]);
    const nums = [...p.matchAll(/,(-?[\d.]+)/g)].map((m) => Number(m[1]));
    expect(Math.max(...nums)).toBeLessThanOrEqual(10);
    expect(Math.min(...nums)).toBeGreaterThanOrEqual(0);
  });

  it("finds the nearest point to a pointer position", () => {
    expect(nearestIndex([0, 50, 100], 100, 0.4)).toBe(1);
    expect(nearestIndex([0, 50, 100], 100, 2)).toBe(2);
    expect(nearestIndex([], 100, 0.5)).toBe(-1);
  });
});
