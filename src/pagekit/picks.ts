// The words and key numbers for the Predictions, AI Signals and Strategies
// pages: what a forecast calls in plain language, how strong a model's view
// is, what each strategy kind does, and the one to three numbers on top of
// each page. No React here, so every rule is covered by a test.

import type { ChipTone } from "../design";
import { signedRatio } from "../design/format";
import type { AiView, ForecastStats, GateUnit, LlmDirection, MarketForecast, StrategyConfig, StrategyKind, StrategyState, Track } from "../types";
import { num, share } from "./format";

export type Lean = "up" | "down" | "flat";

// ── Predictions ──────────────────────────────────────────────────────────────

export interface Call {
  /** "Likely yes", "Leans down", "Too close to call". */
  call: string;
  lean: Lean;
  /** The forecast as a whole percent: "62%". */
  chance: string;
  /** What the percent is the chance of: "chance of yes", "chance it rises". */
  of: string;
}

/**
 * A forecast in words. An event market is about yes or no; a price market is
 * about up or down, where 50 % means no idea and is usually the honest answer.
 */
export function forecastCall(f: Pick<MarketForecast, "kind" | "ensembleP">): Call {
  const p = Number.isFinite(f.ensembleP) ? f.ensembleP : 0.5;
  const chance = `${Math.round(p * 100)}%`;
  if (f.kind === "outcome") {
    const of = "chance of yes";
    if (p >= 0.8) return { call: "Very likely yes", lean: "up", chance, of };
    if (p >= 0.6) return { call: "Likely yes", lean: "up", chance, of };
    if (p > 0.52) return { call: "Leans yes", lean: "up", chance, of };
    if (p <= 0.2) return { call: "Very likely no", lean: "down", chance, of };
    if (p <= 0.4) return { call: "Likely no", lean: "down", chance, of };
    if (p < 0.48) return { call: "Leans no", lean: "down", chance, of };
    return { call: "Too close to call", lean: "flat", chance, of };
  }
  const of = "chance it rises";
  if (p > 0.52) return { call: "Leans up", lean: "up", chance, of };
  if (p < 0.48) return { call: "Leans down", lean: "down", chance, of };
  return { call: "No clear direction", lean: "flat", chance, of };
}

/** What it would do about a forecast, as a short label and a chip tone. */
export function actionWord(a: MarketForecast["action"]): { label: string; tone: ChipTone } {
  return a === "buy" ? { label: "Would buy", tone: "good" } : a === "sell" ? { label: "Would sell", tone: "bad" } : { label: "Not acting", tone: "neutral" };
}

/** Biggest net edge first: the only ordering that matters on this page. */
export function sortByEdge<T extends Pick<MarketForecast, "netEdgeBps">>(fs: readonly T[]): T[] {
  return [...fs].sort((a, b) => b.netEdgeBps - a.netEdgeBps);
}

export interface PredictionSummary {
  /** Markets with a forecast. */
  total: number;
  /** Markets where it would buy or sell. */
  acting: number;
  /** Sources that have beaten the market on a checked record. */
  trusted: number;
  /** Distinct sources on the scoreboard; at least `trusted`. */
  sources: number;
  /** Forecasts whose outcome is known. */
  checked: number;
  waiting: number;
  recorded: number;
}

/** The numbers on top of the Predictions page. */
export function predictionSummary(forecasts: readonly Pick<MarketForecast, "action">[], stats: ForecastStats, tracks: readonly Pick<Track, "source">[]): PredictionSummary {
  const sources = new Set(tracks.map((t) => t.source)).size;
  return {
    total: forecasts.length,
    acting: forecasts.filter((f) => f.action !== "hold").length,
    trusted: stats.trustedSources,
    sources: Math.max(sources, stats.trustedSources),
    checked: stats.resolved,
    waiting: stats.pending,
    recorded: stats.recorded,
  };
}

/** Translate the engine's reason string out of trading vocabulary. */
export function plainReason(reason: string): string {
  if (reason.includes("track record")) return "Nothing has proven itself against the market yet, so it will not bet on its own opinion.";
  if (reason.includes("round-trip cost")) return "The difference is smaller than the fees it would pay to trade it.";
  if (reason.includes("below the")) return "The difference is real but too small to be worth trading.";
  if (reason.includes("no forecaster")) return "Nothing has an opinion on this one.";
  return reason;
}

/** Basis points with a sign and the real minus: "+12 bps", "−40 bps". */
export function bps(n: number): string {
  if (!Number.isFinite(n)) return "n/a";
  const r = Math.round(n);
  return `${r > 0 ? "+" : r < 0 ? "−" : ""}${Math.abs(r)} bps`;
}

// ── AI signals ───────────────────────────────────────────────────────────────

