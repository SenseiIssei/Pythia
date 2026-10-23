// The on-chain wallet on the Real money page (pythia-core onchain_live, GET
// /api/onchain/live): what the owner's locked real-money Solana trader on the
// server reports, the owner's conversions between the allowed coins, and the
// kill switch. Nothing here reads a key, signs or moves money; there is no
// withdraw or transfer in Pythia. A conversion is a request the trader quotes,
// then a confirm of exactly that quote; the trader guards and signs on the
// server. docs/ONCHAIN-STAGE2.md.

import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";
import { usdToEur } from "./realMoney";
import type { SolEur } from "./pumpfunLive";

export interface OnchainBalance {
  coin: string;
  symbol: string | null;
  mint: string | null;
  amount: number | null;
  usd: number | null;
  priceUsd: number | null;
}

export interface OnchainDay {
  startUsd: number | null;
  pnlUsd: number | null;
  swaps: number | null;
  converts: number | null;
  convertUsd: number | null;
}

export interface OnchainAck {
  mode: string | null;
  books: string[] | null;
  mints: string[] | null;
  bookUsd: number | null;
  maxTotalUsd: number | null;
  maxTradeUsd: number | null;
  maxDailyLossUsd: number | null;
  maxConvertUsd: number | null;
  expires: string | null;
  onKill: string | null;
}

export interface OnchainHard {
  maxTotalUsd: number | null;
  maxTradeUsd: number | null;
  maxDailyLossUsd: number | null;
  maxConvertUsd: number | null;
  reserveSol: number | null;
  maxConverts: number | null;
  confirmS: number | null;
}

export interface OnchainLimits {
  maxTotalUsd: number | null;
  maxTradeUsd: number | null;
  maxDailyLossUsd: number | null;
  maxConvertUsd: number | null;
}

export interface OnchainCoin {
  coin: string;
  symbol: string | null;
  mint: string | null;
  decimals: number | null;
  allowed: boolean;
}

export interface OnchainStatus {
  t: number;
  running: boolean;
  on: boolean;
  mode: string | null;
  /** Every reason the trader does not trade (empty when it may). */
  gate: string[];
  address: string | null;
  solLamports: number | null;
  balances: OnchainBalance[];
  totalUsd: number | null;
  day: OnchainDay | null;
  ack: OnchainAck | null;
  hard: OnchainHard | null;
  limits: OnchainLimits | null;
  coins: OnchainCoin[];
  kill: boolean;
  simulate: { t: number | null; ok: boolean | null } | null;
  books: { book: string; allowed: boolean; why: string | null }[];
  reconcile: { t: number | null; ok: boolean | null; diffs: string[] } | null;
  stops: { daily: boolean; total: boolean };
}

export interface OnchainTrade {
  t: number | null;
  kind: string | null;
  book: string | null;
  from: string | null;
  to: string | null;
  inAmount: number | null;
  outAmount: number | null;
  inUsd: number | null;
  outUsd: number | null;
  feeSol: number | null;
  sig: string | null;
  status: string | null;
  why: string | null;
}

export type ConvertState = "waiting" | "proposed" | "refused" | "confirmed" | "filled" | "failed" | "expired";
const STATES: readonly ConvertState[] = ["waiting", "proposed", "refused", "confirmed", "filled", "failed", "expired"];

/** One conversion: the request, the trader's proposal, the confirm and the result in one. */
export interface OnchainConvert {
  id: string;
  state: ConvertState;
  from: string | null;
  to: string | null;
  amount: number | null;
  requestedMs: number | null;
  expectedOut: number | null;
  minOut: number | null;
  costBps: number | null;
  inUsd: number | null;
  route: string[];
  proposedMs: number | null;
  expiresMs: number | null;
  confirmedMs: number | null;
  doneMs: number | null;
  sig: string | null;
  outAmount: number | null;
  why: string | null;
}

export interface OnchainView {
  /** The trader wrote its status within two minutes and did not say it stopped. */
  running: boolean;
  status: OnchainStatus | null;
  /** The wallet's public address: from the trader, else from the wallet tool's file. */
  address: string | null;
  trades: OnchainTrade[];
  converts: OnchainConvert[];
  killFile: boolean;
  nowMs: number;
  /** One euro in US dollars (Kraken's EURUSD), read by the backend; null when it could not be read. */
  eurUsd: SolEur | null;
}

// ── reading the view: anything malformed becomes null or empty, never a throw ──

