// The Real money page's arithmetic: everything that trades real money added
// up in euro. The pump.fun bot reports SOL (euro at today's SOL price, as its
// own page does), the live autopilots report US dollars (euro at Kraken's
// EUR/USD, read by the backend). Pure functions, so the totals are tested.

import { isDemoLine } from "./pagekit/journal";
import type { PumpfunTrade, SolEur } from "./pumpfunLive";
import type { AutopilotStatus, JournalEntry } from "./types";

/** A P&L line: [epoch ms, euro], oldest first. */
export type EurLine = [number, number][];

/**
 * The pump.fun bot's running P&L in euro over the trades the service keeps
 * (its newest ones). The line is lifted so it ends at the bot's total since
 * its first live trade; the trades before the kept ones sit at its start.
 */
export function pumpfunLine(trades: readonly PumpfunTrade[], totalSol: number | null | undefined, rate: SolEur | null | undefined): EurLine {
  if (!rate || !(rate.price > 0)) return [];
  const closed = trades.filter((t) => t.exitMs != null && Number.isFinite(t.pnlSol ?? NaN)).sort((a, b) => (a.exitMs ?? 0) - (b.exitMs ?? 0));
  if (!closed.length) return [];
  const kept = closed.reduce((a, t) => a + (t.pnlSol ?? 0), 0);
  let run = totalSol != null && Number.isFinite(totalSol) ? totalSol - kept : 0;
  const out: EurLine = [[(closed[0].exitMs ?? 0) - 1, run * rate.price]];
  for (const t of closed) {
    run += t.pnlSol ?? 0;
    out.push([t.exitMs ?? 0, run * rate.price]);
  }
  return out;
}

/** US dollars in euro at `eurUsd` (dollars per euro); null without a rate. */
export function usdToEur(usd: number, eurUsd: SolEur | null | undefined): number | null {
  return eurUsd && eurUsd.price > 0 && Number.isFinite(usd) ? usd / eurUsd.price : null;
}

/** One autopilot's P&L in euro over its equity history (equity less what it was given). */
export function autopilotLine(s: Pick<AutopilotStatus, "history" | "startCapital">, eurUsd: SolEur | null | undefined): EurLine {
  if (!eurUsd || !(eurUsd.price > 0)) return [];
  return s.history.filter(([t, e]) => Number.isFinite(t) && Number.isFinite(e)).map(([t, e]) => [t, (e - s.startCapital) / eurUsd.price]);
}

/**
 * Several P&L lines as one: at every time any of them moves, the sum of each
 * line's last value at or before it (nothing before its first point, its last
 * value after its end: a stopped autopilot keeps what it made).
 */
export function combineLines(lines: readonly EurLine[]): EurLine {
  const live = lines.filter((l) => l.length > 0);
  const times = [...new Set(live.flatMap((l) => l.map((p) => p[0])))].sort((a, b) => a - b);
  const at = live.map(() => -1);
  return times.map((t) => {
    let sum = 0;
    live.forEach((l, i) => {
      while (at[i] + 1 < l.length && l[at[i] + 1][0] <= t) at[i] += 1;
      if (at[i] >= 0) sum += l[at[i]][1];
    });
    return [t, sum] as [number, number];
  });
}

export interface RealMoneyTotal {
  /** Euro P&L of everything that could be converted. */
  eur: number;
  pumpfunEur: number | null;
  autopilotsEur: number | null;
  /** Dollars of the autopilots, shown when no EUR/USD rate could be read. */
  autopilotsUsd: number;
  /** What is missing from the euro figure, in plain words. */
  missing: string[];
}

/** The real-money P&L in euro: the pump.fun bot since its first live trade plus every live autopilot. */
export function realMoneyTotal(
  pumpfunSol: number | null | undefined,
  rate: SolEur | null | undefined,
  autopilots: readonly Pick<AutopilotStatus, "pnl">[],
  eurUsd: SolEur | null | undefined,
): RealMoneyTotal {
  const missing: string[] = [];
  const pumpfunEur = pumpfunSol == null ? null : rate && rate.price > 0 ? pumpfunSol * rate.price : null;
  if (pumpfunSol != null && pumpfunEur == null) missing.push("pump.fun (no SOL/EUR price)");
  const autopilotsUsd = autopilots.reduce((a, s) => a + (Number.isFinite(s.pnl) ? s.pnl : 0), 0);
  const autopilotsEur = autopilots.length ? usdToEur(autopilotsUsd, eurUsd) : null;
  if (autopilots.length && autopilotsEur == null) missing.push("the autopilots (no EUR/USD rate)");
  return { eur: (pumpfunEur ?? 0) + (autopilotsEur ?? 0), pumpfunEur, autopilotsEur, autopilotsUsd, missing };
}

/** The engine journal's real-money fills (Kraken, Alpaca), newest first as they come; demo lines are not real money. */
export function liveFills(journal: readonly JournalEntry[], limit = 50): JournalEntry[] {
  return journal.filter((e) => e.kind === "fill" && e.mode === "live" && !isDemoLine(e)).slice(0, limit);
}

/** Euro in the reader's locale, "+12,34 €" with `signed`. */
export function euro(v: number | null | undefined, signed = false): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const x = Math.abs(v) < 0.005 ? 0 : v;
  const s = Math.abs(x).toLocaleString(undefined, { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${signed ? (x > 0 ? "+" : x < 0 ? "-" : "") : x < 0 ? "-" : ""}${s}`;
}
