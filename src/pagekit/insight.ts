// Pure helpers for the Analytics, Correlation, Models, Lab and Research pages:
// the key numbers of a curve, the most correlated pairs, calm matrix tints and
// plain words for model and lab states. No React, so every rule has a test.

import type { ChipTone } from "../design";

// ── curves ─────────────────────────────────────────────────────────────────

/** Percent below the running high at every point: 0 at a new high, negative below it. */
export function drawdownSeries(curve: readonly number[]): number[] {
  let peak = -Infinity;
  return curve.map((v) => {
    if (v > peak) peak = v;
    // At the high itself the dip is a plain 0, never a negative zero.
    return peak > 0 && v < peak ? -((peak - v) / peak) * 100 : 0;
  });
}

/** The deepest dip below a high, in percent (0 or negative). */
export function worstDip(curve: readonly number[]): number {
  const dd = drawdownSeries(curve);
  return dd.length ? Math.min(0, ...dd) : 0;
}

/** Percent change from the first to the last point; null without two usable points. */
export function curveReturn(curve: readonly number[]): number | null {
  const pts = curve.filter((v) => Number.isFinite(v));
  if (pts.length < 2 || pts[0] === 0) return null;
  return ((pts[pts.length - 1] - pts[0]) / Math.abs(pts[0])) * 100;
}

/** Gross, costs and net added up over several strategies. */
export function sumPnl(list: readonly { gross: number; costs: number; net: number }[]): { gross: number; costs: number; net: number } {
  return list.reduce((a, p) => ({ gross: a.gross + p.gross, costs: a.costs + p.costs, net: a.net + p.net }), { gross: 0, costs: 0, net: 0 });
}

// ── correlation ────────────────────────────────────────────────────────────

/**
 * A calm cell tint from the theme tokens: moving together (risk piles up) in
 * the loss colour, moving opposite in the gain colour, the strength as alpha.
 * Null (cannot compare) gets no fill.
 */
export function corrTint(r: number | null): string {
  if (r === null || !Number.isFinite(r)) return "transparent";
  const a = Math.min(1, Math.abs(r));
  const alpha = (0.06 + a * 0.34).toFixed(3);
  return r >= 0 ? `rgb(var(--pt-down) / ${alpha})` : `rgb(var(--pt-up) / ${alpha})`;
}

/** What a correlation means, in words. */
export function corrWord(r: number | null): string {
  if (r === null || !Number.isFinite(r)) return "cannot be compared";
  if (r >= 0.7) return "move almost as one";
  if (r >= 0.4) return "often move together";
  if (r > -0.4) return "mostly independent";
  if (r > -0.7) return "often move opposite";
  return "move almost opposite";
}

export interface CorrPair {
  a: string;
  b: string;
  r: number;
  /** Both sides are held right now. */
  held: boolean;
}

/**
 * The most alike pairs, strongest first by absolute correlation. Held pairs
 * go first when `heldFirst` is set, since those are the ones that matter for
 * the account. Diagonal and pairs that cannot be compared are left out.
 */
export function topPairs(
  corr: { ids: readonly string[]; matrix: readonly (readonly (number | null)[])[] },
  held: readonly string[] = [],
  n = 5,
  heldFirst = true,
): CorrPair[] {
  const h = new Set(held);
  const out: CorrPair[] = [];
  for (let i = 0; i < corr.ids.length; i++) {
    for (let j = i + 1; j < corr.ids.length; j++) {
      const r = corr.matrix[i]?.[j];
      if (r == null || !Number.isFinite(r)) continue;
      out.push({ a: corr.ids[i], b: corr.ids[j], r, held: h.has(corr.ids[i]) && h.has(corr.ids[j]) });
    }
  }
  out.sort((x, y) => (heldFirst && x.held !== y.held ? (x.held ? -1 : 1) : Math.abs(y.r) - Math.abs(x.r)));
  return out.slice(0, Math.max(0, n));
}

/** How bunched the held positions are, as a level and a sentence. */
export function bunching(n: number, effectiveBets: number): { tone: "up" | "warn" | "down" | "plain"; word: string } {
  if (n < 2) return { tone: "plain", word: "Needs two or more positions to compare" };
  const share = effectiveBets / n;
  if (share < 0.5) return { tone: "down", word: "Mostly one bet in disguise" };
  if (share < 0.8) return { tone: "warn", word: "Partly bunched together" };
  return { tone: "up", word: "Well spread" };
}

// ── models ─────────────────────────────────────────────────────────────────

/** The model's next-hour forecast against the week's average, in words. */
export function outlook(modelVolPct: number, weekVolPct: number): { word: string; tone: ChipTone } {
  const ratio = weekVolPct > 0 ? modelVolPct / weekVolPct : NaN;
  if (!Number.isFinite(ratio)) return { word: "normal", tone: "neutral" };
  if (ratio > 1.25) return { word: "busier than usual", tone: "bad" };
  if (ratio < 0.8) return { word: "calmer than usual", tone: "good" };
  return { word: "normal", tone: "neutral" };
}

export type Drift = "stable" | "shift" | "drift";

/** An input's distance from the training data, as a chip. */
export function driftChip(level: Drift | string): { word: string; tone: ChipTone } {
  if (level === "drift") return { word: "outside trained range", tone: "bad" };
  if (level === "shift") return { word: "different regime", tone: "accent" };
  return { word: "like training", tone: "good" };
}

/**
 * The live ranking skill against its backtest: holding at least half of the
 * lab's number is good, positive but less is so-so, zero or below is bad.
 */
export function icTone(live: number | null | undefined, lab: number | null | undefined): "up" | "warn" | "down" | "plain" {
  if (live == null || !Number.isFinite(live)) return "plain";
  if (lab != null && Number.isFinite(lab) && live >= lab * 0.5 && live > 0) return "up";
  return live > 0 ? "warn" : "down";
}

// ── lab ────────────────────────────────────────────────────────────────────

/** The lab's old six tones as calm chip tones. "Better than expected" stays good. */
export function labChip(t: string): ChipTone {
  return t === "green" || t === "cyan" ? "good" : t === "amber" ? "warn" : t === "red" ? "bad" : t === "purple" ? "accent" : "neutral";
}

/** How the forward tests stand: how many are in line or better, and how many passed the 30-day gate. */
export function forwardTally(rows: readonly { status: string; gate7: { ready: boolean } }[]): { total: number; fine: number; watch: number; ready: number } {
  let fine = 0;
  let watch = 0;
  let ready = 0;
  for (const r of rows) {
    if (r.status === "on_track" || r.status === "ahead") fine++;
    if (r.status === "watch") watch++;
    if (r.gate7.ready) ready++;
  }
  return { total: rows.length, fine, watch, ready };
}

/** A plain number with its sign: "+0.123", "−0.040", "0.000". */
export function signedNum(n: number | null | undefined, dp = 3): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  const abs = Math.abs(n).toFixed(dp);
  if (Number(abs) === 0) return (0).toFixed(dp);
  return `${n < 0 ? "−" : "+"}${abs}`;
}

/** Coin names without the quote currency: "BTCUSDT" reads "BTC". */
export function coinName(symbol: string): string {
  return symbol.replace(/USDT$/, "");
}