type Obj = Record<string, unknown>;
const obj = (x: unknown): Obj | null => (x != null && typeof x === "object" && !Array.isArray(x) ? (x as Obj) : null);
const num = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);
const str = (x: unknown): string | null => (typeof x === "string" ? x : null);
const bool = (x: unknown): boolean => x === true;
const strs = (x: unknown): string[] => (Array.isArray(x) ? x.filter((s): s is string => typeof s === "string") : []);
const list = <T>(x: unknown, f: (o: Obj) => T | null): T[] => (Array.isArray(x) ? x.map((e) => { const o = obj(e); return o ? f(o) : null; }).filter((e): e is T => e != null) : []);

function balance(o: Obj): OnchainBalance | null {
  const coin = str(o.coin);
  if (!coin) return null;
  return { coin, symbol: str(o.symbol), mint: str(o.mint), amount: num(o.amount), usd: num(o.usd), priceUsd: num(o.priceUsd) };
}

function coin(o: Obj): OnchainCoin | null {
  const c = str(o.coin);
  if (!c) return null;
  return { coin: c, symbol: str(o.symbol), mint: str(o.mint), decimals: num(o.decimals), allowed: bool(o.allowed) };
}

function status(x: unknown): OnchainStatus | null {
  const o = obj(x);
  const t = num(o?.t);
  if (!o || t == null) return null;
  const day = obj(o.day);
  const ack = obj(o.ack);
  const hard = obj(o.hard);
  const limits = obj(o.limits);
  const sim = obj(o.simulate);
  const rec = obj(o.reconcile);
  const stops = obj(o.stops);
  return {
    t,
    running: bool(o.running),
    on: bool(o.on),
    mode: str(o.mode),
    gate: strs(o.gate),
    address: str(o.address),
    solLamports: num(o.solLamports),
    balances: list(o.balances, balance),
    totalUsd: num(o.totalUsd),
    day: day ? { startUsd: num(day.startUsd), pnlUsd: num(day.pnlUsd), swaps: num(day.swaps), converts: num(day.converts), convertUsd: num(day.convertUsd) } : null,
    ack: ack
      ? {
          mode: str(ack.mode),
          books: Array.isArray(ack.books) ? strs(ack.books) : null,
          mints: Array.isArray(ack.mints) ? strs(ack.mints) : null,
          bookUsd: num(ack.bookUsd),
          maxTotalUsd: num(ack.maxTotalUsd),
          maxTradeUsd: num(ack.maxTradeUsd),
          maxDailyLossUsd: num(ack.maxDailyLossUsd),
          maxConvertUsd: num(ack.maxConvertUsd),
          expires: str(ack.expires),
          onKill: str(ack.onKill),
        }
      : null,
    hard: hard
      ? {
          maxTotalUsd: num(hard.maxTotalUsd),
          maxTradeUsd: num(hard.maxTradeUsd),
          maxDailyLossUsd: num(hard.maxDailyLossUsd),
          maxConvertUsd: num(hard.maxConvertUsd),
          reserveSol: num(hard.reserveSol),
          maxConverts: num(hard.maxConverts),
          confirmS: num(hard.confirmS),
        }
      : null,
    limits: limits
      ? { maxTotalUsd: num(limits.maxTotalUsd), maxTradeUsd: num(limits.maxTradeUsd), maxDailyLossUsd: num(limits.maxDailyLossUsd), maxConvertUsd: num(limits.maxConvertUsd) }
      : null,
    coins: list(o.coins, coin),
    kill: bool(o.kill),
    simulate: sim ? { t: num(sim.t), ok: typeof sim.ok === "boolean" ? sim.ok : null } : null,
    books: list(o.books, (b) => (str(b.book) ? { book: str(b.book) as string, allowed: bool(b.allowed), why: str(b.why) } : null)),
    reconcile: rec ? { t: num(rec.t), ok: typeof rec.ok === "boolean" ? rec.ok : null, diffs: strs(rec.diffs) } : null,
    stops: { daily: bool(stops?.daily), total: bool(stops?.total) },
  };
}

function trade(o: Obj): OnchainTrade {
  return {
    t: num(o.t),
    kind: str(o.kind),
    book: str(o.book),
    from: str(o.from),
    to: str(o.to),
    inAmount: num(o.inAmount),
    outAmount: num(o.outAmount),
    inUsd: num(o.inUsd),
    outUsd: num(o.outUsd),
    feeSol: num(o.feeSol),
    sig: str(o.sig),
    status: str(o.status),
    why: str(o.why),
  };
}

