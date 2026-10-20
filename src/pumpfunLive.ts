// The pump.fun wallet page's data (pythia-core pumpfun_live, GET /api/pumpfun/live):
// what the owner's live service on the server reports, the limits the owner may
// lower, and the kill switch. Nothing here reads a key or moves money; there is
// no withdraw or transfer in Pythia. Funding is the owner sending SOL from his
// own wallet or exchange to the address; withdrawing is the owner importing his
// backup into his own wallet. docs/PUMPFUN-LIVE.md.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";

export interface PumpfunAck {
  mode: "test" | "full" | null;
  strategy: string | null;
  maxTotalSol: number | null;
  maxDailyLossSol: number | null;
  maxTradeSol: number | null;
}

export interface PumpfunLimits {
  maxTradeSol: number | null;
  maxOpen: number | null;
  maxExposureSol: number | null;
  maxDailyLossSol: number | null;
  maxTotalSol: number | null;
}

export interface PumpfunPosition {
  pid: number | null;
  mint: string;
  symbol: string | null;
  name: string | null;
  venue: string | null;
  state: string | null;
  tokens: number | null;
  costSol: number | null;
  markSol: number | null;
  signalMs: number | null;
  landMs: number | null;
}

export interface PumpfunStatus {
  t: number;
  running: boolean;
  on: boolean;
  mode: "test" | "full" | null;
  rule: string | null;
  address: string | null;
  balanceSol: number | null;
  balanceT: number | null;
  holdings: { mint: string; amount: number }[];
  positions: PumpfunPosition[];
  leftovers: Record<string, unknown>[];
  pnlTodaySol: number;
  tradesToday: number;
  winsToday: number;
  pnlTotalSol: number;
  tradesTotal: number;
  sinceMs: number | null;
  gate: string[];
  refusing: string | null;
  ack: PumpfunAck;
  limits: PumpfunLimits | null;
  stops: { daily: boolean; total: boolean };
  kill: boolean;
  simulate: { t: number | null; ok: boolean | null; venue: string | null; mint: string | null } | null;
  exposureSol: number;
  skipped: Record<string, number>;
}

export interface PumpfunTrade {
  mode: string | null;
  rule: string | null;
  mint: string | null;
  name: string | null;
  symbol: string | null;
  signalMs: number | null;
  landMs: number | null;
  exitMs: number | null;
  exitWhy: string | null;
  stakeSol: number | null;
  proceedsSol: number | null;
  pnlSol: number | null;
  ret: number | null;
  holdS: number | null;
  latBuyMs: number | null;
  slip: number | null;
}

export interface PumpfunDist {
  n: number;
  median: number | null;
  p10: number | null;
  p90: number | null;
}

export interface PumpfunExecution {
  verdict: string;
  fills: number;
  failed: number;
  latBuyMs: PumpfunDist;
  sendToLandMs: PumpfunDist;
  slipBuy: PumpfunDist;
  paperSlip: PumpfunDist;
  feeSol: PumpfunDist;
  assumed: { latMedianMs: number | null; latLoMs: number | null; latHiMs: number | null; txFeeSol: number | null; slipTol: number | null };
  latRatio: number | null;
}

export interface PumpfunSettings {
  maxTotalSol: number | null;
  maxDailyLossSol: number | null;
  maxTradeSol: number | null;
  maxOpen: number | null;
  updatedMs: number;
}

export interface PumpfunHard {
  testMaxTotalSol: number;
  testMaxDailyLossSol: number;
  testMaxTradeSol: number;
  fullMaxDailyLossSol: number;
  fullMaxTradeSol: number;
  maxOpen: number;
}

export interface PumpfunView {
  running: boolean;
  status: PumpfunStatus | null;
  address: string | null;
  settings: PumpfunSettings;
  killFile: boolean;
  trades: PumpfunTrade[];
  execution: PumpfunExecution | null;
  hard: PumpfunHard;
  nowMs: number;
}

export type SettingsPatch = Partial<Record<"maxTotalSol" | "maxDailyLossSol" | "maxTradeSol" | "maxOpen", number | null>>;

async function asJson<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `backend answered ${r.status}`;
    try {
      const body = (await r.json()) as { error?: string };
      if (body?.error) msg = body.error;
    } catch {
      /* not JSON: keep the status */
    }
    throw new Error(msg);
  }
  return (await r.json()) as T;
}

export async function pumpfunLive(): Promise<PumpfunView> {
  switch (liveMode()) {
    case "native":
      return invoke<PumpfunView>("pumpfun_live");
    case "server":
      return asJson<PumpfunView>(await fetch(`${serverUrl()}/api/pumpfun/live`));
    default:
      throw new Error("The pump.fun wallet needs a connected backend.");
  }
}

/** The limits and the kill switch act on the server's files; the desktop app only shows them. */
export function canControl(): boolean {
  return liveMode() === "server";
}

