// The Activity timeline: the engine's events ring and journal, plus the
// operator alerts, turned into simple rows grouped by day. Pure functions.

import type { JournalEntry, Market } from "../types";
import { alertTitle, plainText, type AlertRecord } from "./alerts";

export type ActivityKind = "buy" | "sell" | "rebalance" | "autopilot" | "alert" | "risk" | "refused" | "summary";

export interface ActivityItem {
  id: string;
  ts: number;
  kind: ActivityKind;
  /** The row's main line: "Bought BTC", "Rebalanced". */
  title: string;
  /** The second line, short. */
  detail: string;
  /** Right-hand amount, when there is one ("$1,234.56"). */
  amount?: string;
  /** Practice money or real money. */
  real: boolean;
}

export interface ActivityDay {
  key: string;
  /** "Today", "Yesterday", "Mon 13 Oct". */
  label: string;
  items: ActivityItem[];
  /** "2 trades · 1 rebalance". Empty when there is nothing to count. */
  summary: string;
}

/**
 * Which journal lines belong on the timeline. Mirrors the engine's
 * `is_event` (crates/pythia-core/src/engine/mod.rs), so a build without the
 * events ring shows the same kinds of line from the journal.
 */
export function isEvent(e: Pick<JournalEntry, "kind" | "message">): boolean {
  switch (e.kind) {
    case "order":
    case "fill":
    case "reject":
    case "risk":
      return true;
    case "signal":
      return e.message.startsWith("Rebalance") || e.message.includes("utopilot");
    case "system":
      return ["Exit ", "Trim ", "DEMO ", "Live ", "LIVE "].some((p) => e.message.startsWith(p)) || e.message.includes("utopilot");
    default:
      return false;
  }
}

export interface ParsedFill {
  side: "buy" | "sell";
  qty: number;
  marketId: string;
  price: number;
  /** The mode word the engine wrote: Paper, DEMO, LIVE. */
  mode: string;
}

const FILL_RE = /^(\w+)\s+FILL\s+(Buy|Sell)\s+(-?[\d.]+)\s+(\S+)\s+@\s+([\d.]+)/i;

/** "Paper FILL Buy 0.0123 crypto:BTC/USD @ 67250.0000" into its parts. */
export function parseFill(message: string): ParsedFill | null {
  const m = FILL_RE.exec(message.trim());
  if (!m) return null;
  const qty = Math.abs(Number(m[3]));
  const price = Number(m[5]);
  if (!Number.isFinite(qty) || !Number.isFinite(price)) return null;
  return { side: m[2].toLowerCase() === "buy" ? "buy" : "sell", qty, marketId: m[4], price, mode: m[1] };
}

/** "crypto:BTC/USD" or "BTC/USD" to "BTC"; a share ticker stays as it is. */
export function assetName(marketId: string, symbols: Map<string, string> = new Map()): string {
  const sym = symbols.get(marketId) ?? marketId.split(":").pop() ?? marketId;
  return sym.split("/")[0] || sym;
}

export function usd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function qtyText(q: number): string {
  const dp = q >= 100 ? 2 : q >= 1 ? 4 : 6;
  return Number(q.toFixed(dp)).toLocaleString("en-US", { maximumFractionDigits: dp });
}

/** The first sentence, without a trailing dot, cut to a phone's width. */
export function shortLine(t: string, max = 90): string {
  const first = t.split(/(?<=[.!?])\s/)[0].trim().replace(/[.\s]+$/, "");
  return first.length > max ? `${first.slice(0, max - 1).trimEnd()}…` : first;
}

/** One journal or event line as a timeline row; null for lines that do not belong. */
export function fromJournal(e: JournalEntry, symbols: Map<string, string> = new Map()): ActivityItem | null {
  if (!isEvent(e)) return null;
  const real = e.mode === "live";
  const base = { id: e.id, ts: e.ts, real };
  if (e.kind === "fill") {
    const f = parseFill(e.message);
    if (!f) return { ...base, kind: "buy", title: "Trade filled", detail: shortLine(e.message) };
    const asset = assetName(f.marketId, symbols);
    const real2 = real || /^live$/i.test(f.mode);
    return {
      ...base,
      real: real2,
      kind: f.side,
      title: `${f.side === "buy" ? "Bought" : "Sold"} ${asset}`,
      detail: `${qtyText(f.qty)} at ${usd(f.price)}`,
      amount: usd(f.qty * f.price),
    };
  }
  // Placed orders say the same as the fill that follows; the fill is the row.
  if (e.kind === "order") return null;
  if (e.kind === "reject") return { ...base, kind: "refused", title: "Order refused", detail: shortLine(e.message) };
  if (e.kind === "risk") return { ...base, kind: "risk", title: "Safety rule", detail: shortLine(e.message) };
  if (e.message.startsWith("Rebalance")) return { ...base, kind: "rebalance", title: "Rebalanced", detail: shortLine(e.message) };
  if (e.message.includes("utopilot")) return { ...base, kind: "autopilot", title: "Autopilot", detail: shortLine(e.message) };
  if (e.message.startsWith("Exit ") || e.message.startsWith("Trim ")) {
    return { ...base, kind: "sell", title: e.message.startsWith("Exit ") ? "Position closed" : "Position trimmed", detail: shortLine(e.message) };
  }
  return { ...base, kind: "autopilot", title: "Update", detail: shortLine(e.message) };
}