function convert(o: Obj): OnchainConvert | null {
  const id = str(o.id);
  const state = str(o.state) as ConvertState | null;
  if (!id || !state || !STATES.includes(state)) return null;
  return {
    id,
    state,
    from: str(o.from),
    to: str(o.to),
    amount: num(o.amount),
    requestedMs: num(o.requestedMs),
    expectedOut: num(o.expectedOut),
    minOut: num(o.minOut),
    costBps: num(o.costBps),
    inUsd: num(o.inUsd),
    route: strs(o.route),
    proposedMs: num(o.proposedMs),
    expiresMs: num(o.expiresMs),
    confirmedMs: num(o.confirmedMs),
    doneMs: num(o.doneMs),
    sig: str(o.sig),
    outAmount: num(o.outAmount),
    why: str(o.why),
  };
}

/** The engine's answer as the section reads it. */
export function parseOnchainView(x: unknown): OnchainView {
  const o = obj(x) ?? {};
  const rate = obj(o.eurUsd);
  const price = num(rate?.price);
  return {
    running: bool(o.running),
    status: status(o.status),
    address: str(o.address),
    trades: list(o.trades, trade),
    converts: list(o.converts, convert),
    killFile: bool(o.killFile),
    nowMs: num(o.nowMs) ?? Date.now(),
    eurUsd: rate && price != null && price > 0 ? { price, open: num(rate.open) ?? price, t: num(rate.t) ?? 0 } : null,
  };
}

// ── the engine's routes (server only: the files live on the server) ──

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

/** Conversions and the kill switch act on the server's files; only the connected backend has them. */
export function canControlOnchain(): boolean {
  return liveMode() === "server";
}

const NO_SERVER = "The on-chain wallet needs the connected backend on the server.";

export async function onchainLive(): Promise<OnchainView> {
  if (!canControlOnchain()) throw new Error(NO_SERVER);
  return parseOnchainView(await asJson<unknown>(await fetch(`${serverUrl()}/api/onchain/live`, { cache: "no-store" })));
}

const post = async <T>(path: string, body?: unknown): Promise<T> =>
  asJson<T>(
    await fetch(`${serverUrl()}${path}`, {
      method: "POST",
      ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    }),
  );

export interface ConvertAsk {
  from: string;
  to: string;
  /** In units of `from`. */
  amount: number;
}

/** Ask the trader for a quote; the answer is the request's id. */
export async function onchainConvert(ask: ConvertAsk): Promise<{ id: string }> {
  if (!canControlOnchain()) throw new Error(NO_SERVER);
  return post("/api/onchain/live/convert", ask);
}

/** Accept the trader's fresh proposal `id`. */
export async function onchainConfirm(id: string): Promise<{ id: string; confirmed: boolean }> {
  if (!canControlOnchain()) throw new Error(NO_SERVER);
  return post("/api/onchain/live/convert/confirm", { id });
}

export async function onchainKill(): Promise<{ killFile: boolean; path: string; already: boolean }> {
  if (!canControlOnchain()) throw new Error(NO_SERVER);
  return post("/api/onchain/live/kill");
}

// ── what the section says ──

/** A balance in US dollars (the trader's figure, else amount times price) and in euro at Kraken's EUR/USD. */
export function balanceMoney(b: OnchainBalance, eurUsd: SolEur | null | undefined): { usd: number | null; eur: number | null } {
  const usd = b.usd ?? (b.amount != null && b.priceUsd != null ? b.amount * b.priceUsd : null);
  return { usd, eur: usd == null ? null : usdToEur(usd, eurUsd) };
}

/** The wallet's worth: the trader's total, else the sum of what it priced. */
export function totalMoney(s: OnchainStatus | null | undefined, eurUsd: SolEur | null | undefined): { usd: number | null; eur: number | null } {
  if (!s) return { usd: null, eur: null };
  const parts = s.balances.map((b) => balanceMoney(b, null).usd).filter((u): u is number => u != null);
  const usd = s.totalUsd ?? (parts.length ? parts.reduce((a, b) => a + b, 0) : null);
  return { usd, eur: usd == null ? null : usdToEur(usd, eurUsd) };
}

/** A coin amount: up to `dp` decimals, no trailing zeros ("0.05", "1,234.5"). */
export function amountText(v: number | null | undefined, dp = 6): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  return v.toLocaleString("en-US", { maximumFractionDigits: dp });
}

