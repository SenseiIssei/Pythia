// Pokemon cards from the lab, read-only: prices, changes, forecasts, the
// paper collection (play money). Written daily by lab.pokemon.daily into
// <data>/pokemon/ui/latest.json and served as written (labview.rs). Nothing
// here can buy or sell a card; the owner trades by hand.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";

export interface PokemonCard {
  id: string;
  name: string;
  set: string | null;
  setId: string | null;
  number: string | null;
  rarity: string | null;
  releaseDate: string | null;
  image: string | null;
  imageLarge: string | null;
  priceUsd: number | null;
  /** "tcgplayer" (USD market price) or "cardmarket" (EUR trend at the ECB rate). */
  priceSrc: string | null;
  variant: string | null;
  cardmarketEur: number | null;
  /** When the API last refreshed this card's Cardmarket prices (YYYY-MM-DD). */
  cardmarketUpdated?: string | null;
  /** Updated within two weeks. A stale block is shown for the record only. */
  cardmarketFresh?: boolean;
  spreadPct: number | null;
  tcgplayerUrl: string | null;
  cardmarketUrl: string | null;
  change1dPct: number | null;
  change7dPct: number | null;
  change30dPct: number | null;
  /** "snapshots" (our own history) or "cardmarket" (its trend against its 30-day average). */
  change30dSrc: string;
  pred30dPct: number | null;
  pred90dPct: number | null;
  /** "model" (validated out of sample), "mixed", or "prior" (a fixed rule, not validated). */
  predSrc: string | null;
  fairUsd: number | null;
  fairGapPct: number | null;
  character: string | null;
  altArt: boolean;
  /** [date, price in USD] from our daily snapshots. */
  history: [string, number | null][];
}

export interface PokemonHolding {
  id: string;
  name: string;
  set: string | null;
  image: string | null;
  qty: number;
  buyPrice: number;
  price: number;
  bought: string;
  changePct: number | null;
  why: string;
}

export interface PokemonCollection {
  start: number;
  started: string | null;
  equity: number;
  equityMarket: number;
  cash: number;
  returnPct: number;
  holdings: PokemonHolding[];
  curve: [string, number][];
  trades?: PokemonTrade[];
}

export interface PokemonTrade {
  date: string;
  side: string;
  name: string;
  qty: string | number;
  price: string | number;
  cash: string | number;
  why: string;
}

export interface PokemonModel {
  validated: boolean;
  sentence: string;
  fairValueR2: number | null;
}

export interface PokemonFreshness {
  /** Share of priced cards whose Cardmarket block is under two weeks old, 0..1. */
  cardmarketFreshShare: number | null;
  cardmarketNewest: string | null;
  tcgplayerNewest: string | null;
}

export interface PokemonAlertMove {
  card_id: string;
  name: string;
  set: string | null;
  price: number;
  move: number;
  basis: string;
}

/** A main set the card API does not price yet, from TCGplayer through tcgcsv. */
export interface PokemonNewSet {
  set: string;
  released: string | null;
  /** Negative for a set not out yet (pre-order prices). */
  ageDays: number | null;
  singles: number;
  /** Mean of the 10 dearest singles. */
  top10MeanUsd: number | null;
  boosterBoxUsd: number | null;
  cards: { name: string; number: string | null; rarity: string | null; priceUsd: number | null; image: string | null; url: string | null }[];
}

/** "out 29 days", "out in 22 days", "out today". */
export function releaseWords(ageDays: number | null): string {
  if (ageDays == null || !Number.isFinite(ageDays)) return "";
  if (ageDays === 0) return "out today";
  if (ageDays < 0) return `out in ${-ageDays} day${ageDays === -1 ? "" : "s"}`;
  if (ageDays < 60) return `out ${ageDays} day${ageDays === 1 ? "" : "s"}`;
  return `out ${Math.round(ageDays / 30.4)} months`;
}

