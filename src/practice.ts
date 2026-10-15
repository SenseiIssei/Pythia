// The arithmetic behind the Practice page: which autopilots to show, what
// each one holds, how it did against simply holding Bitcoin, when the next lab
// signal is due, and the latest fills in plain rows. Pure functions, so the
// numbers a beginner reads are tested, not eyeballed.

import { DAY_MS, compareWithHold, curve, isActive } from "./autopilot";
import type { ForwardReport, ForwardRow } from "./lab";
import type { AutopilotStatus, FillRoute, Market, Order, PositionView } from "./types";

/** The lab writes its daily signals at about this time, UTC. */
export const LAB_SIGNAL_HOUR_UTC = 4;
export const LAB_SIGNAL_MINUTE_UTC = 15;

/** A stopped autopilot stays on the page this long after it stopped. */
export const RECENT_MS = 7 * DAY_MS;

const MINUS = "−";

/** "+$12.34", "−$5.00", "$0.00". A real minus sign, so it reads as one. */
export function signedUsd(n: number, dp = 2): string {
  if (!Number.isFinite(n)) return "n/a";
  const abs = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  const zero = Number(abs.replace(/,/g, "")) === 0;
  return `${zero ? "" : n < 0 ? MINUS : "+"}$${abs}`;
}

/** "+1.23%", "−0.40%", "0.00%". */
export function signedPctText(n: number | null | undefined, dp = 2): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  const abs = Math.abs(n).toFixed(dp);
  const zero = Number(abs) === 0;
  return `${zero ? "" : n < 0 ? MINUS : "+"}${abs}%`;
}

export type Direction = "up" | "down" | "flat";

/** Up, down, or not moved at all (within half a cent, or a hundredth of a percent). */
export function direction(n: number | null | undefined, epsilon = 0.005): Direction {
  if (n == null || !Number.isFinite(n)) return "flat";
  return n > epsilon ? "up" : n < -epsilon ? "down" : "flat";
}

/** "BTC/USD" to "BTC"; anything without a slash stays as it is. */
export function coinOf(symbol: string): string {
  return symbol.split("/")[0] || symbol;
}

/** Price with sensible decimals: $67,250.00, $3.4512, $0.000123. */
export function fmtPrice(p: number): string {
  if (!Number.isFinite(p)) return "n/a";
  const a = Math.abs(p);
  const dp = a >= 1000 ? 2 : a >= 1 ? 4 : a >= 0.01 ? 5 : 8;
  return `$${p.toLocaleString("en-US", { minimumFractionDigits: Math.min(dp, 2), maximumFractionDigits: dp })}`;
}

/** Coin amount without trailing noise: 0.0123, 1.5, 120. */
export function fmtQty(q: number): string {
  if (!Number.isFinite(q)) return "n/a";
  const a = Math.abs(q);
  const dp = a >= 100 ? 2 : a >= 1 ? 4 : 6;
  return Number(q.toFixed(dp)).toLocaleString("en-US", { maximumFractionDigits: dp });
}

/**
 * The autopilots worth showing: every active one, then the ones that stopped
 * in the last week, newest first.
 */
export function practiceAutopilots(list: AutopilotStatus[], now: number): AutopilotStatus[] {
  const active = list.filter(isActive).sort((a, b) => b.startedMs - a.startedMs);
  const recent = list
    .filter((s) => !isActive(s) && s.stoppedMs != null && now - s.stoppedMs <= RECENT_MS)
    .sort((a, b) => (b.stoppedMs ?? 0) - (a.stoppedMs ?? 0));
  return [...active, ...recent];
}

/** The next time the daily lab signal is due, strictly after `now`. */
export function nextLabSignalMs(now: number): number {
  const d = new Date(now);
  const today = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), LAB_SIGNAL_HOUR_UTC, LAB_SIGNAL_MINUTE_UTC);
  return today > now ? today : today + DAY_MS;
}

/** True when at least one of its strategies runs on the lab's daily signal. */
export function usesLabSignal(s: AutopilotStatus): boolean {
  return s.bySleeve.some((b) => b.strategyId.startsWith("lab:")) || s.config.sleeves.some((c) => c.strategyId.startsWith("lab:"));
}

export interface Holding {
  marketId: string;
  coin: string;
  qty: number;
  /** What it is worth at the last price. */
  value: number;
  pnl: number;
  /** P&L against what it cost, percent. */
  pnlPct: number;
}

/**
 * Is this position in the autopilot's own book? Every autopilot keeps a book
 * of its own, so two of them can hold the same coin: the position says whose
 * it is (`book`). An older engine has no books; there the markets it holds
 * (`held`, or its sleeves' markets) decide.
 */