export function usdText(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  return v.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** The coins a conversion may go from and to. */
export function allowedCoins(s: OnchainStatus | null | undefined): string[] {
  return (s?.coins ?? []).filter((c) => c.allowed).map((c) => c.coin);
}

/** A coin's price in US dollars from the balances, or null. */
export function priceOf(s: OnchainStatus | null | undefined, c: string): number | null {
  const p = s?.balances.find((b) => b.coin === c)?.priceUsd;
  return p != null && p > 0 ? p : null;
}

export interface ConvertInput {
  from: string;
  to: string;
  amount: string;
}

/** The form into a request, or every reason it cannot be sent (the engine checks again, the trader once more). */
export function checkConvert(input: ConvertInput, v: Pick<OnchainView, "status" | "running" | "killFile">): { ask: ConvertAsk | null; errors: string[] } {
  const errors: string[] = [];
  const s = v.status;
  if (!s || !v.running) errors.push("The trader is not running.");
  if (v.killFile || s?.kill) errors.push("The kill switch is on.");
  const ok = allowedCoins(s);
  if (!input.from || !input.to) errors.push("Choose both coins.");
  else if (input.from === input.to) errors.push("From and to must be different coins.");
  for (const c of [input.from, input.to]) if (c && !ok.includes(c)) errors.push(`${c} is not a coin the trader may convert.`);
  const raw = input.amount.trim().replace(",", ".");
  const amount = raw ? Number(raw) : NaN;
  if (!Number.isFinite(amount) || amount <= 0) errors.push("The amount must be a positive number.");
  else {
    const price = priceOf(s, input.from);
    const cap = s?.limits?.maxTradeUsd ?? null;
    if (price != null && cap != null && amount * price > cap + 1e-9) errors.push(`At most ${usdText(cap)} per trade: about ${amountText(cap / price)} ${input.from}.`);
  }
  return { ask: errors.length ? null : { from: input.from, to: input.to, amount }, errors };
}

/** Seconds left to confirm a proposal, or null when it is not proposed. */
export function secondsLeft(c: Pick<OnchainConvert, "state" | "expiresMs">, nowMs: number): number | null {
  if (c.state !== "proposed" || c.expiresMs == null) return null;
  return Math.max(0, Math.ceil((c.expiresMs - nowMs) / 1000));
}

/** A conversion still on its way: the section reads every FAST_POLL_MS while there is one. */
export function inFlight(c: Pick<OnchainConvert, "state">): boolean {
  return c.state === "waiting" || c.state === "proposed" || c.state === "confirmed";
}

export const FAST_POLL_MS = 3_000;
export const SLOW_POLL_MS = 15_000;

export function pollMs(v: Pick<OnchainView, "converts"> | null | undefined): number {
  return v?.converts.some(inFlight) ? FAST_POLL_MS : SLOW_POLL_MS;
}

export const STATE_WORDS: Record<ConvertState, string> = {
  waiting: "Waiting for a quote",
  proposed: "Quote ready",
  refused: "Refused",
  confirmed: "Confirmed, being sent",
  filled: "Done",
  failed: "Failed",
  expired: "Expired",
};

/** Is it trading, in one line. */
export function onOff(v: Pick<OnchainView, "status" | "running" | "killFile">): { label: string; level: "ok" | "warn" | "bad" | "off" } {
  const s = v.status;
  if (v.killFile || s?.kill) return { label: "Stopped by the kill switch", level: "bad" };
  if (!s) return { label: "Not running, locked", level: "off" };
  if (!v.running) return { label: "Not running", level: "off" };
  if (s.on) return { label: s.mode === "test" ? "Trading real money (test mode)" : "Trading real money", level: "ok" };
  return { label: "Not trading", level: "warn" };
}

/** Every reason the trader does not trade right now, in plain words; empty when it does. */
export function gateReasons(v: Pick<OnchainView, "status" | "running" | "killFile">): string[] {
  const s = v.status;
  const out: string[] = [];
  if (v.killFile) out.push("The kill file is set. Delete reports/onchain_live/KILL on the server to allow trades again.");
  if (!s) {
    out.push("The trader is not running. It stays locked until the owner arms it on the server (docs/ONCHAIN-STAGE2.md).");
    return out;
  }
  if (s.on && v.running && !v.killFile && !s.kill) return s.gate.filter(Boolean);
  if (!v.running) out.push(s.running ? "The trader's status is more than two minutes old." : "The trader says it has stopped.");
  if (s.kill && !v.killFile) out.push("The trader reports a kill file.");
  if (s.stops.total) out.push("The total loss stop has fired.");
  if (s.stops.daily) out.push("The daily loss stop has fired; trading resumes tomorrow (UTC).");
  for (const g of s.gate) if (g && !out.includes(g)) out.push(g);
  if (out.length === 0) out.push("The trader is off.");
  return out;
}

/** The transaction on Solscan, a public block explorer. */
export function solscanTx(sig: string): string {
  return `https://solscan.io/tx/${encodeURIComponent(sig)}`;
}
