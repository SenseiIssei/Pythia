// What one Autopilot card shows, and what the guided start sheet sends. Pure
// functions over the engine's AutopilotStatus, so the numbers on the card are
// tested rather than eyeballed.

import { curve, floorAtStart, isActive, type Stop } from "../autopilot";
import { benchLabel, benchmark, holdings, type Holding } from "../practice";
import type { AutopilotConfig, AutopilotStart, AutopilotStatus, PositionView, Venue } from "../types";

export type Tone = "up" | "down" | "flat";

export function toneOf(n: number | null | undefined, epsilon = 0.005): Tone {
  if (n == null || !Number.isFinite(n)) return "flat";
  return n > epsilon ? "up" : n < -epsilon ? "down" : "flat";
}

export interface StrategyShare {
  id: string;
  name: string;
  /** 0..100, rounded so the shown shares add up to 100. */
  pct: number;
  pnl: number;
}

export interface StatusWords {
  /** One or two words: "Running", "Paused", "Stopped", "Finished". */
  label: string;
  /** One plain sentence on what it is doing. */
  line: string;
  tone: "good" | "warn" | "neutral" | "bad";
}

export interface CardModel {
  id: string;
  name: string;
  mode: AutopilotConfig["mode"];
  active: boolean;
  /** What it is worth now. */
  value: number;
  /** What it started with. */
  amount: number;
  pnl: number;
  pnlPct: number;
  tone: Tone;
  /** Percentage points ahead of holding its benchmark (Bitcoin, or SPY for
   *  US shares); null when unknown. */
  vsBtcPts: number | null;
  btcPct: number | null;
  /** "Bitcoin" or "SPY". */
  benchLabel: string;
  /** Equity values for the small chart, oldest first. */
  chart: number[];
  holdings: Holding[];
  strategies: StrategyShare[];
  status: StatusWords;
}

/**
 * Shares in whole percent that add up to exactly 100 (largest remainder), so
 * "60% · 40%" never reads as "59% · 40%".
 */
export function roundShares(weights: number[]): number[] {
  const total = weights.reduce((a, w) => a + (w > 0 ? w : 0), 0);
  if (!(total > 0)) return weights.map(() => 0);
  const raw = weights.map((w) => ((w > 0 ? w : 0) / total) * 100);
  const floor = raw.map(Math.floor);
  let left = 100 - floor.reduce((a, b) => a + b, 0);
  const order = raw.map((r, i) => ({ i, rem: r - Math.floor(r) })).sort((a, b) => b.rem - a.rem);
  for (const { i } of order) {
    if (left <= 0) break;
    floor[i] += 1;
    left -= 1;
  }
  return floor;
}

/** The strategies it runs with their share, biggest first. Dropped ones are left out. */
export function strategyShares(s: AutopilotStatus, names: Record<string, string> = {}): StrategyShare[] {
  const live = s.bySleeve.filter((b) => !b.dropped);
  if (live.length > 0) {
    const pcts = roundShares(live.map((b) => b.weight));
    return live
      .map((b, i) => ({ id: b.strategyId, name: b.name || names[b.strategyId] || b.strategyId, pct: pcts[i], pnl: b.pnl }))
      .sort((a, b) => b.pct - a.pct);
  }
  const pcts = roundShares(s.config.sleeves.map((c) => c.weight));
  return s.config.sleeves
    .map((c, i) => ({ id: c.strategyId, name: names[c.strategyId] || c.strategyId, pct: pcts[i], pnl: 0 }))
    .sort((a, b) => b.pct - a.pct);
}

/** Its state in plain words. */
export function statusWords(s: AutopilotStatus, holdingCount: number): StatusWords {
  switch (s.state) {
    case "running":
      if (holdingCount > 0) return { label: "Running", line: `Running. Holds ${holdingCount} ${holdingCount === 1 ? "asset" : "assets"}.`, tone: "good" };
      return { label: "Running", line: s.waiting ? `Running, in cash: ${trimDot(s.waiting)}.` : "Running, in cash and waiting for a signal.", tone: "good" };
    case "paused":
      return { label: "Paused", line: s.pausedReason ? `Paused: ${trimDot(s.pausedReason)}. Buys nothing new.` : "Paused. Buys nothing new.", tone: "warn" };
    case "finished":
      return { label: "Finished", line: s.stopReason ? `Finished: ${trimDot(s.stopReason)}.` : "Finished.", tone: "neutral" };
    default:
      return { label: "Stopped", line: s.stopReason ? `Stopped: ${trimDot(s.stopReason)}.` : "Stopped.", tone: "neutral" };
  }
}

function trimDot(t: string): string {
  return t.trim().replace(/[.\s]+$/, "");
}

export interface BtcSeries {
  times?: number[];
  closes?: number[];
}

/** Everything one card shows. */
export function cardModel(
  s: AutopilotStatus,
  positions: PositionView[],
  now: number,
  btc: BtcSeries | null = null,
  names: Record<string, string> = {},
): CardModel {
  const held = holdings(s, positions);
  const bench = benchmark(s, now, btc?.times, btc?.closes);
  return {
    id: s.config.id,
    name: s.config.name,
    mode: s.config.mode,
    active: isActive(s),
    value: s.equity,
    amount: s.startCapital,
    pnl: s.pnl,
    pnlPct: s.pnlPct,
    tone: toneOf(s.pnl),
    vsBtcPts: bench ? bench.edgePct : null,
    btcPct: bench ? bench.btcPct : null,
    benchLabel: bench?.label ?? benchLabel(s.benchmark?.symbol),
    chart: curve(s, now).map((p) => p[1]),
    holdings: held,
    strategies: strategyShares(s, names),
    status: statusWords(s, held.length),
  };
}

