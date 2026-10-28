// Fortschritt (GET /api/lab/progress): how far Pythia is from real money, for
// the owner's phone. Written every 15 minutes by the lab job `progress`
// (research/lab/lab/ops/progress.py) from the lab's own reports: the readiness
// ladder, P3's 10 EUR pump.fun books, paper minus live, the tsmom books' gate 7
// and the newest weekly page. Every section carries the time of its report and
// the age after which it is stale; the age is measured here against this
// device's clock, so a number from a job that stopped never looks current.
// Read only: nothing here trades or changes a setting.

import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";

/** The page reads the file again every 2 minutes while it is shown. */
export const PROGRESS_POLL_MS = 120_000;

export interface Source {
  file: string;
  found: boolean;
  atMs: number | null;
  staleMs: number;
}

export interface LadderRow {
  id: string;
  name: string;
  step: number;
  stepName: string;
  next: string;
  tainted: number;
}

export interface Ladder extends Source {
  topStep: number | null;
  topName: string | null;
  counts: { step: number; name: string; n: number }[];
  nTrials: number | null;
  sr0: number | null;
  rows: LadderRow[];
}

export interface GateItem {
  id: string;
  label: string;
  ok: boolean;
}

export interface TenBook {
  book: string;
  strategy: string;
  started: boolean;
  sol: number | null;
  eur: number | null;
  trades: number;
  mean: number | null;
  band: [number | null, number | null] | null;
  days: number | null;
  needDays: number;
  canPay: boolean;
  pass: boolean;
  gate: GateItem[];
}

export interface Ten extends Source {
  started: boolean;
  books: TenBook[];
}

export interface Gap extends Source {
  calibration: {
    rule: string;
    pairs: number;
    live: number;
    paper: number;
    days: number | null;
    medianPts: number | null;
    meanPts: number | null;
    verdict: string | null;
  } | null;
  p2: { pts: number | null; gatePts: number; pass: boolean } | null;
}

export interface Gate7Book {
  book: string;
  since: string;
  days: number;
  rebalances: number;
  needDays: number;
  needRebalances: number;
  ready: boolean;
  paperPct: number | null;
  backtestPct: number | null;
}

export interface Gate7 extends Source {
  books: Gate7Book[];
}

export interface Weekly extends Source {
  lines: string[];
}