/** A model's direction as a word and a lean, so the arrow never stands alone. */
export function directionWord(d: LlmDirection): { word: string; lean: Lean } {
  return d === "long" ? { word: "Up", lean: "up" } : d === "short" ? { word: "Down", lean: "down" } : { word: "No view", lean: "flat" };
}

/** How sure a model said it is, in a word: 70 % and up is strong, under 40 % weak. */
export function strengthWord(confidence: number): string {
  if (!Number.isFinite(confidence)) return "Unknown";
  return confidence >= 0.7 ? "Strong" : confidence >= 0.4 ? "Moderate" : "Weak";
}

export interface ViewRow {
  view: AiView;
  ageSec: number;
  /** Older than the overlay's time to live: ignored by the engine. */
  stale: boolean;
}

/** The newest views first, at most `limit`, each with its age and whether it still counts. */
export function recentViews(views: readonly AiView[], now: number, ttlSec: number, limit = 6): ViewRow[] {
  return [...views]
    .sort((a, b) => b.ts - a.ts)
    .slice(0, limit)
    .map((view) => {
      const ageSec = Math.round((now - view.ts) / 1000);
      return { view, ageSec, stale: ageSec > ttlSec };
    });
}

/** Views that still count, and how many of them lean up or down. */
export function viewCounts(views: readonly AiView[], now: number, ttlSec: number): { fresh: number; up: number; down: number } {
  const fresh = views.filter((v) => Math.round((now - v.ts) / 1000) <= ttlSec);
  return {
    fresh: fresh.length,
    up: fresh.filter((v) => v.direction === "long").length,
    down: fresh.filter((v) => v.direction === "short").length,
  };
}

/** "12 s ago", "4 min ago": how old a view is, in a few characters. */
export function ageText(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  if (s < 90) return `${s} s ago`;
  const m = Math.round(s / 60);
  if (m < 90) return `${m} min ago`;
  return `${Math.round(m / 60)} h ago`;
}

// ── Strategies ───────────────────────────────────────────────────────────────

const BLURB: Record<StrategyKind, string> = {
  "ema-cross": "Buys when the short-term average price crosses above the long-term one, and sells when it crosses back.",
  bollinger: "Buys when the price falls unusually far below its recent range and sells when it snaps back.",
  "rsi-reversal": "Buys after a sharp fall and sells after a sharp rise, betting that the move partly reverses.",
  "macd-trend": "Follows a trend once its momentum confirms it, and steps aside when the momentum fades.",
  breakout: "Buys when the price breaks above its recent high and leaves when the move fails.",
  "multi-tf": "Only trades when the short and the long view of the trend agree.",
  pairs: "Trades two related markets against each other when their usual gap stretches.",
  "prob-edge": "Buys event outcomes it thinks are priced too low and sells those priced too high.",
  composed: "Follows rules you built yourself in the composer.",
  arb: "Looks for prices that do not add up across markets and trades the gap when it beats the costs.",
  manual: "Orders you place by hand.",
  "lab-targets": "Holds the target weights decided in the research lab.",
};

/** What a strategy kind does, in one sentence. */
export function strategyBlurb(kind: string): string {
  return BLURB[kind as StrategyKind] ?? "A rule set that decides on its own when to buy or sell.";
}

/** The state as a label, a chip tone and one sentence on what it means. */
export function stateInfo(state: StrategyState): { label: string; tone: ChipTone; means: string } {
  switch (state) {
    case "live":
      return { label: "Live", tone: "bad", means: "Sends real orders with real money." };
    case "paused":
      return { label: "Paused", tone: "neutral", means: "Switched off. It places no orders." };
    case "demo":
      return { label: "Demo", tone: "accent", means: "Sends orders to the venue's demo account: real API, virtual money." };
    default:
      return { label: "Paper", tone: "neutral", means: "Trades practice money on real prices." };
  }
}

/** The numbers on top of the Strategies page. */
export function strategySummary(list: readonly Pick<StrategyConfig, "pnl" | "state">[]): { pnl: number; running: number; live: number; total: number } {
  return {
    pnl: list.reduce((a, s) => a + (Number.isFinite(s.pnl) ? s.pnl : 0), 0),
    running: list.filter((s) => s.state !== "paused").length,
    live: list.filter((s) => s.state === "live").length,
    total: list.length,
  };
}

/** A gate's number the way it was measured: a signed return, a share, a count or a plain number. */
export function gateValue(v: number | undefined, unit: GateUnit): string {
  if (v === undefined || !Number.isFinite(v)) return "n/a";
  if (unit === "pct") return signedRatio(v, 1);
  if (unit === "share") return share(v);
  if (unit === "count") return Math.round(v).toLocaleString("en-US");
  return num(v, Math.abs(v) < 0.1 ? 3 : 2);
}
