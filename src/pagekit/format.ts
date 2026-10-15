// Small helpers the redesigned pages share on top of src/design/format.ts:
// plain numbers, percents already in percent units, counted words and how
// full a limit is. No React here, so every rule is covered by a test.

const MINUS = "−";

/** A plain number with a real minus sign: "1,234.50", "−0.40". */
export function num(n: number | null | undefined, dp = 2): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  const s = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return n < 0 && Number(Math.abs(n).toFixed(dp)) !== 0 ? `${MINUS}${s}` : s;
}

/** A percent that is already in percent units: 12.345 reads "12.3%". */
export function pct(n: number | null | undefined, dp = 1): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  return `${num(n, dp)}%`;
}

/** A fraction as an unsigned percent: 0.55 reads "55%". */
export function share(x: number | null | undefined, dp = 0): string {
  return x == null || !Number.isFinite(x) ? "n/a" : pct(x * 100, dp);
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

/** The words for a limit level, so the meter never relies on colour alone. */
export function levelWord(l: Level): string {
  return l === "off" ? "Off" : l === "over" ? "At the limit" : l === "near" ? "Close to the limit" : "Within the limit";
}

/** "13:04" in the viewer's clock. */
export function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