export function inBook(s: AutopilotStatus, p: PositionView): boolean {
  if (p.key !== undefined) return p.book === s.config.id && (s.held ? s.held.includes(p.marketId) : true);
  const own = s.held ?? s.bySleeve.flatMap((b) => b.markets);
  return own.includes(p.marketId);
}

/**
 * What an autopilot holds now: the positions of its own book (see
 * [`inBook`]).
 */
export function holdings(s: AutopilotStatus, positions: PositionView[]): Holding[] {
  if (!isActive(s) && !s.held) return [];
  return positions
    .filter((p) => inBook(s, p) && Math.abs(p.qty) > 1e-12)
    .map((p) => {
      const cost = Math.abs(p.qty * p.avgPrice);
      return {
        marketId: p.marketId,
        coin: coinOf(p.symbol),
        qty: p.qty,
        value: p.qty * p.lastPrice,
        pnl: p.unrealized,
        pnlPct: cost > 0 ? (p.unrealized / cost) * 100 : 0,
      };
    })
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
}

/** Why it holds nothing right now, in one sentence. */
export function cashReason(s: AutopilotStatus): string {
  if (s.state === "paused") return s.pausedReason ? `Paused: ${s.pausedReason}.` : "Paused: it opens nothing new.";
  if (!isActive(s)) return s.stopReason ? `Stopped: ${s.stopReason}.` : "Stopped.";
  if (usesLabSignal(s)) return "In cash, waiting for a signal: the latest lab signal says to hold nothing.";
  return "In cash, waiting for a signal: none of its strategies sees a trade worth taking yet.";
}

export interface Benchmark {
  /** Bitcoin's change over the run, percent. */
  btcPct: number;
  /** The autopilot's change over the same window, percent. */
  runPct: number;
  /** Percentage points ahead of Bitcoin (negative: behind). */
  edgePct: number;
  /** Taken from the price history, which may not reach back to the start. */
  approximate: boolean;
  /** What it is held against, in words: "Bitcoin" or "SPY". */
  label?: string;
}

/** "Bitcoin" for BTC/USD, "BTC/SPY blend" for a portfolio's blend
 *  ("BTC/USD+SPY"), the symbol for anything else. */
export function benchLabel(symbol: string | undefined): string {
  if (symbol && symbol.includes("+")) return "BTC/SPY blend";
  return !symbol || /^BTC\b/i.test(symbol) ? "Bitcoin" : symbol;
}

/**
 * The autopilot against simply holding its benchmark over the same period:
 * the engine's own figure first (BTC for crypto, SPY for US shares, from its
 * start or from when the comparison could start); without one, the BTC
 * price at its start against now; without that, the price history the app has.
 */
export function benchmark(
  s: AutopilotStatus,
  now: number,
  btcTimes?: number[],
  btcCloses?: number[],
): Benchmark | null {
  const b = s.benchmark;
  if (b && b.returnPct != null && Number.isFinite(b.returnPct)) {
    const edge = b.excessPct != null && Number.isFinite(b.excessPct) ? b.excessPct : s.pnlPct - b.returnPct;
    return { btcPct: b.returnPct, runPct: b.returnPct + edge, edgePct: edge, approximate: b.fromMs != null, label: benchLabel(b.symbol) };
  }
  if (b && b.symbol !== "BTC/USD") return null;
  if (s.btcReturnPct != null && Number.isFinite(s.btcReturnPct)) {
    return { btcPct: s.btcReturnPct, runPct: s.pnlPct, edgePct: s.pnlPct - s.btcReturnPct, approximate: false };
  }
  const c = compareWithHold(curve(s, now), btcTimes, btcCloses, s.startedMs, s.stoppedMs ?? now);
  if (!c) return null;
  return { btcPct: c.holdPct, runPct: c.runPct, edgePct: c.runPct - c.holdPct, approximate: c.partial };
}

/** "Ahead of Bitcoin by 1.20 points", in words a beginner can read. */
export function benchmarkLine(b: Benchmark): string {
  const btc = `Holding ${b.label ?? "Bitcoin"} would have made ${signedPctText(b.btcPct)}`;
  const d = direction(b.edgePct, 0.005);
  const gap = `${Math.abs(b.edgePct).toFixed(2)} points`;
  const verdict = d === "up" ? `ahead by ${gap}` : d === "down" ? `behind by ${gap}` : "level with it";
  return `${btc}; this is ${verdict}${b.approximate ? " (over the part the price history covers)" : ""}.`;
}

/**
 * The autopilot an order was for: the book the order names, or, for an
 * order from an older engine, the autopilot that ran its strategy then.
 */
