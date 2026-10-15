// The CS2 skins board, read-only (pythia-core labview::Cs2Board, written
// hourly by lab.cs2.run to reports/cs2/latest.json next to its lab feed
// header). Prices, predictions and a play-money portfolio; nothing in Pythia
// buys or sells skins.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";
import type { ChangeTone, ChipTone } from "./design";

export type Cs2Signal = "buy" | "hold" | "avoid" | "gap" | "drop";

export interface Cs2Item {
  name: string;
  category: string;
  price: number | null;
  ask: number | null;
  steamPrice: number | null;
  /** Fractions: 0.05 is +5 %. */
  change7d: number | null;
  pred7d: number | null;
  pred30d: number | null;
  expectedNet: number | null;
  horizon: number | null;
  gap: number | null;
  sales7d: number;
  listed: number;
  held: boolean;
  watch: boolean;
  signal: Cs2Signal | string;
}

export interface Cs2Position {
  name: string;
  qty: number;
  cost: number;
  bought: string;
  price: number | null;
  returnPct: number | null;
}

export interface Cs2Portfolio {
  equity: number;
  startEquity: number;
  cash: number;
  returnPct: number;
  started: string | null;
  lastRebalance: string | null;
  positions: Cs2Position[];
  lastTrades: Record<string, unknown>[];
  dates: string[];
  equityCurve: number[];
}

/** The daily research summary (lab/experiments/cs2.py `summary`). Every field may be missing. */
export interface Cs2Research {
  date?: string;
  verdict?: string;
  historyDays?: number;
  firstDay?: string;
  spread?: { status?: string; itemsToday?: number | null; steamPremiumMedian?: number | null; toSteamMedian?: number | null; toSkinportMedian?: number | null };
  momentumIc?: number | null;
  momentumIcLiquid?: number | null;
  bootstrapIc7?: number | null;
  bootstrapIc30?: number | null;
  bootstrapItems?: number | null;
  caseAgeIc?: number | null;
  walkForward7?: string;
  walkForward30?: string;
}

export interface Cs2Board {
  generated: string;
  generatedMs: number;
  /** "ok" with rows, "no data" before the first collection. */
  status: string;
  /** The lab feed's status: ok, watch or bad (empty on boards from before the feed header). */
  feedStatus: string;
  headline: string;
  verdict: string;
  currency: string;
  historyDays: number;
  change7Basis: string;
  hurdle: number | null;
  model: { src7: string; src30: string; note: string };
  portfolio: Cs2Portfolio | null;
  alerts: { tsMs: number | null; kind: string; name: string; text: string }[];
  research: Cs2Research | null;
  items: Cs2Item[];
}

export async function cs2Board(): Promise<Cs2Board | null> {
  switch (liveMode()) {
    case "native":
      return invoke<Cs2Board | null>("cs2_board");
    case "server": {
      const r = await fetch(`${serverUrl()}/api/cs2`);
      if (!r.ok) throw new Error(`backend answered ${r.status}`);
      return (await r.json()) as Cs2Board | null;
    }
    default:
      throw new Error("The CS2 board needs the desktop app or a connected backend.");
  }
}

export const SIGNAL: Record<string, { label: string; tone: ChipTone; help: string }> = {
  buy: { label: "Buy idea", tone: "good", help: "The model expects at least 3 % more than the fees over its horizon. Paper only." },
  hold: { label: "Hold", tone: "neutral", help: "Nothing clears the fees either way." },
  avoid: { label: "Avoid", tone: "bad", help: "The model expects a drop of 5 % or more over 7 days." },
  gap: { label: "Gap", tone: "accent", help: "Skinport and Steam differ by more than both venues' fees. Check it by hand." },
  drop: { label: "Drop", tone: "warn", help: "A liquid item fell well below its 30-day median." },
};

export function signalInfo(s: string) {
  return SIGNAL[s] ?? { label: s || "n/a", tone: "neutral" as ChipTone, help: "" };
}

const MINUS = "−";

/** Euro with two decimals, "n/a" when missing. */
export function eur(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const s = Math.abs(v).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${v < 0 && Number(Math.abs(v).toFixed(2)) !== 0 ? MINUS : ""}${s} €`;
}

/** A fraction as a signed percent: 0.052 -> "+5.2 %". */
export function frac(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const s = Math.abs(v * 100).toFixed(digits);
  return `${v < 0 ? MINUS : "+"}${s} %`;
}

/** Up, down or flat for a fraction, quiet within half a percent. */
export function changeTone(v: number | null | undefined): ChangeTone {
  if (v == null || !Number.isFinite(v) || Math.abs(v) < 0.005) return "flat";
  return v > 0 ? "up" : "down";
}

/** The prediction a row shows: 30 days when there is one, else 7. */
export function prediction(r: Cs2Item): { value: number | null; horizon: number | null } {
  if (r.horizon === 30 && r.pred30d != null) return { value: r.pred30d, horizon: 30 };
  if (r.pred7d != null) return { value: r.pred7d, horizon: 7 };
  return { value: null, horizon: null };
}

/** "case" -> "Case", "knife_glove" -> "Knife or glove". */
export function categoryLabel(c: string): string {
  const named: Record<string, string> = { knife_glove: "Knife or glove", music_kit: "Music kit", other: "Other" };
  return named[c] ?? (c ? c.charAt(0).toUpperCase() + c.slice(1).replace(/_/g, " ") : "Other");
}

/** The counts the top of the page shows. */
export function boardCounts(b: Cs2Board): { buy: number; lookAt: number; avoid: number } {
  let buy = 0;
  let lookAt = 0;
  let avoid = 0;
  for (const r of b.items) {
    if (r.signal === "buy") buy += 1;
    else if (r.signal === "gap" || r.signal === "drop") lookAt += 1;
    else if (r.signal === "avoid") avoid += 1;
  }
  return { buy, lookAt, avoid };
}

export type Cs2Filter = "all" | "signals" | "held" | "watch" | "case" | "skin" | "sticker";
export type Cs2Sort = "liquid" | "change" | "prediction" | "price";

/** The rows to show: filtered by the chips and a search text, then sorted. */
export function visibleItems(items: Cs2Item[], filter: Cs2Filter, query: string, sort: Cs2Sort): Cs2Item[] {
  const q = query.trim().toLowerCase();
  const rows = items.filter((r) => {
    if (q && !r.name.toLowerCase().includes(q)) return false;
    switch (filter) {
      case "signals":
        return r.signal !== "hold";
      case "held":
        return r.held;
      case "watch":
        return r.watch;
      case "case":
      case "skin":
      case "sticker":
        return r.category === filter;
      default:
        return true;
    }
  });
  const key = (r: Cs2Item): number => {
    switch (sort) {
      case "change":
        return r.change7d ?? -Infinity;
      case "prediction":
        return r.expectedNet ?? -Infinity;
      case "price":
        return r.price ?? -Infinity;
      default:
        return r.sales7d;
    }
  };
  return [...rows].sort((a, b) => key(b) - key(a));
}