/** One operator alert as a timeline row. */
export function fromAlert(a: AlertRecord, i: number): ActivityItem {
  return {
    id: `alert:${a.ts}:${i}`,
    ts: a.ts,
    kind: "alert",
    title: alertTitle(a),
    detail: shortLine(plainText(a.text)),
    real: false,
  };
}

/** The daily report as a row. */
export function fromDigest(d: { ts: number; text: string } | null | undefined): ActivityItem | null {
  if (!d || !Number.isFinite(d.ts)) return null;
  return { id: `digest:${d.ts}`, ts: d.ts, kind: "summary", title: "Daily report", detail: shortLine(d.text, 140), real: false };
}

/** Local calendar day, "2026-10-15". */
export function dayKey(ts: number): string {
  const d = new Date(ts);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** "Today", "Yesterday", or "Mon 13 Oct" (with the year when it is not this year). */
export function dayLabel(ts: number, now: number): string {
  const k = dayKey(ts);
  if (k === dayKey(now)) return "Today";
  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  if (k === dayKey(y.getTime())) return "Yesterday";
  const d = new Date(ts);
  const sameYear = d.getFullYear() === new Date(now).getFullYear();
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
}

/** "3 trades · 1 rebalance · 2 alerts". */
export function daySummary(items: ActivityItem[]): string {
  const trades = items.filter((i) => i.kind === "buy" || i.kind === "sell").length;
  const reb = items.filter((i) => i.kind === "rebalance").length;
  const alerts = items.filter((i) => i.kind === "alert").length;
  const parts: string[] = [];
  const n = (c: number, one: string, many: string) => `${c} ${c === 1 ? one : many}`;
  if (trades) parts.push(n(trades, "trade", "trades"));
  if (reb) parts.push(n(reb, "rebalance", "rebalances"));
  if (alerts) parts.push(n(alerts, "alert", "alerts"));
  return parts.join(" · ");
}

export type ActivityFilter = "all" | "trades" | "alerts";

export function matchesFilter(i: ActivityItem, f: ActivityFilter): boolean {
  if (f === "trades") return i.kind === "buy" || i.kind === "sell" || i.kind === "rebalance";
  if (f === "alerts") return i.kind === "alert" || i.kind === "risk" || i.kind === "refused" || i.kind === "summary";
  return true;
}

export interface TimelineInput {
  events?: JournalEntry[];
  journal?: JournalEntry[];
  alerts?: AlertRecord[];
  digest?: { ts: number; text: string } | null;
  markets?: Market[];
}

/**
 * The whole timeline, newest first, grouped by local day. Events and journal
 * overlap (the ring keeps what the journal drops); they merge by id.
 */
export function timeline(input: TimelineInput, now: number, filter: ActivityFilter = "all", limit = 300): ActivityDay[] {
  const symbols = new Map((input.markets ?? []).map((m) => [m.id, m.symbol]));
  const seen = new Set<string>();
  const items: ActivityItem[] = [];
  for (const e of [...(input.events ?? []), ...(input.journal ?? [])]) {
    if (seen.has(e.id)) continue;
    seen.add(e.id);
    const it = fromJournal(e, symbols);
    if (it) items.push(it);
  }
  (input.alerts ?? []).forEach((a, i) => items.push(fromAlert(a, i)));
  const dg = fromDigest(input.digest);
  if (dg) items.push(dg);

  const shown = items
    .filter((i) => Number.isFinite(i.ts) && matchesFilter(i, filter))
    .sort((a, b) => b.ts - a.ts)
    .slice(0, limit);
  const days: ActivityDay[] = [];
  for (const it of shown) {
    const key = dayKey(it.ts);
    let day = days[days.length - 1];
    if (!day || day.key !== key) {
      day = { key, label: dayLabel(it.ts, now), items: [], summary: "" };
      days.push(day);
    }
    day.items.push(it);
  }
  for (const d of days) d.summary = daySummary(d.items);
  return days;
}

/** "14:05". */
export function timeOfDay(ts: number): string {
  return new Date(ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
