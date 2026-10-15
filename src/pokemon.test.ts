import { describe, expect, it } from "vitest";
import { cardmarketStale, filterCards, headlineChange, money, pct, predLabel, priceHistory, releaseWords, rowFigure, sortCards, type PokemonCard } from "./pokemon";

function card(over: Partial<PokemonCard>): PokemonCard {
  return {
    id: "x", name: "Pikachu", set: "Base", setId: "base1", number: "58", rarity: "Common", releaseDate: "1999-01-09",
    image: null, imageLarge: null, priceUsd: 10, priceSrc: "tcgplayer", variant: "normal", cardmarketEur: 9,
    spreadPct: 1, tcgplayerUrl: null, cardmarketUrl: null, change1dPct: null, change7dPct: null,
    change30dPct: null, change30dSrc: "snapshots", pred30dPct: 0, pred90dPct: 0, predSrc: "prior", fairUsd: 12,
    fairGapPct: 20, character: "pikachu", altArt: false, history: [], ...over,
  };
}

describe("sortCards", () => {
  const a = card({ id: "a", priceUsd: 5, change1dPct: -30, pred90dPct: 10, fairGapPct: null });
  const b = card({ id: "b", priceUsd: 50, change1dPct: 5, pred90dPct: null, fairGapPct: 40 });
  const c = card({ id: "c", priceUsd: null, change1dPct: null, change7dPct: 12, pred90dPct: -5, fairGapPct: -10 });

  it("puts the dearest first and unknown prices last", () => {
    expect(sortCards([a, b, c], "price").map((x) => x.id)).toEqual(["b", "a", "c"]);
  });
  it("ranks moves by size either way, falling back to longer windows", () => {
    expect(sortCards([a, b, c], "change").map((x) => x.id)).toEqual(["a", "c", "b"]);
  });
  it("ranks forecasts and cheapness with unknowns last", () => {
    expect(sortCards([a, b, c], "forecast").map((x) => x.id)).toEqual(["a", "c", "b"]);
    expect(sortCards([a, b, c], "cheap").map((x) => x.id)).toEqual(["b", "c", "a"]);
  });
  it("does not change the input", () => {
    const xs = [a, b, c];
    sortCards(xs, "price");
    expect(xs.map((x) => x.id)).toEqual(["a", "b", "c"]);
  });
});

describe("helpers", () => {
  it("filters on name, set, number and rarity", () => {
    const xs = [card({ id: "1", name: "Charizard ex", set: "151" }), card({ id: "2", rarity: "Illustration Rare" })];
    expect(filterCards(xs, "chari").map((x) => x.id)).toEqual(["1"]);
    expect(filterCards(xs, "illustration").map((x) => x.id)).toEqual(["2"]);
    expect(filterCards(xs, "  ")).toHaveLength(2);
  });
  it("shows the shortest change we have and says when it is Cardmarket's", () => {
    expect(headlineChange(card({ change1dPct: 2, change7dPct: 9 }))).toEqual({ pct: 2, label: "1 day" });
    expect(headlineChange(card({ change30dPct: -4, change30dSrc: "cardmarket" })).label).toBe("30 days (Cardmarket)");
    expect(headlineChange(card({})).pct).toBeNull();
  });
  it("labels the forecast source honestly", () => {
    expect(predLabel("prior")).toMatch(/not validated/);
    expect(predLabel(null)).toMatch(/not validated/);
    expect(predLabel("model")).toMatch(/validated out of sample/);
  });
  it("shows the figure the sort is about under the price", () => {
    const c = card({ change7dPct: 9, pred90dPct: 14, fairGapPct: -20 });
    expect(rowFigure(c, "price")).toEqual({ pct: 9, suffix: "7 days" });
    expect(rowFigure(c, "change")).toEqual({ pct: 9, suffix: "7 days" });
    expect(rowFigure(c, "forecast")).toEqual({ pct: 14, suffix: "in 90 d" });
    expect(rowFigure(c, "cheap")).toEqual({ pct: -20, suffix: "to fair" });
  });
  it("flags stale Cardmarket data only when most of it is old", () => {
    expect(cardmarketStale({ freshness: { cardmarketFreshShare: 0.1, cardmarketNewest: "2026-07-01", tcgplayerNewest: null } })).toBe(true);
    expect(cardmarketStale({ freshness: { cardmarketFreshShare: 0.9, cardmarketNewest: null, tcgplayerNewest: null } })).toBe(false);
    expect(cardmarketStale({})).toBe(false);
  });
  it("keeps only real prices in the history line", () => {
    expect(priceHistory(card({ history: [["2026-10-14", 3], ["2026-10-15", null], ["2026-10-16", 4]] }))).toEqual([3, 4]);
  });
  it("says how long a set has been out, or when it comes", () => {
    expect(releaseWords(29)).toBe("out 29 days");
    expect(releaseWords(1)).toBe("out 1 day");
    expect(releaseWords(146)).toBe("out 5 months");
    expect(releaseWords(-22)).toBe("out in 22 days");
    expect(releaseWords(0)).toBe("out today");
    expect(releaseWords(null)).toBe("");
  });
  it("formats money and percentages", () => {
    expect(money(1234.5)).toBe("$1,234.50");
    expect(money(null)).toBe("n/a");
    expect(pct(-3.21)).toBe("−3.2 %");
    expect(pct(0)).toBe("+0.0 %");
  });
});
