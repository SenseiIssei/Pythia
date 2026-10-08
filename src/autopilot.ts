// The arithmetic behind the Autopilot page: the floor a set of stop rules
// produces, and the plain-language analysis of a run. Pure functions, so the
// numbers the owner reads are tested, not eyeballed.
//
// Units: every `...Pct` in the autopilot contract is a percent (12.5 means
// 12.5 %), like `RiskStatus.drawdownPct`. Sleeve weights are fractions that
// add up to 1.

import type { AutopilotConfig, AutopilotStatus, Market, PnlBreakdown } from "./types";

export const DAY_MS = 86_400_000;

/**
 * How much evidence a run needs before its result says more than luck. The
 * same bar a strategy has to clear before it may touch real money: 30 trading
 * days and 30 trades on live prices (PROFIT-PLAN, gate 7).
 */
export const MEANINGFUL_DAYS = 30;
export const MEANINGFUL_TRADES = 30;

/** The phrase a live start has to be confirmed with. Travels as `confirm`. */
export const LIVE_PHRASE = "START LIVE";

export type Stop = AutopilotConfig["stop"];

/** Positive, finite, or nothing: an empty or zero field means "no limit". */
export function limit(n: number | null | undefined): number | undefined {
  return n != null && Number.isFinite(n) && n > 0 ? n : undefined;
}

export interface FloorPlan {
  /** The lowest equity it can reach before a stop rule ends the run; null when no rule sets one. */
  floor: number | null;
  /** Which rule sets it. */
  by: "lossPct" | "lossUsd" | "trailing" | null;
  /** Equity at which take-profit fires, if set. */
  takeProfitAt: number | null;
}

/**
 * The floor at the start, before it has gained anything. The highest of the
 * loss rules wins, because whichever is hit first stops it. A trailing limit
 * starts from the start capital (the best point so far) and only ever rises.
 */
export function floorAtStart(capital: number, stop: Stop): FloorPlan {
  const candidates: { v: number; by: FloorPlan["by"] }[] = [];
  const lossPct = limit(stop.maxLossPct);
  const lossUsd = limit(stop.maxLossUsd);
  const trail = limit(stop.trailingPct);
  if (lossPct !== undefined) candidates.push({ v: capital * (1 - Math.min(lossPct, 100) / 100), by: "lossPct" });
  if (lossUsd !== undefined) candidates.push({ v: capital - lossUsd, by: "lossUsd" });
  if (trail !== undefined) candidates.push({ v: capital * (1 - Math.min(trail, 100) / 100), by: "trailing" });
  const tp = limit(stop.takeProfitPct);
  const takeProfitAt = tp !== undefined ? capital * (1 + tp / 100) : null;
  if (candidates.length === 0) return { floor: null, by: null, takeProfitAt };
  const best = candidates.reduce((a, b) => (b.v > a.v ? b : a));
  return { floor: Math.max(0, best.v), by: best.by, takeProfitAt };
}

/** Equity points of a run, always ending at its current equity. */
export function curve(s: AutopilotStatus, now: number): [number, number][] {
  const pts = s.history.filter(([t, v]) => Number.isFinite(t) && Number.isFinite(v));
  const end = s.stoppedMs ?? now;
  if (pts.length === 0) return [[s.startedMs, s.startCapital], [Math.max(end, s.startedMs + 1), s.equity]];
  const last = pts[pts.length - 1];
  if (last[1] !== s.equity && end > last[0]) return [...pts, [end, s.equity]];
  return pts;
}

export interface Dip {
  /** Fall from the high, as a percent of the high. */
  pct: number;
  usd: number;
  peakMs: number;
  troughMs: number;
}

/** The deepest fall from a high point to a later low. Null when it never fell. */
export function worstDip(points: [number, number][]): Dip | null {
  let peak = points[0];
  let worst: Dip | null = null;
  for (const p of points) {
    if (p[1] > peak[1]) peak = p;
    const usd = peak[1] - p[1];
    if (usd > 0 && peak[1] > 0 && (!worst || usd / peak[1] > worst.pct / 100)) {
      worst = { pct: (usd / peak[1]) * 100, usd, peakMs: peak[0], troughMs: p[0] };
    }
  }
  return worst;
}

/** Gross, costs and net in the shape the rest of the app already explains. */
export function breakdown(s: AutopilotStatus): PnlBreakdown {
  const costs = Math.max(0, s.fees);
  const gross = s.pnl + costs;
  const costShare = gross > 0 ? costs / gross : undefined;
  return {
    gross,
    costs,
    net: s.pnl,
    costShare,
    costHeavy: costShare !== undefined ? costShare > 0.4 : costs > 0,
  };
}

export interface Maturity {
  days: number;
  trades: number;
  enough: boolean;
  daysLeft: number;
  tradesLeft: number;
}

