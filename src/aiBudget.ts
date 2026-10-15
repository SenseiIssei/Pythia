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

export type Tone = "up" | "down" | "plain";

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

/** The LLM's edge over a reference in Brier points (negative is better), with its t, in words. */
export function edgeWords(v: { diff: number | null; t: number | null }, name: string): { text: string; tone: Tone } {
  if (v.diff === null) return { text: `no comparison with ${name} yet`, tone: "plain" };
  const t = v.t === null ? "" : `, t ${v.t.toFixed(1)}`;
  const pts = `${v.diff > 0 ? "+" : ""}${(v.diff * 100).toFixed(2)} pts${t}`;
  if (v.t !== null && v.t < -2) return { text: `better than ${name} (${pts})`, tone: "up" };
  if (v.t !== null && v.t > 2) return { text: `worse than ${name} (${pts})`, tone: "down" };
  return { text: `no measurable difference to ${name} (${pts})`, tone: "plain" };
}