/** "Ahead of Bitcoin by 1.2 pts", "Behind Bitcoin by 3.0 pts", "Level with Bitcoin". */
export function vsBtcText(pts: number | null, label = "Bitcoin"): string {
  if (pts == null || !Number.isFinite(pts)) return `No ${label} comparison yet`;
  const t = toneOf(pts, 0.05);
  if (t === "flat") return `Level with ${label}`;
  return `${t === "up" ? "Ahead of" : "Behind"} ${label} by ${Math.abs(pts).toFixed(1)} pts`;
}

/** Totals over the active autopilots, for the header of the page. */
export function totals(list: AutopilotStatus[]): { value: number; amount: number; pnl: number; pnlPct: number; count: number } {
  const act = list.filter(isActive);
  const value = act.reduce((a, s) => a + s.equity, 0);
  const amount = act.reduce((a, s) => a + s.startCapital, 0);
  const pnl = value - amount;
  return { value, amount, pnl, pnlPct: amount > 0 ? (pnl / amount) * 100 : 0, count: act.length };
}

// ── the guided start ───────────────────────────────────────────────────────

export type Care = "low" | "medium" | "high";

export interface CareChoice {
  id: Care;
  label: string;
  /** What it means, in one short line. */
  detail: string;
  stop: Stop;
}

/**
 * "How careful" mapped onto the engine's stop rules. More careful means a
 * smaller loss it may take before it stops itself, and a tighter trailing
 * limit that protects gains.
 */
export const CARE: Record<Care, CareChoice> = {
  low: {
    id: "low",
    label: "Low",
    detail: "Stops after a 30% loss. Room for big swings.",
    stop: { maxLossPct: 30, trailingPct: null, onTakeProfit: "stop" },
  },
  medium: {
    id: "medium",
    label: "Medium",
    detail: "Stops after a 15% loss, or a 20% fall from its best.",
    stop: { maxLossPct: 15, trailingPct: 20, onTakeProfit: "stop" },
  },
  high: {
    id: "high",
    label: "High",
    detail: "Stops after a 7% loss, or a 10% fall from its best.",
    stop: { maxLossPct: 7, trailingPct: 10, onTakeProfit: "stop" },
  },
};

/** Which care level a set of stop rules matches, if any. */
export function careOf(stop: Stop): Care | null {
  for (const c of Object.values(CARE)) {
    if ((stop.maxLossPct ?? null) === (c.stop.maxLossPct ?? null) && (stop.trailingPct ?? null) === (c.stop.trailingPct ?? null) && !stop.maxLossUsd) {
      return c.id;
    }
  }
  return null;
}

/** paper: Pythia's simulator. demo: the exchange's demo account. Never live here. */
export type PracticeAccount = "paper" | "demo";

export interface StartAnswers {
  amount: string;
  care: Care;
  account: PracticeAccount;
  /** The markets it trades. */
  assetClass: Venue;
}

/** Parse a typed amount: "$1,000" is 1000. NaN when it is not a number. */
export function parseAmount(s: string): number {
  const t = s.replace(/[$,\s]/g, "");
  if (t === "") return NaN;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

export const MIN_AMOUNT = 10;
export const MAX_AMOUNT = 1_000_000;

/** What is wrong with a step's answer, or null when it is fine. */
export function amountProblem(s: string): string | null {
  const n = parseAmount(s);
  if (!Number.isFinite(n)) return "Enter an amount in dollars.";
  if (n < MIN_AMOUNT) return `At least $${MIN_AMOUNT}.`;
  if (n > MAX_AMOUNT) return "At most $1,000,000.";
  return null;
}

/** The lowest it can fall to before it stops itself, for the summary line. */
export function floorFor(amount: number, care: Care): number | null {
  return floorAtStart(amount, CARE[care].stop).floor;
}

/**
 * The config the guided sheet starts. Pythia picks the strategies ("auto",
 * re-picked daily). Practice only: the sheet cannot start real money.
 */
export function startConfig(
  a: StartAnswers,
  venue: AutopilotConfig["venue"],
  now: number,
): AutopilotStart {
  const amount = parseAmount(a.amount);
  return {
    id: `ap-${now.toString(36)}`,
    name: `Autopilot ${new Date(now).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`,
    mode: a.account,
    venue,
    assetClass: a.assetClass,
    capitalUsd: amount,
    sleeves: [],
    repickEveryHours: 24,
    stop: { ...CARE[a.care].stop },
    flattenOnStop: true,
  };
}

/**
 * Why the demo account cannot be used for these markets, or null. The
 * engine checks again; this only saves a refused start.
 */
export function demoProblem(live: { demoVenues?: Venue[]; demoExchange?: string | null; demoRealPrices?: boolean | null }, assetClass: Venue): string | null {
  if (assetClass === "crypto" && (live.demoVenues ?? []).includes("crypto") && !!live.demoExchange && live.demoRealPrices === false) {
    return "This exchange's demo account uses its own prices. Use practice money instead.";
  }
  return null;
}
