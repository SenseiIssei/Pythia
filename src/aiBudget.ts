// The Claude API budget (pythia-core/src/ai_budget.rs) and the lab's AI reports
// (lab.ai.brief, lab.ai.score, lab.ai.weekly). The budget is the hard gate in
// front of every paid model call; the reports are shadow forecasts, scored and
// never traded.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";

export interface AiCaps {
  lifetimeUsd: number;
  monthlyUsd: number;
  dailyUsd: number;
}

export interface AiSpend {
  lifetimeUsd: number;
  monthUsd: number;
  todayUsd: number;
  calls: number;
  callsToday: number;
  month: string;
  day: string;
  inFlightUsd: number;
}

export interface AiLedgerEntry {
  ts: number;
  source: string;
  job: string;
  model: string;
  servedBy?: string;
  inputTokens: number;
  outputTokens: number;
  cacheWriteTokens: number;
  cacheReadTokens: number;
  batch: boolean;
  costUsd: number;
  ok: boolean;
}

/** One job's spend on one UTC day, from the ledger. */
export interface JobDaySpend {
  /** YYYY-MM-DD, UTC. */
  day: string;
  /** brief, critic, director, ask, weekly, overlay, signal, ... */
  job: string;
  usd: number;
  calls: number;
}

export interface AiBudget {
  caps: AiCaps;
  defaults: AiCaps;
  spend: AiSpend;
  leftLifetimeUsd: number;
  leftMonthUsd: number;
  leftTodayUsd: number;
  /** Why a cheap call would be refused right now, if it would. */
  refusing: string | null;
  recent: AiLedgerEntry[];
  /** Spend per job and day over the last 14 days (an older engine leaves it out). */
  byJobDay?: JobDaySpend[];
  pricesAsOf: string;
  pricesEstimate: boolean;
  /** Kept on disk (survives restarts) or in memory only. */
  persisted: boolean;
  keyConfigured: boolean;
  models: { routine: string; review: string; deep: string };
}

export interface SourceScore {
  n: number;
  brier: number | null;
  logloss: number | null;
  hitRate: number | null;
  meanP: number | null;
}

export interface AiScores {
  generated_ms: number;
  horizon_days: number;
  predictions: number;
  resolved: number;
  pending: number;
  models: string[];
  sources: { llm: SourceScore; base: SourceScore; momentum: SourceScore };
  vs: { base: { n: number; diff: number | null; t: number | null }; momentum: { n: number; diff: number | null; t: number | null } };
  verdict: string;
  reliability: { bin: string; n: number; predicted: number; observed: number }[];
  by_coin: { coin: string; n: number; llm: number | null; base: number | null; momentum: number | null }[];
  references: { base: string; momentum: string };
}

export interface BriefPrediction {
  coin: string;
  p_llm: number;
  p_base: number;
  p_momentum: number;
  reason: string;
  ref_day: string;
  resolve_day: string;
}

export interface AiBrief {
  date: string;
  generated_ms: number;
  model: string | null;
  summary: string[];
  predictions: BriefPrediction[];
  problems: string[];
  costUsd: number | null;
  batch: boolean;
}

export interface AiReport {
  brief: AiBrief | null;
  scores: AiScores | null;
  weekly: { markdown: string; updatedMs: number | null } | null;
}

const UNAVAILABLE = "The AI budget lives in the desktop app or a connected backend.";

