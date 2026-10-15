// Number formatting for the design system. Every amount on screen goes through
// here, so a minus is always the real minus sign and a gain always has its +.

export type ChangeTone = "up" | "down" | "flat";

const MINUS = "−";

/** "$1,234.56". Non-finite numbers read "n/a" rather than "NaN". */
export function money(n: number, dp = 2): string {
  if (!Number.isFinite(n)) return "n/a";
  const s = Math.abs(n).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: dp, maximumFractionDigits: dp });
  return n < 0 && Number(Math.abs(n).toFixed(dp)) !== 0 ? `${MINUS}${s}` : s;
}

/** "+$12.34", "−$5.00", "$0.00". */
export function signedMoney(n: number, dp = 2): string {
  if (!Number.isFinite(n)) return "n/a";
  if (Number(Math.abs(n).toFixed(dp)) === 0) return money(0, dp);
  return `${n < 0 ? MINUS : "+"}${money(Math.abs(n), dp)}`;
}

/** A percent already in percent units: 1.234 reads "+1.23%". */
export function signedPct(n: number | null | undefined, dp = 2): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  const abs = Math.abs(n).toFixed(dp);
  if (Number(abs) === 0) return `${(0).toFixed(dp)}%`;
  return `${n < 0 ? MINUS : "+"}${abs}%`;
}

/** A fraction as a signed percent: 0.0123 reads "+1.23%". */
export function signedRatio(n: number | null | undefined, dp = 2): string {
  return n == null || !Number.isFinite(n) ? "n/a" : signedPct(n * 100, dp);
}

/** "$1.2K", "$3.4M", "$12" for tight spaces. */
export function compactMoney(n: number): string {
  if (!Number.isFinite(n)) return "n/a";
  const abs = Math.abs(n);
  const sign = n < 0 ? MINUS : "";
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(abs >= 1e10 ? 0 : 1)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(abs >= 1e4 ? 0 : 1)}K`;
  return `${sign}$${abs.toFixed(abs >= 100 ? 0 : 2)}`;
}

/**
 * A price with as many decimals as it needs: big prices get two, tiny coins
 * get enough to show they moved.
 */
export function price(n: number): string {
  if (!Number.isFinite(n)) return "n/a";
  const abs = Math.abs(n);
  const dp = abs >= 1000 ? 2 : abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6;
  return money(n, dp);
}

/** Up, down or flat, with a dead band so a rounding wobble reads as flat. */
export function changeTone(n: number | null | undefined, epsilon = 0.005): ChangeTone {
  if (n == null || !Number.isFinite(n)) return "flat";
  return n > epsilon ? "up" : n < -epsilon ? "down" : "flat";
}

/** Change between the first and the last point of a series: amount and percent. */
export function seriesChange(data: readonly number[]): { abs: number; pct: number | null; tone: ChangeTone } {
  const pts = data.filter((v) => Number.isFinite(v));
  if (pts.length < 2) return { abs: 0, pct: null, tone: "flat" };
  const first = pts[0];
  const last = pts[pts.length - 1];
  const abs = last - first;
  const pct = first !== 0 ? (abs / Math.abs(first)) * 100 : null;
  return { abs, pct, tone: changeTone(abs, Math.abs(first) * 1e-6 || 0.005) };
}

/** The ticker a badge shows: the base of a pair, upper case, at most 4 letters. */
export function tickerOf(symbol: string): string {
  const base = symbol.split(/[/:\-_ ]/)[0] || symbol;
  return base.replace(/[^a-z0-9]/gi, "").toUpperCase().slice(0, 4) || "?";
}

/** A stable hue for a ticker badge, so BTC always looks like BTC. */
export function tickerHue(symbol: string): number {
  let h = 0;
  for (const c of tickerOf(symbol)) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

/** "just now", "5 min ago", "3 h ago", "2 d ago". */
export function ago(ms: number, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 36) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}