export async function savePumpfunLimits(patch: SettingsPatch): Promise<PumpfunSettings> {
  if (!canControl()) throw new Error("Limits are set through the connected backend on the server.");
  return asJson<PumpfunSettings>(
    await fetch(`${serverUrl()}/api/pumpfun/live/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  );
}

export async function pumpfunKill(): Promise<{ killFile: boolean; path: string; already: boolean }> {
  if (!canControl()) throw new Error("The kill switch works through the connected backend on the server.");
  return asJson(await fetch(`${serverUrl()}/api/pumpfun/live/kill`, { method: "POST" }));
}

// ── what the page says ──

export function sol(v: number | null | undefined, signed = false, dp = 4): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const s = Math.abs(v).toFixed(dp);
  return `${signed ? (v > 0 ? "+" : v < 0 ? "-" : "") : v < 0 ? "-" : ""}${s} SOL`;
}

export type Tone = "up" | "down" | "flat";

export function tone(v: number | null | undefined): Tone {
  return v == null || v === 0 ? "flat" : v > 0 ? "up" : "down";
}

export interface StateLine {
  label: string;
  level: "ok" | "warn" | "bad" | "off";
  detail: string;
}

/** One line for the top of the page: is anything trading, and if not, why. */
export function stateLine(v: PumpfunView): StateLine {
  const s = v.status;
  if (v.killFile || s?.kill) {
    return { label: "Stopped by the kill switch", level: "bad", detail: "Nothing is bought; what was open is sold. Delete reports/pumpfun_rt/KILL on the server to allow buys again." };
  }
  if (!s || !v.running) {
    return { label: "Live service not running", level: "off", detail: "Nothing trades. The owner starts the live service by hand on the server (docs/PUMPFUN-LIVE.md)." };
  }
  if (s.stops.total) return { label: "Total budget used up", level: "bad", detail: "The total budget stop fired; no more buys. Only a new confirmation file changes that." };
  if (s.stops.daily) return { label: "Daily loss stop", level: "warn", detail: "No more buys until tomorrow (UTC)." };
  if (s.on) {
    return { label: s.mode === "test" ? "Trading real money (test)" : "Trading real money", level: "ok", detail: `${s.rule ?? "?"}, every trade is posted to Telegram.` };
  }
  return { label: "Not trading", level: "warn", detail: s.gate[0] ?? s.refusing ?? "The live gate is shut." };
}

export interface Ceilings {
  maxTotalSol: number | null;
  maxDailyLossSol: number;
  maxTradeSol: number;
  maxOpen: number;
}

/** What a setting must stay at or under (the same rule the engine checks): the confirmation file, capped by the code. */
export function ceilings(ack: PumpfunAck | null | undefined, hard: PumpfunHard): Ceilings | null {
  const low = (a: number | null | undefined, h: number) => (a != null && Number.isFinite(a) && a > 0 ? Math.min(a, h) : h);
  if (ack?.mode === "test") {
    return {
      maxTotalSol: low(ack.maxTotalSol, hard.testMaxTotalSol),
      maxDailyLossSol: low(ack.maxDailyLossSol, hard.testMaxDailyLossSol),
      maxTradeSol: low(ack.maxTradeSol, hard.testMaxTradeSol),
      maxOpen: hard.maxOpen,
    };
  }
  if (ack?.mode === "full") {
    return { maxTotalSol: null, maxDailyLossSol: low(ack.maxDailyLossSol, hard.fullMaxDailyLossSol), maxTradeSol: hard.fullMaxTradeSol, maxOpen: hard.maxOpen };
  }
  return null;
}

export type LimitKey = "maxTotalSol" | "maxDailyLossSol" | "maxTradeSol" | "maxOpen";
export type LimitInput = Record<LimitKey, string>;

export const LIMIT_LABEL: Record<LimitKey, string> = {
  maxTotalSol: "Total budget",
  maxDailyLossSol: "Daily loss limit",
  maxTradeSol: "Per trade",
  maxOpen: "Open positions",
};

/** The form's text into a patch, or the reason it cannot be saved. Empty means "use the confirmation file's value". */
export function parseLimits(input: LimitInput, c: Ceilings | null): { patch: SettingsPatch; errors: Partial<Record<LimitKey, string>> } {
  const patch: SettingsPatch = {};
  const errors: Partial<Record<LimitKey, string>> = {};
  if (!c) {
    for (const k of Object.keys(input) as LimitKey[]) if (input[k].trim()) errors[k] = "Start the live service first: limits are set below its confirmation file.";
    return { patch, errors };
  }
  for (const k of Object.keys(input) as LimitKey[]) {
    const raw = input[k].trim().replace(",", ".");
    if (!raw) {
      patch[k] = null;
      continue;
    }
    const v = Number(raw);
    if (k === "maxOpen") {
      if (!Number.isInteger(v) || v < 1 || v > c.maxOpen) errors[k] = `A whole number from 1 to ${c.maxOpen}.`;
      else patch[k] = v;
      continue;
    }
    const cap = c[k];
    if (!Number.isFinite(v) || v <= 0) errors[k] = "A positive amount of SOL.";
    else if (cap != null && v > cap + 1e-12) errors[k] = `Only lower: at most ${cap} SOL.`;
    else patch[k] = v;
  }
  return { patch, errors };
}

export function limitInput(s: PumpfunSettings | null | undefined): LimitInput {
  const f = (v: number | null | undefined) => (v == null ? "" : String(v));
  return { maxTotalSol: f(s?.maxTotalSol), maxDailyLossSol: f(s?.maxDailyLossSol), maxTradeSol: f(s?.maxTradeSol), maxOpen: f(s?.maxOpen) };
}

const EXIT: Record<string, string> = {
  take: "take profit",
  take_part: "part taken",
  stop: "stop loss",
  trail: "trailing stop",
  dev_sell: "the dev sold",
  pull: "liquidity pulled",
  risk: "risk model",
  time: "time stop",
  kill: "kill switch",
  stuck: "could not sell",
};

export function exitWords(why: string | null | undefined): string {
  return why ? EXIT[why] ?? why : "";
}

/** A mint or address shortened for a row: first and last four characters. */
export function short(a: string | null | undefined): string {
  if (!a) return "";
  return a.length > 12 ? `${a.slice(0, 4)}...${a.slice(-4)}` : a;
}
