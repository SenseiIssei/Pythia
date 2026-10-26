// The Lab page's research factory panel (server GET /api/lab/factory): the
// factories' nightly reports (F3 pump.fun reports/pumpfun_rt/factory.json, F2
// small wallets reports/smallaccount/factory.json), A1's model zoo (zoo.json:
// the pick per label) and its allocator (allocator.json: the posterior per
// strategy). Fields as the lab writes them (snake_case). Paper only, read only.

import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";

export interface FactoryBar {
  sharpe?: number;
  p?: number;
  min_entries?: number;
  trials?: number;
}

export interface FactoryCandidate {
  id: string;
  label?: string | null;
  sizing?: string | null;
  /** Median wallet after 30 days in SOL (from START_SOL). */
  median?: number | null;
  p_lost80?: number | null;
  entries?: number | null;
  dsr?: number | null;
}

export interface FactoryHeld {
  id: string;
  median?: number | null;
  pnl_sol?: number | null;
  entries?: number | null;
}

export interface FactoryBook {
  book: string;
  label?: string;
  sizing?: string;
  added_day?: string | null;
  sol?: number | null;
  eur?: number | null;
  pnl_sol?: number | null;
  trades?: number;
  ref_sol?: number | null;
  proposed?: boolean;
}

export interface FactoryReport {
  updated_ms?: number;
  night?: string;
  trials_ever?: number;
  trials_tonight?: number;
  bar?: FactoryBar;
  best?: FactoryCandidate[];
  holdback?: FactoryHeld[];
  winners?: string[];
  books?: FactoryBook[];
  retired?: { book?: string; retired_ms?: number; why?: string }[];
  proposals?: string[];
  /** The labels whose model settings are adopted. */
  adopted?: string[];
  sol_eur?: number | null;
  start_sol?: number;
}

export interface ZooLabel {
  pick?: string | null;
  days?: number | null;
  changes?: { day?: string; from?: string; to?: string; why?: string }[] | null;
  note?: string | null;
}

export interface AllocatorArm {
  days?: number;
  mean?: number | null;
  posterior_mean?: number | null;
  posterior_sd?: number | null;
  p_best?: number | null;
  weight?: number | null;
  drawdown?: number | null;
  guarded?: boolean;
  wallet_x?: number | null;
}

export interface Allocator {
  updated_ms?: number;
  choice?: string | null;
  why?: string | null;
  live_rule?: string | null;
  armed?: boolean;
  arms?: Record<string, AllocatorArm>;
}

export interface LabFactory {
  found: boolean;
  factories?: { F3?: FactoryReport | null; F2?: FactoryReport | null };
  zoo?: { updated_ms?: number; labels?: Record<string, ZooLabel> } | null;
  allocator?: Allocator | null;
}

/** The factory panel's data from the connected server. The desktop app has no reader for it yet. */
export async function labFactory(): Promise<LabFactory> {
  if (liveMode() !== "server") throw new Error("The research factory is read by the connected server.");
  const r = await fetch(`${serverUrl()}/api/lab/factory`);
  if (!r.ok) throw new Error(`backend answered ${r.status}`);
  return (await r.json()) as LabFactory;
}

export const FACTORY_NAMES: Record<string, string> = { F3: "F3 · pump.fun", F2: "F2 · small wallets" };

export interface FactoryView {
  code: string;
  name: string;
  /** null: the factory has not written a report (not built yet, or not run). */
  report: FactoryReport | null;
  /** The night's best candidate and its held-back result, when it was held back. */
  best: FactoryCandidate | null;
  held: FactoryHeld | null;
  books: (FactoryBook & { eurNow: number | null })[];
}

/** One view per factory, F3 then F2, each with its books' wallets in EUR (the book's own, else SOL at the report's rate). */
export function factoryViews(d: LabFactory | null | undefined): FactoryView[] {
  return (["F3", "F2"] as const).map((code) => {
    const r = d?.factories?.[code] ?? null;
    const best = r?.best?.[0] ?? null;
    return {
      code,
      name: FACTORY_NAMES[code],
      report: r,
      best,
      held: best ? (r?.holdback ?? []).find((h) => h.id === best.id) ?? null : null,
      books: (r?.books ?? []).map((b) => ({
        ...b,
        eurNow: b.eur ?? (b.sol != null && r?.sol_eur ? b.sol * r.sol_eur : null),
      })),
    };
  });
}

export interface ArmRow extends AllocatorArm {
  name: string;
  chosen: boolean;
  live: boolean;
}

/** The allocator's strategies, the most likely best first. */
export function armRows(a: Allocator | null | undefined): ArmRow[] {
  return Object.entries(a?.arms ?? {})
    .map(([name, x]) => ({ ...x, name, chosen: name === a?.choice, live: name === a?.live_rule }))
    .sort((x, y) => (y.p_best ?? 0) - (x.p_best ?? 0) || x.name.localeCompare(y.name));
}

/** The zoo's pick per label, in the report's order. */
export function zooPicks(d: LabFactory | null | undefined): { label: string; pick: string | null; days: number | null; changed: string | null }[] {
  return Object.entries(d?.zoo?.labels ?? {}).map(([label, z]) => {
    const last = (z.changes ?? []).at(-1);
    return { label, pick: z.pick ?? null, days: z.days ?? null, changed: last ? `${last.from} → ${last.to} on ${last.day}` : null };
  });
}

/** Euro in the app's English: "€97.60"; "n/a" without a number. */
export function euro(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  return v.toLocaleString("en-GB", { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
