import { describe, expect, it } from "vitest";
import { boardCounts, categoryLabel, changeTone, eur, frac, itemLinks, leanWords, prediction, signalInfo, visibleItems, type Cs2Board, type Cs2Item } from "./cs2";

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
    expect(changeTone(0.02)).toBe("up");
    expect(changeTone(-0.02)).toBe("down");
    expect(changeTone(0.001)).toBe("flat");
    expect(changeTone(null)).toBe("flat");
  });

  it("names every signal and survives an unknown one", () => {
    expect(signalInfo("buy").tone).toBe("good");
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

describe("page helpers", () => {
  it("shows the 30-day forecast when there is one, else the 7-day", () => {
    expect(prediction(item({ horizon: 30, pred30d: 0.04, pred7d: 0.01 }))).toEqual({ value: 0.04, horizon: 30 });
    expect(prediction(item({ horizon: 7, pred7d: -0.02 }))).toEqual({ value: -0.02, horizon: 7 });
    expect(prediction(item({}))).toEqual({ value: null, horizon: null });
  });

  it("names categories in plain words", () => {
    expect(categoryLabel("knife_glove")).toBe("Knife or glove");
    expect(categoryLabel("case")).toBe("Case");
    expect(categoryLabel("")).toBe("Other");
  });

  it("counts buy ideas, things to look at and items to avoid", () => {
    const b = { items: [item({ signal: "buy" }), item({ signal: "gap" }), item({ signal: "drop" }), item({ signal: "avoid" }), item({})] } as Cs2Board;
    expect(boardCounts(b)).toEqual({ buy: 1, lookAt: 2, avoid: 1 });
  });

  it("writes a loss in euro with a real minus", () => {
    expect(eur(-3.5)).toBe("−3,50 €");
    expect(eur(-0.001)).toBe("0,00 €");
  });
});

describe("itemLinks", () => {
  it("keeps the lab's links on Steam and Skinport", () => {
    const l = itemLinks({ name: "AK-47 | Redline (Field-Tested)", steam_url: "https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20%28Field-Tested%29", skinport_url: "https://skinport.com/item/ak-47-redline-field-tested" });
    expect(l.map((x) => x.label)).toEqual(["Steam market", "Skinport"]);
    expect(l[1].url).toBe("https://skinport.com/item/ak-47-redline-field-tested");
  });
  it("builds them from the name, encoded, when the lab's are missing or foreign", () => {
    const l = itemLinks({ name: "StatTrak™ Zeus x27 | Tosai (Well-Worn)", steam_url: "javascript:alert(1)", skinport_url: "https://evil.example/item" });
    expect(l[0].url).toBe("https://steamcommunity.com/market/listings/730/StatTrak%E2%84%A2%20Zeus%20x27%20%7C%20Tosai%20(Well-Worn)");
    expect(l[1].url).toBe("https://skinport.com/item/stattrak-zeus-x27-tosai-well-worn");
    expect(itemLinks({ name: "★ Karambit | Doppler (Factory New)" })[1].url).toBe("https://skinport.com/item/karambit-doppler-factory-new");
  });
  it("says which way the market leans", () => {
    expect(leanWords("momentum")).toContain("kept rising");
    expect(leanWords("reversion")).toContain("fell back");
    expect(leanWords(undefined)).toBe("not enough data");
  });
});
