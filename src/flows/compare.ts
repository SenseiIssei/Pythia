// Several autopilots side by side: one row each (return, against its
// benchmark, drawdown, trades, fees) and their equity curves on one chart.
// Every autopilot keeps a book of its own, so their numbers never mix. The
// curves are put on one scale as a return in percent from each one's own
// amount: one axis, never two. Pure functions, tested in compare.test.ts.

import { curve, isActive, worstDip } from "../autopilot";
import { benchmark } from "../practice";
import type { AutopilotStatus } from "../types";

/** The chart draws with the design system's series colours
 *  (`--color-series-1` to `-6`, src/design/tokens.ts), in fixed order. A
 *  seventh autopilot on is in the table only. */
export const MAX_SERIES = 6;

export interface CompareRow {
  id: string;
  name: string;
  mode: AutopilotStatus["config"]["mode"];
  active: boolean;
  /** Its colour slot in the chart (0..5), by when it started, or null when
   *  it is in the table only. */
  slot: number | null;
  amount: number;
  equity: number;
  /** Return on its amount, percent. */
  returnPct: number;
  pnl: number;
  /** What it is held against: "Bitcoin" or "SPY". */
  benchLabel: string;
  benchPct: number | null;
  /** Points ahead of its benchmark (negative: behind); null when unknown. */
  vsBenchPts: number | null;
  /** Below its peak now, percent. */
  drawdownPct: number;
  /** The deepest fall from a peak so far, percent. */
  maxDrawdownPct: number;
  trades: number;
  fees: number;
  /** Fees as a share of its amount, percent. */
  feesPct: number;
  /** Its own cash, when the engine reports it. */
  cash: number | null;
  /** Days it has run (until its stop). */
  days: number;
}

/** Ordered for the chart's colours: the earliest start first, so an
 *  autopilot keeps its colour while others come and go. */
function byStart(list: AutopilotStatus[]): AutopilotStatus[] {
  return [...list].sort((a, b) => a.startedMs - b.startedMs || a.config.id.localeCompare(b.config.id));
}

/** The deepest fall from a peak: the engine's figure, else the history's. */
function maxDrawdown(s: AutopilotStatus, now: number): number {
  if (s.maxDrawdownPct != null && Number.isFinite(s.maxDrawdownPct)) return s.maxDrawdownPct;
  return worstDip(curve(s, now))?.pct ?? 0;
}

/** One row per autopilot, in the order given (the page lists active ones
 *  first); the chart colours follow the start order. */
export function compareRows(list: AutopilotStatus[], now: number): CompareRow[] {
  const slots = new Map(byStart(list).map((s, i) => [s.config.id, i < MAX_SERIES ? i : null]));
  return list.map((s) => {
    const b = benchmark(s, now);
    const end = s.stoppedMs ?? now;
    return {
      id: s.config.id,
      name: s.config.name,
      mode: s.config.mode,
      active: isActive(s),
      slot: slots.get(s.config.id) ?? null,
      amount: s.startCapital,
      equity: s.equity,
      returnPct: s.pnlPct,
      pnl: s.pnl,
      benchLabel: b?.label ?? (s.benchmark?.symbol === "SPY" ? "SPY" : "Bitcoin"),
      benchPct: b ? b.btcPct : null,
      vsBenchPts: b ? b.edgePct : null,
      drawdownPct: s.drawdownPct,
      maxDrawdownPct: maxDrawdown(s, now),
      trades: s.trades,
      fees: s.fees,
      feesPct: s.startCapital > 0 ? (s.fees / s.startCapital) * 100 : 0,
      cash: s.cash != null && Number.isFinite(s.cash) ? s.cash : null,
      days: Math.max(0, (end - s.startedMs) / 86_400_000),
    };
  });
}

export interface CompareSeries {
  id: string;
  name: string;
  slot: number;
  /** [epoch ms, return in percent from its own amount], oldest first. */
  points: [number, number][];
}

/** Each autopilot's equity curve as a return from its own amount, so
 *  different amounts share one axis. Only the first six by start. */
export function combinedSeries(list: AutopilotStatus[], now: number): CompareSeries[] {
  return byStart(list)
    .slice(0, MAX_SERIES)
    .map((s, slot) => {
      const base = s.startCapital > 0 ? s.startCapital : 1;
      return {
        id: s.config.id,
        name: s.config.name,
        slot,
        points: curve(s, now).map(([t, v]) => [t, (v / base - 1) * 100] as [number, number]),
      };
    });
}

export interface ChartFrame {
  t0: number;
  t1: number;
  lo: number;
  hi: number;
  /** Gridline values, percent, including zero. */
  ticks: number[];
}

/** The common frame of the series: time span and a percent range padded to
 *  round ticks, always including zero (where each one started). */
export function chartFrame(series: CompareSeries[]): ChartFrame | null {
  const pts = series.flatMap((s) => s.points);
  if (pts.length < 2) return null;
  let t0 = Math.min(...pts.map((p) => p[0]));
  let t1 = Math.max(...pts.map((p) => p[0]));
  if (t1 <= t0) t1 = t0 + 60_000;
  let lo = Math.min(0, ...pts.map((p) => p[1]));
  let hi = Math.max(0, ...pts.map((p) => p[1]));
  if (hi - lo < 0.5) {
    hi += 0.25;
    lo -= 0.25;
  }
  const step = niceStep((hi - lo) / 4);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v / step) * step);
  t0 = Math.min(t0, t1 - 1);
  return { t0, t1, lo, hi, ticks };
}

/** 1, 2 or 5 times a power of ten, at least `raw`. */
export function niceStep(raw: number): number {
  if (!(raw > 0) || !Number.isFinite(raw)) return 1;
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

/** The value of a series at time `t`: the last point at or before it, or
 *  null before its first point. */
export function valueAt(points: [number, number][], t: number): number | null {
  let v: number | null = null;
  for (const [pt, pv] of points) {
    if (pt > t) break;
    v = pv;
  }
  return v;
}

/** Which one leads, in one plain sentence. */
export function leaderLine(rows: CompareRow[]): string | null {
  const live = rows.filter((r) => r.active);
  const pool = live.length >= 2 ? live : rows;
  if (pool.length < 2) return null;
  const best = pool.reduce((a, b) => (b.returnPct > a.returnPct ? b : a));
  const worst = pool.reduce((a, b) => (b.returnPct < a.returnPct ? b : a));
  if (best.id === worst.id || Math.abs(best.returnPct - worst.returnPct) < 0.005) {
    return "All level so far.";
  }
  const young = pool.some((r) => r.days < 7);
  return `${best.name} leads at ${fmtPct(best.returnPct)}, ${worst.name} trails at ${fmtPct(worst.returnPct)}${
    young ? ". Under a week of running says little yet" : ""
  }.`;
}

/** "+1.23%", "−0.40%" with a real minus sign. */
export function fmtPct(n: number | null | undefined, dp = 2): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  const abs = Math.abs(n).toFixed(dp);
  return `${Number(abs) === 0 ? "" : n < 0 ? "−" : "+"}${abs}%`;
}
