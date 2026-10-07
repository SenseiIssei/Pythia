// Return-series correlation for concentration analysis.
//
// The same rules as the risk manager (`crates/pythia-core/src/engine/risk.rs`,
// `PriceSeries`), so the Correlation page shows the numbers the caps use:
//
// - two markets on real candles are compared on the bar times both have;
// - two markets on live ticks on their shared tail (both tick together);
// - a candle market against a tick market is not compared at all. Pairing a
//   5-minute return with a 1.5-second one measures nothing, so the cell is
//   `null` and the risk manager counts the pair as the worst case.
//
// One difference is kept on purpose: a tick pair with no variance is drawn as
// 0 here, where the risk manager treats it as unknown.

/** Closes per market the correlation is measured on, as in the engine. */
export const CORR_WINDOW = 60;

export function toReturns(prices: number[]): number[] {
  const r: number[] = [];
  for (let i = 1; i < prices.length; i++) {
    if (prices[i - 1] !== 0) r.push(prices[i] / prices[i - 1] - 1);
  }
  return r;
}

function mean(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0) / (xs.length || 1);
}

/** Pearson correlation and whether both sides moved at all. */
function pearsonOrNull(a: number[], b: number[]): number | null {
  const n = Math.min(a.length, b.length);
  if (n < 3) return null;
  const aa = a.slice(a.length - n);
  const bb = b.slice(b.length - n);
  const ma = mean(aa);
  const mb = mean(bb);
  let cov = 0;
  let va = 0;
  let vb = 0;
  for (let i = 0; i < n; i++) {
    const da = aa[i] - ma;
    const db = bb[i] - mb;
    cov += da * db;
    va += da * da;
    vb += db * db;
  }
  if (va === 0 || vb === 0) return null;
  return Math.max(-1, Math.min(1, cov / Math.sqrt(va * vb)));
}

/** Pearson correlation of two return series (aligned on their shared tail). */
export function pearson(a: number[], b: number[]): number {
  return pearsonOrNull(a, b) ?? 0;
}

/**
 * Correlation of two candle series on the bar times both have, within each
 * one's last `CORR_WINDOW` bars. `null` when they share fewer than `minLen`
 * bar times or one did not move. A bar one of them is missing drops out of
 * both, so every return pairs the same interval. Mirrors Rust `bar_correlation`.
 */
export function alignedPearson(a: number[], ta: number[], b: number[], tb: number[], minLen = 20): number | null {
  const tail = (p: number[], t: number[]) => {
    const n = Math.min(p.length, t.length, CORR_WINDOW);
    return { p: p.slice(p.length - n), t: t.slice(t.length - n) };
  };
  const x = tail(a, ta);
  const y = tail(b, tb);
  if (x.p.length < minLen || y.p.length < minLen) return null;
  const byTime = new Map(y.t.map((t, i) => [t, y.p[i]]));
  const shared: [number, number][] = [];
  x.t.forEach((t, i) => {
    const other = byTime.get(t);
    if (other !== undefined) shared.push([x.p[i], other]);
  });
  if (shared.length < minLen) return null;
  const ret = (k: 0 | 1) =>
    shared.slice(1).map((s, i) => (shared[i][k] !== 0 ? s[k] / shared[i][k] - 1 : 0));
  return pearsonOrNull(ret(0), ret(1));
}

export interface CorrMatrix {
  ids: string[];
  /** `null` where a pair cannot be compared in time (candles against ticks,
   *  or candles with too few bar times in common). */
  matrix: (number | null)[][];
}

/**
 * Pairwise return correlations. `times` holds bar open times for the markets
 * on real candles (`historyTimes` in the store); a market missing from it is
 * on ticks.
 */
export function correlationMatrix(
  history: Record<string, number[]>,
  times: Record<string, number[]> = {},
  minLen = 20
): CorrMatrix {
  const ids = Object.keys(history).filter((id) => (history[id]?.length ?? 0) >= minLen);
  const returns = ids.map((id) => toReturns(history[id]));
  const timed = ids.map((id) => (times[id]?.length ?? 0) > 0);
  const matrix = ids.map((a, i) =>
    ids.map((b, j) => {
      if (i === j) return 1;
      if (timed[i] && timed[j]) return alignedPearson(history[a], times[a], history[b], times[b], minLen);
      if (timed[i] !== timed[j]) return null;
      return pearson(returns[i], returns[j]);
    })
  );
  return { ids, matrix };
}

export interface Concentration {
  n: number;
  avgAbsCorr: number;
  effectiveBets: number; // n / (1 + (n-1)*avgAbsCorr): how many *independent* bets you really hold
  /** Held pairs that could not be compared, counted as |correlation| 1 the
   *  way the risk manager counts them. */
  unmeasured: number;
}

/** Concentration of a held subset given the full matrix. */
export function concentration(heldIds: string[], corr: CorrMatrix): Concentration {
  const idx = heldIds.map((id) => corr.ids.indexOf(id)).filter((i) => i >= 0);
  const n = idx.length;
  if (n < 2) return { n, avgAbsCorr: 0, effectiveBets: n, unmeasured: 0 };
  let sum = 0;
  let pairs = 0;
  let unmeasured = 0;
  for (let a = 0; a < idx.length; a++) {
    for (let b = a + 1; b < idx.length; b++) {
      const r = corr.matrix[idx[a]][idx[b]];
      if (r === null) unmeasured++;
      sum += r === null ? 1 : Math.abs(r);
      pairs++;
    }
  }
  const avgAbsCorr = pairs ? sum / pairs : 0;
  const effectiveBets = n / (1 + (n - 1) * avgAbsCorr);
  return { n, avgAbsCorr, effectiveBets, unmeasured };
}
