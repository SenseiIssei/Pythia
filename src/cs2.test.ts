import { describe, expect, it } from "vitest";
import { changeTone, eur, frac, signalInfo, visibleItems, type Cs2Item } from "./cs2";

const item = (over: Partial<Cs2Item>): Cs2Item => ({
  name: "Recoil Case",
  category: "case",
  price: 1,
  ask: 1.01,
  steamPrice: null,
  change7d: 0,
  pred7d: null,
  pred30d: null,
  expectedNet: null,
  horizon: null,
  gap: null,
  sales7d: 10,
  listed: 100,
  held: false,
  watch: false,
  signal: "hold",
  ...over,
});

describe("formatting", () => {
  it("shows fractions as signed percent and euro with a comma", () => {
    expect(frac(0.052)).toBe("+5.2 %");
    expect(frac(-0.1, 0)).toBe("−10 %");
    expect(frac(null)).toBe("n/a");
    expect(eur(1234.5)).toBe("1.234,50 €");
    expect(eur(undefined)).toBe("n/a");
  });

  it("colours changes, quiet near zero", () => {
    expect(changeTone(0.02)).toBe("green");
    expect(changeTone(-0.02)).toBe("red");
    expect(changeTone(0.001)).toBe("neutral");
    expect(changeTone(null)).toBe("neutral");
  });

  it("names every signal and survives an unknown one", () => {
    expect(signalInfo("buy").tone).toBe("green");
    expect(signalInfo("gap").label).toBe("Gap");
    expect(signalInfo("weird").label).toBe("weird");
  });
});

describe("visibleItems", () => {
  const rows = [
    item({ name: "A Case", sales7d: 5, change7d: 0.1, expectedNet: -0.1 }),
    item({ name: "AK-47 | Redline (Field-Tested)", category: "skin", sales7d: 50, change7d: -0.2, signal: "buy", expectedNet: 0.2, held: true }),
    item({ name: "Sticker | Foo", category: "sticker", sales7d: 20, change7d: null, signal: "drop", watch: true }),
  ];

  it("sorts by liquidity unless asked otherwise, missing values last", () => {
    expect(visibleItems(rows, "all", "", "liquid").map((r) => r.sales7d)).toEqual([50, 20, 5]);
    expect(visibleItems(rows, "all", "", "change").map((r) => r.name)).toEqual(["A Case", "AK-47 | Redline (Field-Tested)", "Sticker | Foo"]);
    expect(visibleItems(rows, "all", "", "prediction")[0].name).toBe("AK-47 | Redline (Field-Tested)");
  });

  it("filters by chip and search", () => {
    expect(visibleItems(rows, "signals", "", "liquid")).toHaveLength(2);
    expect(visibleItems(rows, "held", "", "liquid")).toHaveLength(1);
    expect(visibleItems(rows, "watch", "", "liquid")[0].name).toBe("Sticker | Foo");
    expect(visibleItems(rows, "case", "", "liquid")).toHaveLength(1);
    expect(visibleItems(rows, "all", "redline", "liquid")).toHaveLength(1);
  });
});