export interface Progress {
  found: boolean;
  updatedMs: number | null;
  ladder: Ladder;
  ten: Ten;
  gap: Gap;
  gate7: Gate7;
  weekly: Weekly;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const obj = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

function source(o: Record<string, unknown>, file: string): Source {
  return { file: str(o.file) || file, found: o.found === true, atMs: num(o.at_ms), staleMs: num(o.stale_ms) ?? 36 * 3_600_000 };
}

export function parseProgress(raw: unknown): Progress {
  const o = obj(raw);
  const l = obj(o.ladder);
  const steps = obj(l.steps);
  const counts = Object.entries(obj(l.counts))
    .map(([k, v]) => ({ step: Number(k), name: str(steps[k]) || k, n: num(v) ?? 0 }))
    .filter((c) => Number.isFinite(c.step))
    .sort((a, b) => b.step - a.step);
  const rows = arr(l.rows)
    .map(obj)
    .filter((r) => str(r.name))
    .map((r) => ({ id: str(r.id), name: str(r.name), step: num(r.step) ?? 0, stepName: str(r.step_name), next: str(r.next), tainted: num(r.tainted) ?? 0 }));
  const t = obj(o.ten);
  const books = arr(t.books)
    .map(obj)
    .filter((b) => str(b.book))
    .map((b): TenBook => {
      const band = arr(b.band);
      return {
        book: str(b.book),
        strategy: str(b.strategy),
        started: b.started === true,
        sol: num(b.sol),
        eur: num(b.eur),
        trades: num(b.trades) ?? 0,
        mean: num(b.mean),
        band: band.length === 2 ? [num(band[0]), num(band[1])] : null,
        days: num(b.days),
        needDays: num(b.need_days) ?? 30,
        canPay: b.can_pay !== false,
        pass: b.pass === true,
        gate: arr(b.gate).map(obj).map((g) => ({ id: str(g.id), label: str(g.label) || str(g.id), ok: g.ok === true })),
      };
    });
  const g = obj(o.gap);
  const c = g.calibration ? obj(g.calibration) : null;
  const p2 = g.p2 ? obj(g.p2) : null;
  const g7 = obj(o.gate7);
  const w = obj(o.weekly);
  return {
    found: o.found === true,
    updatedMs: num(o.updated_ms),
    ladder: {
      ...source(l, "reports/ladder/latest.json"),
      topStep: num(l.top_step),
      topName: str(l.top_name) || null,
      counts,
      nTrials: num(l.n_trials),
      sr0: num(l.sr0_annual),
      rows,
    },
    ten: { ...source(t, "reports/pumpfun_rt/realistic.json"), started: t.started === true && books.some((b) => b.started), books },
    gap: {
      ...source(g, "reports/pumpfun_rt/realistic.json"),
      calibration: c
        ? {
            rule: str(c.rule),
            pairs: num(c.pairs) ?? 0,
            live: num(c.live) ?? 0,
            paper: num(c.paper) ?? 0,
            days: num(c.days),
            medianPts: num(c.median_pts),
            meanPts: num(c.mean_pts),
            verdict: str(c.verdict) || null,
          }
        : null,
      p2: p2 ? { pts: num(p2.pts), gatePts: num(p2.gate_pts) ?? 2, pass: p2.pass === true } : null,
    },
    gate7: {
      ...source(g7, "reports/paper_review/latest.json"),
      books: arr(g7.books)
        .map(obj)
        .filter((b) => str(b.book))
        .map((b) => ({
          book: str(b.book),
          since: str(b.since),
          days: num(b.days) ?? 0,
          rebalances: num(b.rebalances) ?? 0,
          needDays: num(b.need_days) ?? 30,
          needRebalances: num(b.need_rebalances) ?? 30,
          ready: b.ready === true,
          paperPct: num(b.paper_pct),
          backtestPct: num(b.backtest_pct),
        })),
    },
    weekly: { ...source(w, "reports/weekly/latest.md"), lines: arr(w.lines).map(str).filter(Boolean).slice(0, 12) },
  };
}

export function canReadProgress(): boolean {
  return liveMode() === "server";
}

/** GET only: the page never sends anything else. */
export async function fetchProgress(): Promise<Progress> {
  if (!canReadProgress()) throw new Error("Fortschritt braucht den Server.");
  const r = await fetch(`${serverUrl()}/api/lab/progress`, { method: "GET", cache: "no-store" });
  if (!r.ok) throw new Error(`Der Server antwortete ${r.status}`);
  return parseProgress(await r.json());
}

// ── the age of a number ──

export type Freshness = "fresh" | "stale" | "unknown" | "missing";

/** Missing: no report. Unknown: a report without a time. Stale: older than its section allows. */
export function freshness(s: Pick<Source, "found" | "atMs" | "staleMs">, nowMs: number): Freshness {
  if (!s.found) return "missing";
  if (s.atMs == null) return "unknown";
  return nowMs - s.atMs > s.staleMs ? "stale" : "fresh";
}

/** "vor 5 Min.", "vor 3 Std.", "vor 2 Tagen". */
export function ageText(atMs: number | null, nowMs: number): string {
  if (atMs == null) return "Zeit unbekannt";
  const s = Math.max(0, (nowMs - atMs) / 1000);
  if (s < 60) return "gerade eben";
  if (s < 3600) return `vor ${Math.floor(s / 60)} Min.`;
  if (s < 86_400) return `vor ${Math.floor(s / 3600)} Std.`;
  const d = Math.floor(s / 86_400);
  return d === 1 ? "vor 1 Tag" : `vor ${d} Tagen`;
}

// ── German numbers ──

export function de(v: number | null | undefined, dp = 1, sign = false): string {
  if (v == null || !Number.isFinite(v)) return "k. A.";
  const s = Math.abs(v).toLocaleString("de-DE", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return `${v < 0 ? "-" : sign && v > 0 ? "+" : ""}${s}`;
}

/** A fraction as percent: 0.021 is "+2,1 %". */
export function pctText(frac: number | null | undefined, dp = 1): string {
  return frac == null ? "k. A." : `${de(frac * 100, dp, true)} %`;
}

/** The gate's conditions not met yet, in words; empty when it passes. */
export function missingGate(b: TenBook): string[] {
  return b.gate.filter((g) => !g.ok).map((g) => g.label);
}

/** Days to go to a gate of `need` days, never below 0. */
export function daysToGo(days: number | null, need: number): number {
  return Math.max(0, Math.ceil(need - (days ?? 0)));
}

/** The share of a gate reached, 0 to 1, for the bar. */
export function share(have: number | null, need: number): number {
  return need > 0 ? Math.max(0, Math.min(1, (have ?? 0) / need)) : 0;
}
