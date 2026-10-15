// Geometry for the area charts, kept apart from React so it can be tested.

export interface ChartGeometry {
  /** SVG path of the line. */
  line: string;
  /** The line closed down to the bottom edge, for the soft fill. */
  area: string;
  /** Point positions in viewBox units, one per kept value. */
  xs: number[];
  ys: number[];
  /** The values the positions belong to (after thinning). */
  values: number[];
  /** Index into the original data for each kept point. */
  index: number[];
  min: number;
  max: number;
  /** y of a given value, in viewBox units. */
  yOf: (v: number) => number;
}

/**
 * Keep at most `max` points, evenly spread, always including the first and the
 * last. Charts of a year of minute bars stay light.
 */
export function thin(n: number, max: number): number[] {
  if (n <= max) return Array.from({ length: n }, (_, i) => i);
  const out: number[] = [];
  for (let k = 0; k < max; k++) out.push(Math.round((k * (n - 1)) / (max - 1)));
  return [...new Set(out)];
}

/**
 * A smooth line through the points without overshoot (monotone cubic, Fritsch
 * and Carlson), so a chart never draws a peak the data never had.
 */
export function smoothPath(xs: number[], ys: number[]): string {
  const n = xs.length;
  if (n === 0) return "";
  if (n === 1) return `M${xs[0].toFixed(2)},${ys[0].toFixed(2)}`;
  if (n === 2) return `M${xs[0].toFixed(2)},${ys[0].toFixed(2)}L${xs[1].toFixed(2)},${ys[1].toFixed(2)}`;
  const d: number[] = [];
  const m: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    const dx = xs[i + 1] - xs[i] || 1e-9;
    d.push((ys[i + 1] - ys[i]) / dx);
  }
  m.push(d[0]);
  for (let i = 1; i < n - 1; i++) m.push(d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2);
  m.push(d[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / d[i];
    const b = m[i + 1] / d[i];
    const s = a * a + b * b;
    if (s > 9) {
      const t = 3 / Math.sqrt(s);
      m[i] = t * a * d[i];
      m[i + 1] = t * b * d[i];
    }
  }
  let p = `M${xs[0].toFixed(2)},${ys[0].toFixed(2)}`;
  for (let i = 0; i < n - 1; i++) {
    const h = (xs[i + 1] - xs[i]) / 3;
    p += `C${(xs[i] + h).toFixed(2)},${(ys[i] + m[i] * h).toFixed(2)} ${(xs[i + 1] - h).toFixed(2)},${(ys[i + 1] - m[i + 1] * h).toFixed(2)} ${xs[i + 1].toFixed(2)},${ys[i + 1].toFixed(2)}`;
  }
  return p;
}

/**
 * Lay a series out in a `w` by `h` box with `pad` units free above and below
 * the line. Non-finite values are skipped. `include` widens the value range
 * (a baseline that must stay on screen).
 */
export function chartGeometry(data: readonly number[], w: number, h: number, pad = 4, maxPoints = 240, include: number[] = []): ChartGeometry | null {
  const finite: number[] = [];
  const origin: number[] = [];
  data.forEach((v, i) => {
    if (Number.isFinite(v)) {
      finite.push(v);
      origin.push(i);
    }
  });
  if (finite.length < 2) return null;
  const keep = thin(finite.length, maxPoints);
  const values = keep.map((k) => finite[k]);
  const index = keep.map((k) => origin[k]);
  const extra = include.filter((v) => Number.isFinite(v));
  const min = Math.min(...values, ...extra);
  const max = Math.max(...values, ...extra);
  const span = max - min || Math.abs(max) * 0.01 || 1;
  const yOf = (v: number) => pad + (1 - (v - min) / span) * (h - 2 * pad);
  const xs = values.map((_, i) => (i / (values.length - 1)) * w);
  const ys = values.map(yOf);
  const line = smoothPath(xs, ys);
  const area = `${line}L${w},${h}L0,${h}Z`;
  return { line, area, xs, ys, values, index, min, max, yOf };
}

/** Which kept point is nearest to a fraction (0 to 1) of the width. */
export function nearestIndex(xs: number[], w: number, frac: number): number {
  if (!xs.length) return -1;
  const x = Math.max(0, Math.min(1, frac)) * w;
  let best = 0;
  for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - x) < Math.abs(xs[best] - x)) best = i;
  return best;
}
