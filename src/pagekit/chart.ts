// Geometry for the calm line chart: one shared y-scale, a path per series and
// a few round gridline values. Pure, so it is tested without a browser.

export interface Domain {
  min: number;
  max: number;
}

/** The y-range over every finite value, padded a little so lines never touch the edge. */
export function domainOf(series: number[][], pad = 0.06): Domain | null {
  let min = Infinity;
  let max = -Infinity;
  for (const s of series)
    for (const v of s)
      if (Number.isFinite(v)) {
        if (v < min) min = v;
        if (v > max) max = v;
      }
  if (!Number.isFinite(min)) return null;
  if (min === max) {
    const d = Math.abs(min) * 0.01 || 1;
    return { min: min - d, max: max + d };
  }
  const p = (max - min) * pad;
  return { min: min - p, max: max + p };
}

/**
 * An SVG path through the finite points of one series, `len` points wide so
 * shorter series line up on the left. A gap (NaN) breaks the line.
 */
export function pathOf(data: number[], d: Domain, w: number, h: number, len = data.length): string {
  const n = Math.max(len, 2);
  const span = d.max - d.min || 1;
  let out = "";
  let pen = false;
  data.forEach((v, i) => {
    if (!Number.isFinite(v)) {
      pen = false;
      return;
    }
    const x = (i / (n - 1)) * w;
    const y = h - ((v - d.min) / span) * h;
    out += `${pen ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    pen = true;
  });
  return out;
}

/** Up to `count` round values inside the domain, for quiet gridlines. */
export function ticksOf(d: Domain, count = 3): number[] {
  const span = d.max - d.min;
  if (!(span > 0)) return [d.min];
  const raw = span / (count + 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(d.min / step) * step; v < d.max && out.length < count + 2; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

/** The y position of a value, for drawing a gridline or a marker. */
export function yOf(v: number, d: Domain, h: number): number {
  const span = d.max - d.min || 1;
  return h - ((v - d.min) / span) * h;
}
