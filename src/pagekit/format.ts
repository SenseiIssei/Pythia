// Plain helpers the calm pages share: tone of a number, readable amounts and
// how full a limit is. No React here, so every rule is covered by a test.

import type { ChangeTone } from "../design/flows";

const MINUS = "−";

/** Green when up, red when down, flat inside the epsilon. */
export function toneOf(n: number | null | undefined, epsilon = 0.005): ChangeTone {
  if (n == null || !Number.isFinite(n)) return "flat";
  return n > epsilon ? "up" : n < -epsilon ? "down" : "flat";
}

/** A plain number with a real minus sign: "1,234.50", "−0.40". */
export function num(n: number | null | undefined, dp = 2): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  const s = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return n < 0 && Number(Math.abs(n).toFixed(dp)) !== 0 ? `${MINUS}${s}` : s;
}

/** "$1,234.56", "−$5.00". */
export function usd(n: number | null | undefined, dp = 2): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  const s = `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
  return n < 0 && Number(Math.abs(n).toFixed(dp)) !== 0 ? `${MINUS}${s}` : s;
}

/** Short amounts for tight rows: "$950", "$12.3k", "$4.1M". */
export function usdShort(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  const a = Math.abs(n);
  const sign = n < 0 && a >= 0.5 ? MINUS : "";
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${sign}$${(a / 1e3).toFixed(1)}k`;
  return `${sign}$${a.toFixed(0)}`;
}

/** A percent that is already in percent units: 12.345 -> "12.3%". */
export function pct(n: number | null | undefined, dp = 1): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  return `${num(n, dp)}%`;
}

/** A ratio shown as a signed percent: 0.0123 -> "+1.2%". */
export function signedRatio(x: number | null | undefined, dp = 1): string {
  if (x == null || !Number.isFinite(x)) return "n/a";
  const v = x * 100;
  const abs = Math.abs(v).toFixed(dp);
  if (Number(abs) === 0) return `${(0).toFixed(dp)}%`;
  return `${v < 0 ? MINUS : "+"}${abs}%`;
}

/** "1 trade", "3 trades". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
}

export type Level = "off" | "ok" | "near" | "over";

/**
 * How full a limit is. `cap <= 0` means the limit is switched off. "near"
 * starts at 80 % of the cap, "over" at the cap itself.
 */
export function usage(value: number, cap: number): { pct: number; level: Level } {
  if (!(cap > 0) || !Number.isFinite(value)) return { pct: 0, level: "off" };
  const p = Math.max(0, (value / cap) * 100);
  return { pct: p, level: p >= 100 ? "over" : p >= 80 ? "near" : "ok" };
}

/** "13:04" in the viewer's clock. */
export function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** "just now", "5 min ago", "3 h ago", "2 days ago". */
export function since(ms: number, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}
