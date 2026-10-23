// The Lab page's pump.fun section (pythia-core labview_pumpfun.rs, GET
// /api/lab/pumpfun): the real-time study's readiness per strategy and its
// shadow books (reports/pumpfun_rt/latest.json), the measured execution of
// the live orders (execution.json) and the pipeline strategies' paper books
// of the last seven days (paper/pumpfun_rt/ledger.csv). Paper only, read only.

import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";
import type { PumpfunDist } from "./pumpfunLive";
import type { StudyView } from "./researchView";

/** One strategy's readiness for live, as the study writes it (snake_case). */
export interface PumpfunReadiness {
  days?: number;
  days_ok?: boolean;
  trades?: number;
  trades_ok?: boolean;
  mean?: number | null;
  mean_clean?: number | null;
  positive_ok?: boolean;
  gates_ok?: boolean;
  shadow_days?: number;
  shadow_trades?: number;
  shadow_mean?: number | null;
  shadow_ok?: boolean;
  ready?: boolean;
}

/** A shadow book: the strategy run on the live stream by the study's fill model. */
export interface PumpfunShadow {
  n?: number;
  mean?: number | null;
  pnl_sol?: number | null;
  days?: number;
  first?: string;
  last?: string;
}

/** execution.json as the study writes it. */
export interface PumpfunExecutionFile {
  updated_ms?: number;
  fills?: number;
  buys?: number;
  sells?: number;
  failed?: number;
  lat_buy_ms?: PumpfunDist;
  slip_buy?: PumpfunDist;
  paper_slip?: PumpfunDist;
  verdict?: string;
}

export interface PumpfunBookDay {
  day: string;
  entries: number;
  mean: number | null;
  pnlSol: number;
}

export interface PumpfunEntry {
  exitMs: number;
  symbol: string | null;
  exitWhy: string | null;
  ret: number | null;
  pnlSol: number;
}

export interface PumpfunBook {
  rule: string;
  entries: number;
  wins: number;
  mean: number | null;
  pnlSol: number;
  lastMs: number | null;
  /** Newest first. */
  days: PumpfunBookDay[];
  /** [exit ms, running P&L in SOL], oldest first. */
  curve: [number, number][];
  /** Newest first. */
  recent: PumpfunEntry[];
}

export interface PumpfunLab {
  found: boolean;
  updatedMs: number | null;
  status: string | null;
  headline: string | null;
  caveat: string | null;
  pick: string | null;
  readiness: Record<string, PumpfunReadiness> | null;
  shadow: Record<string, PumpfunShadow> | null;
  execution: PumpfunExecutionFile | null;
  books: PumpfunBook[];
  bookDays: number;
  ledgerMs: number | null;
}

/** The pump.fun lab from the connected server. The desktop app has no reader for it yet. */
export async function labPumpfun(): Promise<PumpfunLab> {
  if (liveMode() !== "server") throw new Error("The pump.fun lab is read by the connected server.");
  const r = await fetch(`${serverUrl()}/api/lab/pumpfun`);
  if (!r.ok) throw new Error(`backend answered ${r.status}`);
  return (await r.json()) as PumpfunLab;
}

export interface StrategyRow {
  rule: string;
  ready: boolean;
  /** The checks the study applies before live, in order, each passed or not. */
  checks: { label: string; ok: boolean }[];
  readiness: PumpfunReadiness | null;
  shadow: PumpfunShadow | null;
  book: PumpfunBook | null;
}

/**
 * One row per pipeline strategy: its readiness, its shadow book and its paper
 * book of the last days. Ready first, then the book with the newest entry,
 * then by name; a strategy with a book but no readiness row still shows.
 */
export function strategyRows(lab: PumpfunLab | null | undefined): StrategyRow[] {
  if (!lab) return [];
  const books = new Map(lab.books.map((b) => [b.rule, b]));
  const names = [...new Set([...Object.keys(lab.readiness ?? {}), ...lab.books.map((b) => b.rule)])];
  return names
    .map((rule) => {
      const r = lab.readiness?.[rule] ?? null;
      return {
        rule,
        ready: !!r?.ready,
        checks: r
          ? [
              { label: "days", ok: !!r.days_ok },
              { label: "trades", ok: !!r.trades_ok },
              { label: "positive", ok: !!r.positive_ok },
              { label: "gates", ok: !!r.gates_ok },
              { label: "shadow", ok: !!r.shadow_ok },
            ]
          : [],
        readiness: r,
        shadow: lab.shadow?.[rule] ?? null,
        book: books.get(rule) ?? null,
      };
    })
    .sort((a, b) => Number(b.ready) - Number(a.ready) || (b.book?.lastMs ?? 0) - (a.book?.lastMs ?? 0) || a.rule.localeCompare(b.rule));
}

/** The newest pump.fun studies (results/pumpfun_*.md) with their verdict lines, newest first. */
export function pumpfunStudies(studies: StudyView[], limit = 8): StudyView[] {
  return studies.filter((s) => (s.file ?? "").startsWith("pumpfun") || /pumpfun/.test(s.code)).slice(0, limit);
}

/** A share as a signed percent: 0.041 -> "+4.1 %"; "n/a" without one. */
export function sharePct(v: number | null | undefined, dp = 1): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  return `${v > 0 ? "+" : v < 0 ? "-" : ""}${Math.abs(v * 100).toFixed(dp)} %`;
}
