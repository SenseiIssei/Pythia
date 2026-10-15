// The research lab, read-only: paper books and experiment reports
// (pythia-core/src/labview.rs). The desktop app reads the synced data folder,
// the server its own.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";

export interface PaperBook {
  name: string;
  variant: string;
  started: string;
  days: number;
  equity: number[];
  dates: string[];
  returnPct: number;
  lastRebalance: Record<string, string>;
}

export interface LabReport {
  name: string;
  updatedMs: number;
  verdict: string;
}

export interface HealthCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface LabStatus {
  found: boolean;
  dir: string;
  books: PaperBook[];
  reports: LabReport[];
  /** The VPS's hourly look at every lab job. */
  health: { at: string; ok: boolean; checks: HealthCheck[] } | null;
  /** The daily forward report: paper books and autopilots against their backtests. */
  forward?: ForwardReport | null;
  /** The nightly learning loop's digest. */
  learn?: LearnDigest | null;
  /** New coin listings the watcher saw in the last 90 days. */
  listings?: ListingsFeed | null;
}

// ── new listings (pythia-core labview::ListingsFeed) ────────────────────────

export interface Listing {
  tsMs: number;
  venue: string;
  event: string;
  symbol: string;
  base: string;
  quote: string | null;
  newBase: boolean | null;
  alpacaLists: boolean | null;
  price: number | null;
  title: string | null;
}

export interface ListingsFeed {
  generated: string;
  generatedMs: number;
  venues: Record<string, { ok: boolean; count: number; error: string | null }>;
  listings: Listing[];
}

const VENUE_LABEL: Record<string, string> = {
  alpaca: "Alpaca",
  binance: "Binance",
  coinbase: "Coinbase",
  kraken: "Kraken",
  binance_news: "Binance announcement",
};

export interface ListingRow {
  key: string;
  tsMs: number;
  venue: string;
  coin: string;
  symbols: string[];
  /** Alpaca lists it: yes, no, or unknown without Alpaca keys. */
  alpaca: "yes" | "no" | "unknown";
  price: string | null;
  title: string | null;
}

/**
 * One row per coin per venue per watcher run, newest first: a new pair of a
 * coin the venue already had is left out unless the venue is Alpaca.
 */
export function listingRows(feed: ListingsFeed | null | undefined, limit = 20): ListingRow[] {
  const rows = new Map<string, ListingRow>();
  for (const l of feed?.listings ?? []) {
    if (l.event !== "announced" && !(l.newBase || l.venue === "alpaca")) continue;
    const key = `${l.venue}:${l.base || l.symbol}:${l.tsMs}`;
    const r = rows.get(key);
    const price =
      l.price != null && Number.isFinite(l.price) ? `${l.price.toPrecision(4)} ${l.quote ?? ""}`.trim() : null;
    if (r) {
      r.symbols.push(l.symbol);
      r.price ??= price;
      continue;
    }
    rows.set(key, {
      key,
      tsMs: l.tsMs,
      venue: VENUE_LABEL[l.venue] ?? l.venue,
      coin: l.base || l.symbol,
      symbols: [l.symbol],
      alpaca: l.venue === "alpaca" ? "yes" : l.alpacaLists == null ? "unknown" : l.alpacaLists ? "yes" : "no",
      price,
      title: l.title,
    });
  }
  return [...rows.values()].sort((a, b) => b.tsMs - a.tsMs).slice(0, limit);
}

/** Venues the watcher could not read on its last run, in plain words. */
export function listingGaps(feed: ListingsFeed | null | undefined): string[] {
  return Object.entries(feed?.venues ?? {})
    .filter(([, v]) => !v.ok)
    .map(([k, v]) => `${VENUE_LABEL[k] ?? k}: ${v.error ?? "no answer"}`);
}

// ── learning loop digest (pythia-core labview::LearnDigest) ─────────────────

export interface LearnDigest {
  generated: string;
  generatedMs: number;
  headline: string;
  changes: { area: string; what: string; why: string }[];
  decisions: { model: string; candidate: string | null; champion: string | null; decision: string; why: string }[];
  autopilots: {
    id: string;
    name: string;
    state: string | null;
    pnlDayPct: number | null;
    btcDayPct: number | null;
    pnlTotalPct: number | null;
    btcTotalPct: number | null;
    vsBtcTotalPts: number | null;
  }[];
  steps: { step: string; status: string; detail: string }[];
}

// ── forward report (pythia-core labview::ForwardReport) ─────────────────────

export interface ForwardBand {
  medianPct: number;
  lowPct: number;
  highPct: number;
  /** 95 % of the backtest's stretches of this length had a smaller worst dip. */
  ddP95Pct: number | null;
  /** "bootstrap" (the backtest's own days) or "approximate" (growth and volatility only). */
  method: string;
  source: string;
  backtestMaxDdPct: number | null;
}