export function autopilotOf(order: Order, list: AutopilotStatus[]): AutopilotStatus | undefined {
  if (order.book) return list.find((s) => s.config.id === order.book);
  return list.find(
    (s) =>
      order.ts >= s.startedMs &&
      (s.stoppedMs == null || order.ts <= s.stoppedMs + 60_000) &&
      (s.bySleeve.some((b) => b.strategyId === order.strategyId) ||
        s.config.sleeves.some((c) => c.strategyId === order.strategyId)),
  );
}

/** Midnight UTC of the day `now` falls on. */
export function startOfUtcDay(now: number): number {
  const d = new Date(now);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

function filled(o: Order): boolean {
  return (o.status === "filled" || o.status === "partial") && o.filledQty > 0;
}

/** Orders it got filled since midnight UTC. */
export function tradesToday(s: AutopilotStatus, orders: Order[], now: number): number {
  const from = Math.max(startOfUtcDay(now), s.startedMs);
  return orders.filter((o) => filled(o) && o.ts >= from && autopilotOf(o, [s]) === s).length;
}

export type FillBadge = { label: string; tone: "cyan" | "purple" | "red" };

/** Where the fill happened, said plainly. */
export function routeBadge(route: FillRoute | undefined, venue: Order["venue"]): FillBadge {
  switch (route) {
    case "live":
      return { label: "real money", tone: "red" };
    case "demo":
      return { label: venue === "alpaca" ? "demo, Alpaca paper" : "demo", tone: "cyan" };
    default:
      return { label: "paper, simulated", tone: "purple" };
  }
}

export interface FillRow {
  id: string;
  ts: number;
  coin: string;
  side: Order["side"];
  qty: number;
  price: number;
  /** Dollars; null when not known yet. */
  fee: number | null;
  /** Why the fee is missing, when it is. */
  feeNote: string | null;
  /** A market order takes liquidity; a limit order may or may not. */
  liquidity: "maker" | "taker" | null;
  badge: FillBadge;
  autopilot: string | null;
}

/** The latest fills, newest first, from the autopilots' strategies when there are any. */
export function fillRows(orders: Order[], markets: Market[], list: AutopilotStatus[], limit = 20): FillRow[] {
  const symbol = new Map(markets.map((m) => [m.id, m.symbol]));
  const ownFills = orders.filter((o) => filled(o) && (list.length === 0 || autopilotOf(o, list)));
  return ownFills
    .sort((a, b) => b.ts - a.ts)
    .slice(0, limit)
    .map((o) => {
      const sym = symbol.get(o.marketId) ?? o.marketId.split(":").pop() ?? o.marketId;
      const alpacaCrypto = o.venue === "alpaca" && sym.includes("/");
      const fee = o.fee != null && Number.isFinite(o.fee) ? o.fee : null;
      return {
        id: o.id,
        ts: o.ts,
        coin: coinOf(sym),
        side: o.side,
        qty: o.filledQty,
        price: o.avgFillPrice ?? o.limitPrice ?? 0,
        fee,
        feeNote: fee == null ? (alpacaCrypto && o.route !== "paper" ? "posted end of day" : "not reported") : null,
        liquidity: o.type === "market" ? "taker" : null,
        badge: routeBadge(o.route, o.venue),
        autopilot: autopilotOf(o, list)?.config.name ?? null,
      };
    });
}

export interface ForwardSummary {
  generatedMs: number;
  verdict: string;
  total: number;
  onTrack: number;
  ahead: number;
  watch: number;
  early: number;
  /** The rows worth a line each: autopilots first, then the paper books. */
  rows: ForwardRow[];
}

/** The daily forward report in brief, for the simple view. */
export function forwardSummary(r: ForwardReport | null | undefined): ForwardSummary | null {
  if (!r) return null;
  const rows = [...(r.autopilots ?? []), ...(r.books ?? [])];
  const count = (st: string) => rows.filter((x) => x.status === st).length;
  return {
    generatedMs: r.generatedMs,
    verdict: r.verdict,
    total: rows.length,
    onTrack: count("on_track"),
    ahead: count("ahead"),
    watch: count("watch"),
    early: count("early"),
    rows,
  };
}

/**
 * Plus and minus colours. Pythia always draws on its own dark surfaces,
 * whatever the system theme, so these are picked for those: each reads at
 * WCAG AA (4.5:1) or better on the card and on the raised surface, which
 * `practice.test.ts` checks. An arrow and a sign go with every colour.
 */
export const PLUS_MINUS = {
  up: "#4ade80",
  down: "#f87171",
  flat: "#9a9ab2",
} as const;

/** WCAG contrast ratio of two `#rrggbb` colours. */
export function contrastRatio(a: string, b: string): number {
  const lum = (hex: string) => {
    const n = parseInt(hex.slice(1), 16);
    const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}