export interface PokemonData {
  generated: string;
  snapshot: string;
  historyDays: number;
  verdict: string;
  model: PokemonModel;
  cards: PokemonCard[];
  collection: PokemonCollection;
  freshness?: PokemonFreshness;
  newSets?: PokemonNewSet[];
  alerts?: { moves: PokemonAlertMove[]; undervalued: { card_id: string }[]; sent: boolean };
}

export interface PokemonView {
  found: boolean;
  data: PokemonData | null;
}

export type CardSort = "price" | "change" | "forecast" | "cheap";

/** Sorted copy; unknown values go last. */
export function sortCards(cards: PokemonCard[], by: CardSort): PokemonCard[] {
  const key = (c: PokemonCard): number | null => {
    switch (by) {
      case "price":
        return c.priceUsd;
      case "change":
        return c.change1dPct ?? c.change7dPct ?? c.change30dPct;
      case "forecast":
        return c.pred90dPct;
      case "cheap":
        return c.fairGapPct;
    }
  };
  return [...cards].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    if (x == null || !Number.isFinite(x)) return y == null || !Number.isFinite(y) ? 0 : 1;
    if (y == null || !Number.isFinite(y)) return -1;
    return by === "change" ? Math.abs(y) - Math.abs(x) : y - x;
  });
}

/** Name, set or number contains the query (case-insensitive). */
export function filterCards(cards: PokemonCard[], q: string): PokemonCard[] {
  const s = q.trim().toLowerCase();
  if (!s) return cards;
  return cards.filter((c) => [c.name, c.set, c.number, c.rarity].some((v) => v?.toLowerCase().includes(s)));
}

/** The change worth showing next to the price: the shortest one we have, and its label. */
export function headlineChange(c: PokemonCard): { pct: number | null; label: string } {
  if (c.change1dPct != null) return { pct: c.change1dPct, label: "1 day" };
  if (c.change7dPct != null) return { pct: c.change7dPct, label: "7 days" };
  if (c.change30dPct != null)
    return { pct: c.change30dPct, label: c.change30dSrc === "cardmarket" ? "30 days (Cardmarket)" : "30 days" };
  return { pct: null, label: "" };
}

/**
 * The figure under a row's price, following the sort: the forecast when
 * sorting by forecast, the distance to fair value when sorting by cheapness,
 * else the latest change. Percent units.
 */
export function rowFigure(c: PokemonCard, by: CardSort): { pct: number | null; suffix: string } {
  if (by === "forecast") return { pct: c.pred90dPct, suffix: "in 90 d" };
  if (by === "cheap") return { pct: c.fairGapPct, suffix: "to fair" };
  const h = headlineChange(c);
  return { pct: h.pct, suffix: h.label };
}

/** Most Cardmarket prices are older than two weeks: the EU side is left out. */
export function cardmarketStale(d: Pick<PokemonData, "freshness">): boolean {
  const s = d.freshness?.cardmarketFreshShare;
  return s != null && Number.isFinite(s) && s < 0.5;
}

/** Prices from our own snapshots, oldest first, without gaps. */
export function priceHistory(c: PokemonCard): number[] {
  return c.history.map(([, p]) => p).filter((p): p is number => p != null && Number.isFinite(p));
}

/** Days of our own history a first honest test of the 30-day forecast needs. */
export const DAYS_FOR_A_TEST = 225;

export function predLabel(src: string | null): string {
  switch (src) {
    case "model":
      return "model, validated out of sample";
    case "mixed":
      return "model for some horizons, rule for others";
    default:
      return "rule, not validated yet";
  }
}

export function money(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  return `${v < 0 ? "−" : "+"}${Math.abs(v).toFixed(digits)} %`;
}

export async function pokemonView(): Promise<PokemonView> {
  switch (liveMode()) {
    case "native":
      return invoke<PokemonView>("pokemon_status");
    case "server": {
      const r = await fetch(`${serverUrl()}/api/pokemon`);
      if (!r.ok) throw new Error(`backend answered ${r.status}`);
      return (await r.json()) as PokemonView;
    }
    default:
      throw new Error("The cards need the desktop app or a connected backend.");
  }
}
