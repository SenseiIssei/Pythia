// Real money readiness: the lab's daily check of every autopilot on the Alpaca
// paper account against the pre-registered rule (docs/LIVE-READINESS.md,
// research/lab/lab/ops/readiness.py). Read from reports/readiness/latest.json
// through the lab status; the risk step is saved through the engine
// (GET/POST /api/readiness/settings, or the desktop commands). Nothing here
// arms live or changes an autopilot.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";

export interface ReadinessRule {
  id: string;
  label: string;
  pass: boolean;
  value: string;
  need: string;
  detail: string;
}

export interface ReadinessItem {
  kind: "autopilot" | "sleeve";
  key: string;
  id: string;
  name: string;
  parent: string | null;
  mode: string | null;
  onAccount: boolean;
  days: number;
  ready: boolean;
  passed: number;
  total: number;
  daysToGo: number | null;
  annualisedPct: number | null;
  sp500Pct: number | null;
  rules: ReadinessRule[];
}

export interface RiskProfile {
  step: number;
  label: string;
  maxDdPct: number;
  etfHurdlePct: number;
  minPositiveWeeks: number;
  minDays: number;
}

export interface Inflation {
  pct: number | null;
  source: string | null;
  month: string | null;
  cached: boolean | null;
}

export interface ReadinessReport {
  generatedMs: number;
  ruleDate: string;
  profile: RiskProfile;
  profiles: RiskProfile[];
  inflation: Inflation;
  items: ReadinessItem[];
  headline: string;
}

export interface ReadinessSettings {
  riskStep: number;
  updatedMs: number;
}

const obj = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown, d = ""): string => (typeof v === "string" ? v : d);

function profileOf(v: unknown): RiskProfile | null {
  const p = obj(v);
  const step = num(p.step);
  if (step == null) return null;
  return {
    step,
    label: str(p.label, `step ${step}`),
    maxDdPct: num(p.max_dd_pct) ?? 0,
    etfHurdlePct: num(p.etf_hurdle_pct) ?? 0,
    minPositiveWeeks: num(p.min_positive_weeks) ?? 0,
    minDays: num(p.min_days) ?? 0,
  };
}

/** The lab's file as written (snake_case), or null when it is not one. */
export function parseReadiness(v: unknown): ReadinessReport | null {
  const d = obj(v);
  if (!Array.isArray(d.autopilots)) return null;
  const profile = profileOf(d.profile);
  if (!profile) return null;
  const inf = obj(d.inflation);
  const items: ReadinessItem[] = (d.autopilots as unknown[]).map((x) => {
    const i = obj(x);
    const rules = (Array.isArray(i.rules) ? i.rules : []).map((r) => {
      const o = obj(r);
      return {
        id: str(o.id),
        label: str(o.label),
        pass: o.pass === true,
        value: str(o.value),
        need: str(o.need),
        detail: str(o.detail),
      };
    });
    return {
      kind: i.kind === "sleeve" ? "sleeve" : "autopilot",
      key: str(i.key, str(i.id)),
      id: str(i.id),
      name: str(i.name, "Autopilot"),
      parent: typeof i.parent === "string" ? i.parent : null,
      mode: typeof i.mode === "string" ? i.mode : null,
      onAccount: i.on_account === true,
      days: num(i.days) ?? 0,
      ready: i.ready === true,
      passed: num(i.passed) ?? rules.filter((r) => r.pass).length,
      total: num(i.total) ?? rules.length,
      daysToGo: num(i.days_to_go),
      annualisedPct: num(i.annualised_pct),
      sp500Pct: num(i.sp500_pct),
      rules,
    };
  });
  return {
    generatedMs: num(d.generated_ms) ?? num(d.updated_ms) ?? 0,
    ruleDate: str(d.rule_date),
    profile,
    profiles: (Array.isArray(d.profiles) ? d.profiles : []).map(profileOf).filter((p): p is RiskProfile => p != null),
    inflation: { pct: num(inf.pct), source: typeof inf.source === "string" ? inf.source : null, month: typeof inf.month === "string" ? inf.month : null, cached: typeof inf.cached === "boolean" ? inf.cached : null },
    items,
    headline: str(d.headline),
  };
}

/** Short names for the rule chips, by rule id. */
export const RULE_SHORT: Record<string, string> = {
  record: "Days and trades",
  profit: "Profit",
  weeks: "Good weeks",
  benchmark: "Benchmark",
  drawdown: "Drawdown",
  band: "Backtest band",
  reconcile: "Reconcile",
  inflation: "Inflation",
  etf: "ETF hurdle",
};

/** "Ready", "12 days to go", or what it is waiting on. */
export function progressWords(i: ReadinessItem): string {
  if (!i.onAccount) return "Not on the Alpaca paper account";
  if (i.ready) return "Ready for a real money proposal";
  if (i.daysToGo && i.daysToGo > 0) return `${i.daysToGo} ${i.daysToGo === 1 ? "day" : "days"} to go at the earliest`;
  const missing = i.rules.filter((r) => !r.pass).map((r) => (RULE_SHORT[r.id] ?? r.label).toLowerCase());
  return missing.length ? `Waiting on ${missing.slice(0, 3).join(", ")}` : "Waiting for the next check";
}

/** The numbers a risk step sets, in one line. */
export function profileWords(p: RiskProfile): string {
  return `drawdown at most ${trim(p.maxDdPct)} %, beat ${trim(p.etfHurdlePct)} % a year, ${p.minPositiveWeeks} of 4 weeks positive, ${p.minDays} days`;
}

function trim(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/** The step's profile, from the report's table. */
export function profileFor(profiles: RiskProfile[], step: number): RiskProfile | null {
  return profiles.find((p) => p.step === step) ?? null;
}

/** Autopilots first, each followed by its sleeves. */
export function ordered(items: ReadinessItem[]): ReadinessItem[] {
  const aps = items.filter((i) => i.kind === "autopilot");
  const out: ReadinessItem[] = [];
  for (const a of aps) {
    out.push(a);
    out.push(...items.filter((i) => i.kind === "sleeve" && i.parent === a.id));
  }
  out.push(...items.filter((i) => i.kind === "sleeve" && !aps.some((a) => a.id === i.parent)));
  return out;
}

export async function readinessSettings(): Promise<ReadinessSettings> {
  switch (liveMode()) {
    case "native":
      return invoke<ReadinessSettings>("readiness_settings");
    case "server": {
      const r = await fetch(`${serverUrl()}/api/readiness/settings`);
      if (!r.ok) throw new Error(`backend answered ${r.status}`);
      return (await r.json()) as ReadinessSettings;
    }
    default:
      throw new Error("The readiness setting needs the desktop app or a connected backend.");
  }
}

export async function setReadinessSettings(riskStep: number): Promise<ReadinessSettings> {
  switch (liveMode()) {
    case "native":
      return invoke<ReadinessSettings>("set_readiness_settings", { riskStep });
    case "server": {
      const r = await fetch(`${serverUrl()}/api/readiness/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ riskStep }),
      });
      if (!r.ok) {
        const body = (await r.json().catch(() => null)) as { error?: string } | null;
        throw new Error(body?.error ?? `backend answered ${r.status}`);
      }
      return (await r.json()) as ReadinessSettings;
    }
    default:
      throw new Error("The readiness setting needs the desktop app or a connected backend.");
  }
}