export interface ForwardGate {
  days: number;
  daysNeeded: number;
  trades: number;
  tradesNeeded: number;
  /** "rebalances" for a paper book, "closed trades" for an autopilot. */
  tradesLabel: string;
  /** 0..1, the slower of the two. */
  progress: number;
  ready: boolean;
}

export interface ForwardCosts {
  paperPct: number;
  modelPct: number;
  ratio: number | null;
  /** The book books the modelled cost as its fill cost. */
  modelledOnly: boolean;
}

export interface ForwardSlippage {
  route: string;
  fills: number;
  medianRealisedBps: number | null;
  medianModelledBps: number | null;
  ratio: number | null;
}

export type ForwardStatus = "none" | "early" | "watch" | "ahead" | "on_track" | "unknown" | "stopped";

export interface ForwardRow {
  kind: "book" | "autopilot" | string;
  name: string;
  label: string;
  variant: string;
  since: string | null;
  days: number;
  elapsedDays: number;
  returnPct: number | null;
  maxDdPct: number | null;
  turnover: number | null;
  costs: ForwardCosts | null;
  fundingPct: number | null;
  expected: ForwardBand | null;
  position: "below" | "inside" | "above" | null;
  gate7: ForwardGate;
  status: ForwardStatus | string;
  sentence: string;
  mode: string | null;
  state: string | null;
  startEquity: number | null;
  equity: number | null;
  floorEquity: number | null;
  btcReturnPct: number | null;
  fees: number | null;
  feesShareOfGross: number | null;
  feesPctOfCapital: number | null;
  tradesPerDay: number | null;
  slippage: ForwardSlippage[];
  labBook: string | null;
}

export interface ForwardReport {
  generated: string;
  generatedMs: number;
  verdict: string;
  books: ForwardRow[];
  autopilots: ForwardRow[];
  engine: { url: string; reachable: boolean; error: string | null } | null;
}

type Tone = "green" | "red" | "amber" | "cyan" | "neutral";

/** Badge text and colour for a forward status, in plain words. */
export function forwardStatus(status: string): { label: string; tone: Tone } {
  switch (status) {
    case "on_track":
      return { label: "on track", tone: "green" };
    case "ahead":
      return { label: "better than expected", tone: "cyan" };
    case "watch":
      return { label: "worth watching", tone: "amber" };
    case "early":
      return { label: "too early to say", tone: "neutral" };
    case "stopped":
      return { label: "stopped", tone: "neutral" };
    case "none":
      return { label: "not started", tone: "neutral" };
    default:
      return { label: "no range to compare", tone: "neutral" };
  }
}

/**
 * Where to draw a return against its expected band on one horizontal track,
 * in percent of the track's width (0..100). The axis spans the band, zero and
 * the actual return with a little room on both sides, so the dot never sits
 * on the edge and zero is always on the track.
 */
export function bandScale(
  actual: number,
  band: { lowPct: number; highPct: number; medianPct: number },
): { low: number; high: number; median: number; actual: number; zero: number } {
  const lo = Math.min(band.lowPct, actual, 0);
  const hi = Math.max(band.highPct, actual, 0);
  const pad = Math.max((hi - lo) * 0.08, 0.05);
  const a = lo - pad;
  const span = hi + pad - a;
  const at = (v: number) => Math.min(100, Math.max(0, ((v - a) / span) * 100));
  return { low: at(band.lowPct), high: at(band.highPct), median: at(band.medianPct), actual: at(actual), zero: at(0) };
}

/** Progress toward gate 7 in percent, the slower of days and trades. */
export function gatePct(g: ForwardGate): number {
  const days = g.daysNeeded > 0 ? g.days / g.daysNeeded : 1;
  const trades = g.tradesNeeded > 0 ? g.trades / g.tradesNeeded : 1;
  return Math.round(Math.min(1, Math.max(0, Math.min(days, trades))) * 100);
}

/** "+1.23 %" with a real minus sign for negatives; "n/a" when unknown. */
export function signedPct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const s = Math.abs(v).toFixed(digits);
  return `${v < 0 ? "−" : "+"}${s} %`;
}

/** Paper fills against the cost model, in one line. */
export function costLine(c: ForwardCosts | null): string | null {
  if (!c) return null;
  if (c.modelledOnly) return `${c.paperPct.toFixed(3)} % of capital (this book books the modelled cost)`;
  const ratio = c.ratio != null ? `, ${c.ratio.toFixed(2)}x` : "";
  return `${c.paperPct.toFixed(3)} % paid vs ${c.modelPct.toFixed(3)} % modelled${ratio}`;
}

export async function labStatus(): Promise<LabStatus> {
  switch (liveMode()) {
    case "native":
      return invoke<LabStatus>("lab_status");
    case "server": {
      const r = await fetch(`${serverUrl()}/api/lab`);
      if (!r.ok) throw new Error(`backend answered ${r.status}`);
      return (await r.json()) as LabStatus;
    }
    default:
      throw new Error("The lab view needs the desktop app or a connected backend.");
  }
}
