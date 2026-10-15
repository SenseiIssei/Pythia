import { describe, expect, it } from "vitest";
import { filterCards, headlineChange, money, pct, predLabel, sortCards, type PokemonCard } from "./pokemon";

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
  it("formats money and percentages", () => {
    expect(money(1234.5)).toBe("$1,234.50");
    expect(money(null)).toBe("n/a");
    expect(pct(-3.21)).toBe("−3.2 %");
    expect(pct(0)).toBe("+0.0 %");
  });
});