async function backend<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${serverUrl()}${path}`, init);
  if (!r.ok) {
    const text = await r.text();
    let msg = text;
    try {
      msg = (JSON.parse(text) as { error?: string }).error ?? text;
    } catch {
      /* plain text */
    }
    throw new Error(msg || `HTTP ${r.status}`);
  }
  return (await r.json()) as T;
}

export async function aiBudget(): Promise<AiBudget> {
  switch (liveMode()) {
    case "native":
      return invoke<AiBudget>("ai_budget");
    case "server":
      return backend<AiBudget>("/api/ai/budget");
    default:
      throw new Error(UNAVAILABLE);
  }
}

export async function setAiBudget(caps: Partial<AiCaps>): Promise<AiBudget> {
  switch (liveMode()) {
    case "native":
      return invoke<AiBudget>("set_ai_budget", {
        lifetimeUsd: caps.lifetimeUsd ?? null,
        monthlyUsd: caps.monthlyUsd ?? null,
        dailyUsd: caps.dailyUsd ?? null,
      });
    case "server":
      return backend<AiBudget>("/api/ai/budget", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(caps),
      });
    default:
      throw new Error(UNAVAILABLE);
  }
}

export async function aiReport(): Promise<AiReport> {
  switch (liveMode()) {
    case "native":
      return invoke<AiReport>("ai_report");
    case "server":
      return backend<AiReport>("/api/ai/report");
    default:
      throw new Error(UNAVAILABLE);
  }
}

// ── pure helpers (tested) ────────────────────────────────────────────────────

/** The highest cap anyone can set, as the engine enforces it. */
export const MAX_CAP_USD = 1000;

/** Share of a cap used, 0..1. A cap of zero is fully used: it switches calls off. */
export function usedShare(spent: number, cap: number): number {
  if (!(cap > 0)) return 1;
  return Math.min(1, Math.max(0, spent / cap));
}

/** A cap typed into a field: the number, or why it is not one. */
export function parseCap(text: string): number | string {
  const t = text.trim().replace(/^\$/, "").replace(",", ".");
  if (t === "") return "Enter an amount in USD.";
  const v = Number(t);
  if (!Number.isFinite(v)) return "Not a number.";
  if (v < 0) return "A cap cannot be negative.";
  if (v > MAX_CAP_USD) return `At most $${MAX_CAP_USD}.`;
  return Math.round(v * 100) / 100;
}

/** A note when the caps are set so one can never be reached, which is allowed but worth saying. */
export function capsNote(c: AiCaps): string | null {
  if (c.dailyUsd === 0 || c.monthlyUsd === 0 || c.lifetimeUsd === 0) return "A cap of $0 switches every Claude call off.";
  if (c.monthlyUsd > c.lifetimeUsd) return "The monthly cap is above the lifetime cap, so the lifetime cap is what stops calls.";
  if (c.dailyUsd > c.monthlyUsd) return "The daily cap is above the monthly cap, so the monthly cap is what stops calls.";
  return null;
}

/** US dollars with enough digits for cents and for fractions of a cent. */
export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  if (v !== 0 && Math.abs(v) < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

export interface JobSpendRow {
  job: string;
  /** USD per day, in the order of `days`. */
  perDay: number[];
  calls: number;
  total: number;
}

export interface JobSpendTable {
  /** YYYY-MM-DD, oldest first, ending today. */
  days: string[];
  rows: JobSpendRow[];
  /** USD per day over every job. */
  dayTotals: number[];
  total: number;
}

/** The YYYY-MM-DD `back` days before `day` (UTC). */
function dayBefore(day: string, back: number): string {
  const t = Date.parse(`${day}T00:00:00Z`) - back * 86_400_000;
  return new Date(t).toISOString().slice(0, 10);
}

/**
 * Spend per job and day for the last `n` days ending `today`: one row per job,
 * dearest first. A job's direct retry ("brief-direct") counts as the job.
 */
export function jobSpendTable(entries: JobDaySpend[] | undefined, today: string, n = 7): JobSpendTable {
  const days = Array.from({ length: n }, (_, i) => dayBefore(today, n - 1 - i));
  const at = new Map(days.map((d, i) => [d, i]));
  const byJob = new Map<string, JobSpendRow>();
  for (const e of entries ?? []) {
    const i = at.get(e.day);
    if (i === undefined || !Number.isFinite(e.usd)) continue;
    const job = (e.job || "other").replace(/-direct$/, "");
    const row = byJob.get(job) ?? { job, perDay: days.map(() => 0), calls: 0, total: 0 };
    row.perDay[i] += e.usd;
    row.calls += e.calls;
    row.total += e.usd;
    byJob.set(job, row);
  }
  const rows = [...byJob.values()].sort((a, b) => b.total - a.total || a.job.localeCompare(b.job));
  const dayTotals = days.map((_, i) => rows.reduce((s, r) => s + r.perDay[i], 0));
  return { days, rows, dayTotals, total: rows.reduce((s, r) => s + r.total, 0) };
}

/** What each job is, in a few words, for the spend table. */
export const JOB_LABELS: Record<string, string> = {
  brief: "Daily brief",
  critic: "Strategy critic",
  director: "Research director",
  weekly: "Weekly review",
  ask: "Telegram questions",
  overlay: "AI overlay",
  signal: "Signals",
};

export interface VsRow {
  key: "llm" | "momentum" | "base";
  label: string;
  sub: string;
  brier: number | null;
  logloss: number | null;
  hitRate: number | null;
  n: number;
  /** Lowest Brier score of the three: the best calibrated so far. */
  best: boolean;
}

/** "LLM vs our models": the brief's calls next to the two references, best Brier marked. */
export function vsRows(s: AiScores): VsRow[] {
  const model = s.models.length ? s.models.join(", ") : "Claude";
  const rows: VsRow[] = [
    { key: "llm", label: "LLM (daily brief)", sub: model, ...pick(s.sources.llm), best: false },
    { key: "momentum", label: "Momentum rule", sub: s.references.momentum, ...pick(s.sources.momentum), best: false },
    { key: "base", label: "Base rate", sub: s.references.base, ...pick(s.sources.base), best: false },
  ];
  const scored = rows.filter((r) => r.brier !== null && r.n > 0);
  if (scored.length) {
    const lo = Math.min(...scored.map((r) => r.brier as number));
    for (const r of rows) r.best = r.brier !== null && r.brier === lo;
  }
  return rows;
}

function pick(x: SourceScore): Pick<VsRow, "brier" | "logloss" | "hitRate" | "n"> {
  return { brier: x?.brier ?? null, logloss: x?.logloss ?? null, hitRate: x?.hitRate ?? null, n: x?.n ?? 0 };
}

/** The LLM's Brier score minus a reference's, in points of 0.01 (negative: the LLM is better). */
export function brierGap(v: { diff: number | null }): string | null {
  if (v.diff === null || !Number.isFinite(v.diff)) return null;
  return `${v.diff > 0 ? "+" : ""}${(v.diff * 100).toFixed(2)} pts`;
}
