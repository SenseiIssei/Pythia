import { describe, expect, it } from "vitest";
import { CARDMARKET_SEARCH, TCGPLAYER_SEARCH, cardLinks, cardmarketAgeDays, cardmarketStale, filterCards, headlineChange, money, pct, predLabel, priceHistory, releaseWords, rowFigure, safeLink, searchName, sortCards, type PokemonCard } from "./pokemon";

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

describe("cardLinks", () => {
  it("uses the card's own pages when the lab has them", () => {
    const l = cardLinks(card({ cardmarketUrl: "https://prices.pokemontcg.io/cardmarket/base1-58", cardmarketLink: "product", tcgplayerUrl: "https://prices.pokemontcg.io/tcgplayer/base1-58", tcgplayerLink: "product" }));
    expect(l.map((x) => x.label)).toEqual(["Cardmarket", "TCGplayer"]);
    expect(l[0].url).toBe("https://prices.pokemontcg.io/cardmarket/base1-58");
    expect(l.every((x) => !x.search)).toBe(true);
  });
  it("falls back to an encoded search for the exact name", () => {
    const l = cardLinks(card({ name: "Pikachu & Zekrom-GX #1?x=<y>" }));
    expect(l[0]).toEqual({ label: "Cardmarket search", url: `${CARDMARKET_SEARCH}?searchString=Pikachu%20%26%20Zekrom-GX%20%231%3Fx%3D%3Cy%3E`, search: true });
    expect(l[1].url).toBe(`${TCGPLAYER_SEARCH}?productLineName=pokemon&q=Pikachu%20%26%20Zekrom-GX%20%231%3Fx%3D%3Cy%3E&view=grid`);
  });
  it("never opens a link that is not https", () => {
    const l = cardLinks(card({ cardmarketUrl: "javascript:alert(1)", tcgplayerUrl: "http://example.org/x" }));
    expect(l.map((x) => x.search)).toEqual([true, true]);
    expect(l.every((x) => x.url.startsWith("https://www."))).toBe(true);
  });
  it("labels the lab's own search links as searches and drops a TCGplayer number suffix", () => {
    const l = cardLinks({ name: "Mew ex - 152/128", url: "https://www.tcgplayer.com/product/717605/x", cardmarketUrl: `${CARDMARKET_SEARCH}?searchString=Mew%20ex` });
    expect(l[0].label).toBe("Cardmarket search");
    expect(l[1]).toEqual({ label: "TCGplayer", url: "https://www.tcgplayer.com/product/717605/x", search: false });
    expect(searchName("Mew - R/RGB")).toBe("Mew");
    expect(searchName("Porygon-Z")).toBe("Porygon-Z");
    expect(safeLink("https://user:pw@example.org/")).toBeNull();
  });
  it("counts how old a Cardmarket price is on the snapshot day", () => {
    expect(cardmarketAgeDays("2026-07-01", "2026-10-15")).toBe(106);
    expect(cardmarketAgeDays(null, "2026-10-15")).toBeNull();
  });
});