export function maturity(days: number, trades: number): Maturity {
  const daysLeft = Math.max(0, Math.ceil(MEANINGFUL_DAYS - days));
  const tradesLeft = Math.max(0, MEANINGFUL_TRADES - trades);
  return { days, trades, enough: daysLeft === 0 && tradesLeft === 0, daysLeft, tradesLeft };
}

export interface HoldComparison {
  /** The window both series cover. */
  fromMs: number;
  toMs: number;
  /** Bitcoin's change over that window, percent. */
  holdPct: number;
  /** The autopilot's change over the same window, percent. */
  runPct: number;
  /** The window is shorter than the run: the price history does not reach back to its start. */
  partial: boolean;
}

/** The latest value at or before `t`, or the first one after it when there is none before. */
function valueAt(points: [number, number][], t: number): number {
  let v = points[0][1];
  for (const [pt, pv] of points) {
    if (pt > t) break;
    v = pv;
  }
  return v;
}

/**
 * What simply holding Bitcoin would have done over the same period, from bar
 * times and closes. Needs timestamps: a price series without them cannot be
 * lined up against the run, so it returns null rather than guess.
 */
export function compareWithHold(
  run: [number, number][],
  times: number[] | undefined,
  closes: number[] | undefined,
  startMs: number,
  endMs: number,
): HoldComparison | null {
  if (!times || !closes || run.length === 0) return null;
  const n = Math.min(times.length, closes.length);
  if (n < 2) return null;
  const prices: [number, number][] = [];
  for (let i = 0; i < n; i++) if (Number.isFinite(times[i]) && closes[i] > 0) prices.push([times[i], closes[i]]);
  if (prices.length < 2) return null;
  const fromMs = Math.max(startMs, prices[0][0]);
  const toMs = Math.min(endMs, prices[prices.length - 1][0]);
  if (toMs <= fromMs) return null;
  const p0 = valueAt(prices, fromMs);
  const p1 = valueAt(prices, toMs);
  const e0 = valueAt(run, fromMs);
  const e1 = valueAt(run, toMs);
  if (!(p0 > 0) || !(e0 > 0)) return null;
  // One bar of slack: candles are stamped at their open, a run at any moment.
  const bar = prices.length > 1 ? (prices[prices.length - 1][0] - prices[0][0]) / (prices.length - 1) : 0;
  const partial = fromMs - startMs > bar * 1.5 || endMs - toMs > bar * 1.5;
  return { fromMs, toMs, holdPct: (p1 / p0 - 1) * 100, runPct: (e1 / e0 - 1) * 100, partial };
}

/** The Bitcoin market to compare against: one with bar times if any has them. */
export function bitcoinMarket(markets: Market[], historyTimes: Record<string, number[]>): Market | undefined {
  const btc = markets.filter((m) => m.kind === "crypto" && /^BTC\b/i.test(m.symbol));
  return btc.find((m) => (historyTimes[m.id]?.length ?? 0) > 1) ?? btc[0];
}

export interface Analysis {
  startMs: number;
  endMs: number;
  days: number;
  points: [number, number][];
  tradesPerDay: number | null;
  pnl: PnlBreakdown;
  dip: Dip | null;
  sleeves: AutopilotStatus["bySleeve"];
  maturity: Maturity;
}

export function analyse(s: AutopilotStatus, now: number): Analysis {
  const endMs = s.stoppedMs ?? now;
  const days = Math.max(0, (endMs - s.startedMs) / DAY_MS);
  const points = curve(s, now);
  return {
    startMs: s.startedMs,
    endMs,
    days,
    points,
    // Under an hour the rate is meaningless and would read as hundreds a day.
    tradesPerDay: days >= 1 / 24 ? s.trades / Math.max(days, 1) : null,
    pnl: breakdown(s),
    dip: worstDip(points),
    sleeves: [...s.bySleeve].sort((a, b) => b.pnl - a.pnl),
    maturity: maturity(days, s.trades),
  };
}

export function isActive(s: AutopilotStatus): boolean {
  return s.state === "running" || s.state === "paused";
}

/** "12 days", "5 h 20 min", "3 min". */
export function fmtDuration(ms: number): string {
  const min = Math.max(0, Math.round(ms / 60_000));
  if (min < 1) return "under a minute";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  if (h < 48) return min % 60 ? `${h} h ${min % 60} min` : `${h} h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d} days ${h % 24} h` : `${d} days`;
}

/** "7 Oct, 14:05". */
export function fmtWhen(ms: number): string {
  return new Date(ms).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** A day count in words: "less than a day", "1 day", "12 days". */
export function fmtDays(days: number): string {
  if (days < 1) return "less than a day";
  const d = Math.floor(days);
  return `${d} day${d === 1 ? "" : "s"}`;
}
