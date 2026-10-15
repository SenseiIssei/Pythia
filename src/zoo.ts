// The model zoo: every model the lab keeps, its score against its baseline over
// time, last retrain, drift and who uses it. Written daily by the lab
// (`python -m lab.models.train`, reports/models/latest.json), served by the
// engine at GET /api/ml/zoo. Read-only in every runtime.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";
import type { ChipTone } from "./design";

export type ZooStatusWord =
  | "in use"
  | "shadow"
  | "failed its gate"
  | "waiting for data"
  | "never trained"
  | "retired"
  | "not on this machine"
  | "error";

export interface ScorePoint {
  label: string | null;
  from: string | null;
  model: number | null;
  baseline: number | null;
}

export interface ZooDecision {
  date: string | null;
  candidate: string | null;
  decision: string;
  challengerScore: number | null;
  championScore: number | null;
  why: string;
}

export interface ZooLive {
  rows: number;
  open: number;
  model: number | null;
  baseline: number | null;
  gainPct: number | null;
  winRate: number | null;
  since: string | null;
  weeks: { from: string | null; model: number | null; baseline: number | null; rows: number }[];
  error: string | null;
}

export interface ZooDrift {
  level: "stable" | "shift" | "drift" | "unknown" | string;
  why: string;
  features: { feature: string; psi: number; outsidePct: number; level: string }[];
}

export interface ZooModel {
  code: string;
  name: string;
  title: string;
  target: string;
  horizon: string;
  universe: string;
  metric: string;
  higherBetter: boolean;
  baseline: string;
  managedBy: string;
  shadowWhere: string;
  status: ZooStatusWord | string;
  statusDetail: string;
  everyDays: number;
  usedBy: string[];
  useRule: string;
  notes: string;
  results: string;
  lastRetrainMs: number | null;
  lastStatus?: string | null;
  nextDue: string | null;
  champion: { version: string; promotedMs: number | null; trainTo: string | null } | null;
  gate: { passed: boolean; why: string } | null;
  modelScore: number | null;
  baselineScore: number | null;
  gainPct: number | null;
  dmP: number | null;
  foldsWon: number | null;
  foldsTotal: number | null;
  history: ScorePoint[];
  decisions: ZooDecision[];
  live: ZooLive | null;
  drift: ZooDrift | null;
  extra: Record<string, unknown>;
}

export interface ZooStatus {
  generatedMs: number;
  generated: string;
  /** The lab feed header's one sentence; empty from older reports. */
  headline?: string;
  models: ZooModel[];
  alerts: string[];
}

/** The zoo's latest report, or null when the lab has not run it yet. */
export async function modelZoo(): Promise<ZooStatus | null> {
  switch (liveMode()) {
    case "native":
      return invoke<ZooStatus | null>("ml_zoo");
    case "server": {
      const r = await fetch(`${serverUrl()}/api/ml/zoo`);
      if (!r.ok) throw new Error(`backend answered ${r.status}`);
      return (await r.json()) as ZooStatus | null;
    }
    default:
      throw new Error("Models run in the desktop app or a connected backend.");
  }
}

export const STATUS_TONE: Record<string, ChipTone> = {
  "in use": "good",
  shadow: "accent",
  "failed its gate": "warn",
  "waiting for data": "neutral",
  "never trained": "neutral",
  retired: "neutral",
  "not on this machine": "neutral",
  error: "bad",
};

export function statusTone(s: string): ChipTone {
  return STATUS_TONE[s] ?? "neutral";
}

/** A status in the words the page uses. */
export function statusWord(s: string): string {
  if (s === "shadow") return "beats baseline, shadow";
  if (s === "failed its gate") return "does not beat baseline";
  return s;
}

/** Drift in words and colour, the engine's rules: outside the trained range is bad, a different spread is a note. */
export function driftChip(level: string | undefined): { word: string; tone: ChipTone } {
  if (level === "drift") return { word: "outside trained range", tone: "bad" };
  if (level === "shift") return { word: "different regime", tone: "accent" };
  if (level === "stable") return { word: "like training", tone: "good" };
  return { word: "not checked", tone: "neutral" };
}

/** Inputs outside the trained range, a failed retrain or a broken shadow score. */
export function needsAttention(m: ZooModel): boolean {
  return m.drift?.level === "drift" || m.status === "error" || m.lastStatus === "failed" || !!m.live?.error;
}

/**
 * Percent better than the baseline at each point (positive = the model is
 * better), whichever way the metric points. Points without both numbers are
 * left out.
 */
export function edgeSeries(points: { model: number | null; baseline: number | null }[], higherBetter: boolean): number[] {
  return edgePoints(points, higherBetter).map((p) => p.edge);
}

/** Like edgeSeries, keeping each point's label (a quarter, a week, a retrain date). */
export function edgePoints(
  points: { model: number | null; baseline: number | null; label?: string | null; from?: string | null }[],
  higherBetter: boolean,
): { label: string; edge: number }[] {
  const out: { label: string; edge: number }[] = [];
  for (const p of points) {
    if (p.model === null || p.baseline === null || !Number.isFinite(p.model) || !Number.isFinite(p.baseline)) continue;
    const label = p.label ?? p.from ?? "";
    if (higherBetter) {
      out.push({ label, edge: (p.model - p.baseline) * 100 });
    } else if (p.baseline !== 0) {
      out.push({ label, edge: ((p.baseline - p.model) / Math.abs(p.baseline)) * 100 });
    }
  }
  return out;
}

/** Share of points where the model beat its baseline, or null without points. */
export function winShare(points: { model: number | null; baseline: number | null }[], higherBetter: boolean): number | null {
  const e = edgeSeries(points, higherBetter);
  return e.length ? e.filter((x) => x > 0).length / e.length : null;
}

/**
 * The model's edge over its baseline out of sample, in percent (positive =
 * better), or null. For a higher-is-better metric (rank-IC) it is the gap in
 * points.
 */
export function edgeNow(m: ZooModel): number | null {
  if (m.higherBetter) {
    return m.modelScore !== null && m.baselineScore !== null ? (m.modelScore - m.baselineScore) * 100 : null;
  }
  return m.gainPct !== null && Number.isFinite(m.gainPct) ? m.gainPct : null;
}

/** A metric value at a precision that suits it. */
export function fmtScore(v: number | null | undefined, metric: string): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  if (metric === "mae") return `${v.toFixed(2)} bps`;
  return Math.abs(v) >= 1 ? v.toFixed(2) : v.toFixed(4);
}

/** A p-value a reader can scan: "< 0.001" below that. */
export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "n/a";
  return p < 0.001 ? "< 0.001" : p.toFixed(3);
}

/** What a metric measures, in plain words. */
export const METRIC_WORDS: Record<string, string> = {
  logloss: "log loss of the up-or-down probability",
  qlike: "QLIKE, the standard volatility forecast error",
  mae: "mean absolute error in bps",
  mse_z: "squared error of the correlation (Fisher z)",
  pinball: "pinball loss over the 10, 50 and 90 % quantiles",
  rank_ic: "rank correlation with the realised returns",
  sharpe: "Sharpe ratio",
};

/** Days since a timestamp, in words. */
export function ago(ms: number | null | undefined, now = Date.now()): string {
  if (!ms) return "never";
  const d = Math.floor((now - ms) / 86_400_000);
  return d <= 0 ? "today" : d === 1 ? "yesterday" : `${d} days ago`;
}
