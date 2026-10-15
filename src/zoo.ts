// The model zoo: every model the lab keeps, its score against its baseline over
// time, last retrain, drift and who uses it. Written daily by the lab
// (`python -m lab.models.train`, reports/model_zoo/latest.json), served by the
// engine at GET /api/ml/zoo. Read-only in every runtime.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";
import type { Tone } from "./components/ui";

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

export const STATUS_TONE: Record<string, Tone> = {
  "in use": "green",
  shadow: "cyan",
  "failed its gate": "amber",
  "waiting for data": "neutral",
  "never trained": "neutral",
  retired: "neutral",
  "not on this machine": "neutral",
  error: "red",
};

export function statusTone(s: string): Tone {
  return STATUS_TONE[s] ?? "neutral";
}

export function driftTone(level: string | undefined): Tone {
  return level === "drift" ? "red" : level === "shift" ? "purple" : level === "stable" ? "green" : "neutral";
}

/**
 * Percent better than the baseline at each point (positive = the model is
 * better), whichever way the metric points. Points without both numbers are
 * left out.
 */
export function edgeSeries(points: { model: number | null; baseline: number | null }[], higherBetter: boolean): number[] {
  const out: number[] = [];
  for (const p of points) {
    if (p.model === null || p.baseline === null || !Number.isFinite(p.model) || !Number.isFinite(p.baseline)) continue;
    if (higherBetter) {
      out.push((p.model - p.baseline) * 100);
    } else if (p.baseline !== 0) {
      out.push(((p.baseline - p.model) / Math.abs(p.baseline)) * 100);
    }
  }
  return out;
}

/** Share of points where the model beat its baseline, or null without points. */
export function winShare(points: { model: number | null; baseline: number | null }[], higherBetter: boolean): number | null {
  const e = edgeSeries(points, higherBetter);
  return e.length ? e.filter((x) => x > 0).length / e.length : null;
}

/** A metric value at a precision that suits it. */
export function fmtScore(v: number | null | undefined, metric: string): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  if (metric === "mae") return `${v.toFixed(2)} bps`;
  return Math.abs(v) >= 1 ? v.toFixed(2) : v.toFixed(4);
}

/** Days since a timestamp, in words. */
export function ago(ms: number | null | undefined, now = Date.now()): string {
  if (!ms) return "never";
  const d = Math.floor((now - ms) / 86_400_000);
  return d <= 0 ? "today" : d === 1 ? "yesterday" : `${d} days ago`;
}
