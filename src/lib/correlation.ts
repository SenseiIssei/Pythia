// Return-series correlation for concentration analysis.

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

/** Pearson correlation of two return series (aligned on their shared tail). */
export function pearson(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  if (n < 3) return 0;
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
  if (va === 0 || vb === 0) return 0;
  return Math.max(-1, Math.min(1, cov / Math.sqrt(va * vb)));
}

export interface CorrMatrix {
  ids: string[];
  matrix: number[][];
}

export function correlationMatrix(history: Record<string, number[]>, minLen = 20): CorrMatrix {
  const ids = Object.keys(history).filter((id) => (history[id]?.length ?? 0) >= minLen);
  const returns = ids.map((id) => toReturns(history[id]));
  const matrix = ids.map((_, i) => ids.map((_, j) => (i === j ? 1 : pearson(returns[i], returns[j]))));
  return { ids, matrix };
}

export interface Concentration {
  n: number;
  avgAbsCorr: number;
  effectiveBets: number; // n / (1 + (n-1)*avgAbsCorr) — how many *independent* bets you really hold
}

/** Concentration of a held subset given the full matrix. */
export function concentration(heldIds: string[], corr: CorrMatrix): Concentration {
  const idx = heldIds.map((id) => corr.ids.indexOf(id)).filter((i) => i >= 0);
  const n = idx.length;
  if (n < 2) return { n, avgAbsCorr: 0, effectiveBets: n };
  let sum = 0;
  let pairs = 0;
  for (let a = 0; a < idx.length; a++) {
    for (let b = a + 1; b < idx.length; b++) {
      sum += Math.abs(corr.matrix[idx[a]][idx[b]]);
      pairs++;
    }
  }
  const avgAbsCorr = pairs ? sum / pairs : 0;
  const effectiveBets = n / (1 + (n - 1) * avgAbsCorr);
  return { n, avgAbsCorr, effectiveBets };
}
