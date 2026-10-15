// What Home shows: the portfolio across every active autopilot, as one value,
// one chart and one list of holdings. Pure functions, tested in homeView.test.ts.

import { curve, isActive } from "../autopilot";
import { holdings, type Holding } from "../practice";
import type { AutopilotStatus, PositionView } from "../types";
import type { Range } from "../design/primitives/controls";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/** How far back each chart range reaches; Max is everything. */
export const RANGE_MS: Record<Range, number> = {
  "1D": DAY,
  "1W": 7 * DAY,
  "1M": 30 * DAY,
  "1Y": 365 * DAY,
  Max: Number.POSITIVE_INFINITY,
};

export type Point = [number, number];

/** The value of a stepwise curve at `t`: its last point at or before t. */
function at(points: Point[], t: number): number | null {
  let v: number | null = null;
  for (const [pt, pv] of points) {
    if (pt > t) break;
    v = pv;
  }
  return v;
}

/**
 * One curve for several autopilots. Each adds its gain or loss from the
 * moment it started, on top of what all of them were given, so starting a new
 * autopilot never shows as a jump. It ends at the sum of their values.
 */
export function combinedCurve(list: AutopilotStatus[], now: number): Point[] {
  const act = list.filter(isActive);
  if (act.length === 0) return [];
  const curves = act.map((s) => ({ start: s.startCapital, pts: curve(s, now) }));
  if (curves.length === 1) return curves[0].pts;
  const base = curves.reduce((a, c) => a + c.start, 0);
  const times = [...new Set(curves.flatMap((c) => c.pts.map((p) => p[0])))].sort((a, b) => a - b);
  return times.map((t) => {
    let v = base;
    for (const c of curves) {
      const x = at(c.pts, t);
      if (x != null) v += x - c.start;
    }
    return [t, v] as Point;
  });
}

/**
 * The part of a curve inside a range, starting with its value at the start of
 * the range so the line does not begin in mid air.
 */
export function inRange(points: Point[], range: Range, now: number): Point[] {
  if (points.length === 0 || range === "Max") return points;
  const from = now - RANGE_MS[range];
  const inside = points.filter((p) => p[0] >= from);
  const before = at(points, from);
  // Nothing moved inside the range: a flat line at the value it had.
  if (before != null && inside.length === 0) return [[from, before], [now, before]];
  if (before != null && inside[0][0] > from) return [[from, before], ...inside];
  return inside.length >= 2 ? inside : points.slice(-2);
}

/** The ranges worth offering: the shortest one that already shows everything, and the ones below it. */
export function usefulRanges(points: Point[], now: number): Range[] {
  if (points.length < 2) return ["Max"];
  const span = now - points[0][0];
  const out: Range[] = [];
  for (const r of ["1D", "1W", "1M", "1Y"] as Range[]) {
    out.push(r);
    if (RANGE_MS[r] >= span) break;
  }
  return [...out, "Max"];
}

/** Gain or loss over the points shown, amount and percent. */
export function change(points: Point[]): { abs: number; pct: number | null } {
  if (points.length < 2) return { abs: 0, pct: null };
  const first = points[0][1];
  const abs = points[points.length - 1][1] - first;
  return { abs, pct: first !== 0 ? (abs / Math.abs(first)) * 100 : null };
}

/** Holdings of every active autopilot, one row per asset, biggest first. */
export function combinedHoldings(list: AutopilotStatus[], positions: PositionView[]): Holding[] {
  const by = new Map<string, Holding & { cost: number }>();
  for (const s of list.filter(isActive)) {
    for (const h of holdings(s, positions)) {
      if (by.has(h.marketId)) continue; // two autopilots on one market share the position
      by.set(h.marketId, { ...h, cost: h.value - h.pnl });
    }
  }
  return [...by.values()]
    .map(({ cost: _c, ...h }) => h)
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
}

/** Holdings straight from the account's positions, for when no autopilot runs. */
export function positionHoldings(positions: PositionView[]): Holding[] {
  return positions
    .filter((p) => Math.abs(p.qty) > 1e-12)
    .map((p) => {
      const cost = Math.abs(p.qty * p.avgPrice);
      return {
        marketId: p.marketId,
        coin: p.symbol,
        qty: p.qty,
        value: p.qty * p.lastPrice,
        pnl: p.unrealized,
        pnlPct: cost > 0 ? (p.unrealized / cost) * 100 : 0,
      };
    })
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
}
