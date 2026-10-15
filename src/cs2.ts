// The CS2 skins board, read-only (pythia-core labview::Cs2Board, written
// hourly by lab.cs2.run). Prices, predictions and a play-money portfolio;
// nothing in Pythia buys or sells skins.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";
import type { Tone } from "./components/ui";

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

export interface Cs2Board {
  generated: string;
  generatedMs: number;
  status: string;
  verdict: string;
  currency: string;
  historyDays: number;
  change7Basis: string;
  hurdle: number | null;
  model: { src7: string; src30: string; note: string };
  portfolio: Cs2Portfolio | null;
  alerts: { tsMs: number | null; kind: string; name: string; text: string }[];
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

export const SIGNAL: Record<string, { label: string; tone: Tone; help: string }> = {
  buy: { label: "Buy idea", tone: "green", help: "The model expects more than the fees over its horizon. Paper only." },
  hold: { label: "Hold", tone: "neutral", help: "Nothing clears the fees either way." },
  avoid: { label: "Avoid", tone: "red", help: "The model expects a drop of 5 % or more over 7 days." },
  gap: { label: "Gap", tone: "cyan", help: "Skinport and Steam differ by more than the fees. Check it by hand." },
  drop: { label: "Drop", tone: "amber", help: "A liquid item fell well below its 30-day median." },
};

export function signalInfo(s: string) {
  return SIGNAL[s] ?? { label: s || "n/a", tone: "neutral" as Tone, help: "" };
}

/** Euro with two decimals, "n/a" when missing. */
export function eur(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  return `${v.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
}

/** A fraction as a signed percent: 0.052 -> "+5.2 %". */
export function frac(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const s = Math.abs(v * 100).toFixed(digits);
  return `${v < 0 ? "−" : "+"}${s} %`;
}

export function changeTone(v: number | null | undefined): Tone {
  if (v == null || !Number.isFinite(v) || Math.abs(v) < 0.005) return "neutral";
  return v > 0 ? "green" : "red";
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
