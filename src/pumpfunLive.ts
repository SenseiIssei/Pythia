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
  /** "wallet": the limits follow the wallet (stake as a share of it); "fixed" or missing: the SOL amounts above. */
  limits?: LimitsKind | null;
  /** The stake per trade as a share of the base the file sets; null: the code default (10 %). */
  stakeShare?: number | null;
}

/** Where a bot's limits come from: the wallet (a share of it, no daily loss or total budget) or fixed amounts. */
export type LimitsKind = "wallet" | "fixed";

/** Where the share in force comes from: the code default, the confirmation file, or the owner's override in the app. */
export type ShareSource = "default" | "ack" | "owner";

/** The owner's master controls as the bot applies them (its status file's `control`, both bots). */
export interface StatusControl {
  limits: LimitsKind | null;
  /** The share in force (on-chain: null while the file's book size rules). */
  share: number | null;
  shareSource: ShareSource | null;
  /** When the owner set it (only for shareSource "owner"). */
  shareSince: number | null;
  /** The file's share or the default (pump.fun); null on-chain. */
  ackShare: number | null;
  /** The owner's value from control.json, even when it could only lower. */
  requestedShare: number | null;
  paused: boolean;
  pausedSince: number | null;
  /** Plain words, e.g. why a requested share was lowered. */
  note: string | null;
  /** False when control.json was malformed (the last good values stay). */
  controlOk: boolean;
  /** On-chain: the USD per book in force and the file's. */
  bookUsd?: number | null;
  ackBookUsd?: number | null;
}

/** The wallet is below what one trade needs. */
export interface LowFunds {
  have: number | null;
  need: number | null;
  unit: string | null;
}

/** The owner's control file as the engine wrote it (shown while the service is down). */
export interface ControlFile {
  share: number | null;
  paused: boolean;
  setAt: number | null;
  shareSetAt: number | null;
  pausedAt: number | null;
  /** pump.fun with limits=wallet: the drawdown brake (the engine reads a missing one as on). */
  brake?: boolean | null;
  brakeSetAt?: number | null;
  /** pump.fun with limits=wallet: no buys under this base in SOL (0.25 while unset). */
  floorSol?: number | null;
}

/** What the Master panel posts; a missing field keeps the current value. */
export interface ControlPatch {
  share?: number;
  resetShare?: boolean;
  paused?: boolean;
  /** pump.fun only: the drawdown brake on or off (applies with limits=wallet). */
  brake?: boolean;
}

/** The engine's answer to reading or writing the control file. */
export interface ControlAnswer extends ControlFile {
  effective: StatusControl | null;
}

export interface PumpfunLimits {
  maxTradeSol: number | null;
  maxOpen: number | null;
  maxExposureSol: number | null;
  maxDailyLossSol: number | null;
  maxTotalSol: number | null;
  kind?: LimitsKind | null;
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
  /** The stake per trade now and why ("50 % of 0.90 SOL (limits: wallet)"). */
  stake?: { sol: number | null; why: string | null; share?: number | null } | null;
  control?: StatusControl | null;
  low?: LowFunds | null;
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
  /** One SOL in euro from Kraken's public ticker, read by the backend; null when it could not be read. */
  solEur?: SolEur | null;
  /** One euro in US dollars (Kraken's EURUSD, same shape) for the Real money page; null when it could not be read. */
  eurUsd?: SolEur | null;
  /** The owner's control file (share, Stop), read even while the service is down. */
  control?: ControlFile | null;
}

export interface SolEur {
  /** The last trade, euro per SOL. */
  price: number;
  /** Today's opening price (00:00 UTC). */
  open: number;
  /** When it was read (ms). */
  t: number;
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

/** The owner's master controls: the share of the wallet per trade and Stop / Start (not the kill switch). */
export async function pumpfunControl(patch: ControlPatch): Promise<ControlAnswer> {
  if (!canControl()) throw new Error("The master controls work through the connected backend on the server.");
  return asJson<ControlAnswer>(
    await fetch(`${serverUrl()}/api/pumpfun/live/control`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  );
}

/** The owner's block list (<data>/pumpfun_rt/blocked-mints.txt): coins the live bot and its paper twin never buy. */
export type BlockKind = "mint" | "creator" | "symbol" | "name" | "match" | "category";

export interface BlockEntry {
  entry: string;
  kind: BlockKind;
  value: string;
}

export interface BlockList {
  path: string;
  entries: BlockEntry[];
  /** Lines the bot ignores (not a mint, creator:, symbol:, name:, match: or category: entry). */
  ignored: string[];
  /** The name categories never bought: the category: lines, or the defaults while there is none. */
  categories?: { blocked: string[]; default: boolean; codes: string[] };
}

/** The live classifier's name categories (categorize.CATS) and those blocked while the list has no category: line. */
export const BLOCK_CATEGORIES = ["copycat", "celebrity", "ai", "animal", "generic", "scam"] as const;
export type BlockCategory = (typeof BLOCK_CATEGORIES)[number];
export const BLOCK_CATEGORIES_DEFAULT: readonly BlockCategory[] = ["copycat", "celebrity", "scam"];
export const BLOCK_CATEGORY_LABEL: Record<BlockCategory, string> = {
  copycat: "Brands and copies",
  celebrity: "Celebrities",
  ai: "AI",
  animal: "Animals",
  generic: "Generic",
  scam: "Scam patterns",
};
export const BLOCK_CATEGORY_HINT: Record<BlockCategory, string> = {
  copycat: "Famous brands, products, apps, games, AI products, other coins, copies of trending names (Apple, ChatGPT, GTA6).",
  celebrity: "Real people: politicians, streamers, founders, athletes, musicians (Biden, IShowSpeed, MrBeast).",
  ai: "AI themes without a brand.",
  animal: "Animal memes.",
  generic: "Everything else.",
  scam: "Likely scams: airdrop, official, v2, presale, random characters.",
};

/** The blocked categories of a list: what the server says, else the category: entries, else the defaults. */
export function blockedCategories(list: BlockList | null): { blocked: BlockCategory[]; isDefault: boolean } {
  const known = (c: string): c is BlockCategory => (BLOCK_CATEGORIES as readonly string[]).includes(c);
  const listed = list?.categories ? list.categories.blocked : (list?.entries ?? []).filter((e) => e.kind === "category").map((e) => e.value);
  const own = BLOCK_CATEGORIES.filter((c) => listed.includes(c) && known(c));
  const isDefault = list?.categories ? list.categories.default : own.length === 0;
  return { blocked: isDefault && !list?.categories ? [...BLOCK_CATEGORIES_DEFAULT] : own, isDefault };
}

/** The change one click on a category makes: block it, unblock it, or why not (the last one stays). */
export function categoryToggle(code: BlockCategory, blocked: readonly BlockCategory[]): { add: string } | { remove: string } | { error: string } {
  if (!blocked.includes(code)) return { add: `category:${code}` };
  if (blocked.length <= 1) return { error: "At least one category stays blocked." };
  return { remove: `category:${code}` };
}

export const BLOCK_KIND_LABEL: Record<BlockKind, string> = { mint: "Mint", creator: "Creator", symbol: "Symbol", name: "Name", match: "Contains", category: "Category" };
/** The kinds the form takes as text; categories are switched on and off on their own row. */
export const BLOCK_FORM_KINDS: BlockKind[] = ["mint", "creator", "symbol", "name", "match"];
/** What each kind blocks, for the form (match: the celebrity copies, 2026-10-23). */
export const BLOCK_KIND_HINT: Record<BlockKind, string> = {
  mint: "This one coin.",
  creator: "Every coin this wallet creates.",
  symbol: "Every coin with exactly this symbol.",
  name: "Every coin with exactly this name.",
  match: "Every coin whose name or symbol contains this text (spacex blocks SpaceX AI and $SPACEX). At least 3 letters or digits.",
  category: "Every coin whose name the classifier puts in this category.",
};
const BLOCK_TEXT_MAX = 64;
const BLOCK_MATCH_MIN = 3;
const BASE58 = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

/** Letters and digits only, lower case, as the bot compares symbols and names ("$SHEKEL" is "shekel"). */
export function blockNorm(s: string): string {
  return Array.from(s)
    .filter((c) => /[\p{L}\p{N}]/u.test(c))
    .join("")
    .toLowerCase();
}

/** The line one entry is written as, or why it is not one (the server checks again). */
export function blockLine(kind: BlockKind, raw: string): { line: string } | { error: string } {
  const v = raw.trim();
  if (!v) return { error: "Enter a value." };
  if (/[#\u0000-\u001f\u007f]/.test(v)) return { error: "No # and no line break." };
  if (kind === "category") {
    const c = v.toLowerCase();
    return (BLOCK_CATEGORIES as readonly string[]).includes(c) ? { line: `category:${c}` } : { error: `A category is one of ${BLOCK_CATEGORIES.join(", ")}.` };
  }
  if (kind === "mint" || kind === "creator") {
    if (!BASE58.test(v)) return { error: `Not a ${kind === "mint" ? "mint" : "wallet"} address (base58, 32 to 44 characters).` };
    return { line: kind === "mint" ? v : `creator:${v}` };
  }
  if (kind === "match" && Array.from(blockNorm(v)).length < BLOCK_MATCH_MIN) return { error: `A match needs at least ${BLOCK_MATCH_MIN} letters or digits.` };
  if (!blockNorm(v)) return { error: `A ${kind} needs at least one letter or digit.` };
  if (Array.from(v).length > BLOCK_TEXT_MAX) return { error: `A ${kind} has at most ${BLOCK_TEXT_MAX} characters.` };
  return { line: `${kind}:${v}` };
}

export async function pumpfunBlocked(): Promise<BlockList> {
  if (!canControl()) throw new Error("The block list works through the connected backend on the server.");
  return asJson<BlockList>(await fetch(`${serverUrl()}/api/pumpfun/live/blocked`));
}

/** Add or remove one entry; the server writes the file atomically and answers with the list. */
export async function changePumpfunBlocked(change: { add: string } | { remove: string }): Promise<BlockList> {
  if (!canControl()) throw new Error("The block list works through the connected backend on the server.");
  return asJson<BlockList>(
    await fetch(`${serverUrl()}/api/pumpfun/live/blocked`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(change),
    }),
  );
}

// ── what the page says ──

export function sol(v: number | null | undefined, signed = false, dp = 4): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const s = Math.abs(v).toFixed(dp);
  return `${signed ? (v > 0 ? "+" : v < 0 ? "-" : "") : v < 0 ? "-" : ""}${s} SOL`;
}

/** A SOL amount in euro at the given rate, in the reader's locale ("9,87 €"); "" without a rate. */
export function eur(v: number | null | undefined, rate: SolEur | null | undefined, signed = false): string {
  if (v == null || !Number.isFinite(v) || !rate || !(rate.price > 0)) return "";
  const x = v * rate.price;
  const abs = Math.abs(x) < 0.005 ? 0 : x;
  const s = Math.abs(abs).toLocaleString(undefined, { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${signed ? (abs > 0 ? "+" : abs < 0 ? "-" : "") : abs < 0 ? "-" : ""}${s}`;
}

/** SOL's move in euro since today's open, as a share (0.034 = +3.4 %); null without a rate. */
export function solEurChange(rate: SolEur | null | undefined): number | null {
  return rate && rate.open > 0 ? rate.price / rate.open - 1 : null;
}

export type Tone = "up" | "down" | "flat";

export function tone(v: number | null | undefined): Tone {
  return v == null || v === 0 ? "flat" : v > 0 ? "up" : "down";
}

/** What the owner reads for the live test's mode: the files and the code say "test", the app says Alpha phase. */
export const ALPHA_PHASE = "Alpha phase";

export function modeWords(mode: string | null | undefined): string {
  return mode === "test" ? ALPHA_PHASE : mode === "full" ? "Full" : (mode ?? "");
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
  if (v.control?.paused || s.control?.paused) {
    return { label: "Paused by you", level: "warn", detail: "No new buys; open positions are still sold by their exits. Start again in the Master panel." };
  }
  if (s.stops.total) return { label: "Total budget used up", level: "bad", detail: "The total budget stop fired; no more buys. Only a new confirmation file changes that." };
  if (s.stops.daily) return { label: "Daily loss stop", level: "warn", detail: "No more buys until tomorrow (UTC)." };
  if (s.on) {
    return { label: s.mode === "test" ? `Trading real money (${ALPHA_PHASE})` : "Trading real money", level: "ok", detail: `${s.rule ?? "?"}, every trade is posted to Telegram.` };
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

/** The badge of a coin on the live chart: buying, open, sold, or not bought (the price ran away before the buy). */
export function coinBadge(c: Pick<FeedCoin, "state" | "exit">): "buying" | "open" | "sold" | "not bought" {
  if (c.state === "skipped") return "not bought";
  if (!c.exit) return c.state === "pending" ? "buying" : "open";
  return "sold";
}

export interface TradeStats {
  n: number;
  wins: number;
  /** Share of trades that made money, 0 to 1; null without trades. */
  winRate: number | null;
  stakeSol: number;
  proceedsSol: number;
  pnlSol: number;
  /** Mean return per trade (0.1 = +10 %); null without returns. */
  avgRet: number | null;
  best: PumpfunTrade | null;
  worst: PumpfunTrade | null;
  avgHoldS: number | null;
  /** Running P&L after each trade, oldest first, starting at 0. */
  curve: number[];
}

/** What the closed trades add up to. The trades come newest first, as the service writes them. */
export function tradeStats(trades: readonly PumpfunTrade[]): TradeStats {
  const oldest = [...trades].sort((a, b) => (a.exitMs ?? 0) - (b.exitMs ?? 0));
  const curve = [0];
  let pnl = 0;
  let stake = 0;
  let proceeds = 0;
  let wins = 0;
  let best: PumpfunTrade | null = null;
  let worst: PumpfunTrade | null = null;
  const rets: number[] = [];
  const holds: number[] = [];
  for (const t of oldest) {
    const p = t.pnlSol ?? 0;
    pnl += p;
    curve.push(pnl);
    stake += t.stakeSol ?? 0;
    proceeds += t.proceedsSol ?? 0;
    if (p > 0) wins += 1;
    if (best == null || p > (best.pnlSol ?? 0)) best = t;
    if (worst == null || p < (worst.pnlSol ?? 0)) worst = t;
    if (t.ret != null && Number.isFinite(t.ret)) rets.push(t.ret);
    if (t.holdS != null && Number.isFinite(t.holdS)) holds.push(t.holdS);
  }
  const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
  return {
    n: oldest.length,
    wins,
    winRate: oldest.length ? wins / oldest.length : null,
    stakeSol: stake,
    proceedsSol: proceeds,
    pnlSol: pnl,
    avgRet: mean(rets),
    best,
    worst,
    avgHoldS: mean(holds),
    curve,
  };
}

/** A holding time in words: "45 s", "12 min", "3 h 05 min". */
export function holdWords(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s) || s < 0) return "n/a";
  if (s < 60) return `${Math.round(s)} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

/** The token's page on Solscan, a public block explorer. */
export function solscanToken(mint: string): string {
  return `https://solscan.io/token/${encodeURIComponent(mint)}`;
}

/** A mint or address shortened for a row: first and last four characters. */
export function short(a: string | null | undefined): string {
  if (!a) return "";
  return a.length > 12 ? `${a.slice(0, 4)}...${a.slice(-4)}` : a;
}

// ── the live feed (GET /api/pumpfun/live/ws; the lab's live_feed.py) ──

/** One trade on a coin the bot holds: time (ms), price (SOL per token), SOL traded, 1 for a buy. */
export type FeedPoint = [number, number, number, 0 | 1];

export interface FeedExit {
  ms: number | null;
  price: number | null;
  why: string | null;
  ret: number | null;
  pnl_sol: number | null;
}

/** A coin the bot holds now or closed in the last minutes (snake_case: the service's file as written). */
export interface FeedCoin {
  mint: string;
  pid: number | null;
  rule: string | null;
  symbol: string | null;
  name: string | null;
  venue: string | null;
  state: string | null;
  signal_ms: number | null;
  land_ms: number | null;
  entry_price: number | null;
  signal_price: number | null;
  cost_sol: number;
  mark_sol: number | null;
  tp: number | null;
  sl: number | null;
  time_s: number | null;
  exit: FeedExit | null;
  points: FeedPoint[];
}

export interface PumpfunFeed {
  t: number;
  coins: FeedCoin[];
  on: boolean | null;
  balance_sol: number | null;
  balance_t: number | null;
  pnl_today_sol: number | null;
  trades_today: number | null;
  wins_today: number | null;
  pnl_total_sol: number | null;
  trades_total: number | null;
  exposure_sol: number | null;
}

export interface Candle {
  t: number;
  open: number;
  high: number;
  low: number;
  close: number;
  /** SOL bought and sold in the candle. */
  buys: number;
  sells: number;
}

/** Trades into candles of `bucketMs`. Each opens at the previous close (the first at its first trade);
 *  a bucket without trades is flat at the last price. */
export function candles(points: readonly FeedPoint[], bucketMs: number, untilMs?: number): Candle[] {
  if (points.length === 0 || bucketMs <= 0) return [];
  const pts = [...points].sort((a, b) => a[0] - b[0]);
  const first = Math.floor(pts[0][0] / bucketMs) * bucketMs;
  const last = Math.floor(Math.max(pts[pts.length - 1][0], untilMs ?? 0) / bucketMs) * bucketMs;
  const out: Candle[] = [];
  let i = 0;
  let prev = pts[0][1];
  for (let t = first; t <= last && out.length < 2_000; t += bucketMs) {
    const c: Candle = { t, open: prev, high: prev, low: prev, close: prev, buys: 0, sells: 0 };
    for (; i < pts.length && pts[i][0] < t + bucketMs; i++) {
      const [, price, solAmt, buy] = pts[i];
      c.high = Math.max(c.high, price);
      c.low = Math.min(c.low, price);
      c.close = price;
      if (buy) c.buys += solAmt;
      else c.sells += solAmt;
    }
    prev = c.close;
    out.push(c);
  }
  return out;
}

/** The return a coin's price stands at against what the bot paid per token (fees included). */
export function coinReturn(c: FeedCoin): number | null {
  const last = c.points.length ? c.points[c.points.length - 1][1] : null;
  if (c.exit?.ret != null) return c.exit.ret;
  if (c.mark_sol != null && c.cost_sol > 0) return c.mark_sol / c.cost_sol - 1;
  return last != null && c.entry_price ? last / c.entry_price - 1 : null;
}

/** Seconds left before the time stop sells, or null when it does not apply. */
export function timeStopLeft(c: FeedCoin, nowMs: number): number | null {
  if (c.exit || c.land_ms == null || c.time_s == null) return null;
  return Math.max(0, Math.round((c.land_ms + c.time_s * 1000 - nowMs) / 1000));
}

export function dexscreener(mint: string): string {
  return `https://dexscreener.com/solana/${encodeURIComponent(mint)}`;
}

/** How the page stays current: the socket, or reading every POLL_MS where it cannot be held open. */
export type SocketState = "connecting" | "live" | "polling" | "retrying" | "off";

/** Reading interval without a socket, and while the tab is hidden. */
export const POLL_MS = 1_500;
const HIDDEN_POLL_MS = 6_000;
/** Socket attempts that never opened before the page reads instead (a proxy that passes no upgrade). */
const SOCKET_TRIES = 2;

export async function pumpfunFeed(): Promise<PumpfunFeed | null> {
  return asJson<PumpfunFeed | null>(await fetch(`${serverUrl()}/api/pumpfun/live/feed`, { cache: "no-store" }));
}

/** The page's WebSocket, or null where there is no server (the desktop app polls instead). */
export function pumpfunSocketUrl(): string | null {
  if (liveMode() !== "server") return null;
  const base = serverUrl();
  if (!base) return null;
  const abs = /^https?:\/\//.test(base) ? base : `${globalThis.location?.origin ?? ""}${base.startsWith("/") ? "" : "/"}${base}`;
  return `${abs.replace(/\/$/, "").replace(/^http/, "ws")}/api/pumpfun/live/ws`;
}

/**
 * Keeps the page current while it is open: one socket that hands on every new view and feed as it
 * comes, tried again when it drops (1 s, doubling to 30 s). Where the socket never opens (the panel's
 * proxy passes no upgrade), it reads the view and the feed every POLL_MS instead. Returns the closer.
 */
export function watchPumpfun(handlers: {
  onView: (v: PumpfunView) => void;
  onFeed: (f: PumpfunFeed | null) => void;
  onState: (s: SocketState) => void;
}): () => void {
  const url = pumpfunSocketUrl();
  if (!url) {
    handlers.onState("off");
    return () => {};
  }
  let ws: WebSocket | null = null;
  let closed = false;
  let wait = 1_000;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let neverOpened = 0;
  let lastView = "";
  let lastFeed = "";

  const poll = async () => {
    if (closed) return;
    try {
      const [view, feed] = await Promise.all([pumpfunLive(), pumpfunFeed()]);
      if (closed) return;
      const vt = JSON.stringify(view);
      if (vt !== lastView) {
        lastView = vt;
        handlers.onView(view);
      }
      const ft = JSON.stringify(feed);
      if (ft !== lastFeed) {
        lastFeed = ft;
        handlers.onFeed(feed);
      }
      handlers.onState("polling");
    } catch {
      if (!closed) handlers.onState("retrying");
    }
    if (!closed) timer = setTimeout(() => void poll(), globalThis.document?.hidden ? HIDDEN_POLL_MS : POLL_MS);
  };

  const open = () => {
    if (closed) return;
    handlers.onState("connecting");
    let opened = false;
    ws = new WebSocket(url);
    ws.onopen = () => {
      opened = true;
      neverOpened = 0;
      wait = 1_000;
      handlers.onState("live");
    };
    ws.onmessage = (e) => {
      try {
        const m = JSON.parse(String(e.data)) as { kind: string; data: unknown };
        if (m.kind === "view") handlers.onView(m.data as PumpfunView);
        else if (m.kind === "feed") handlers.onFeed((m.data as PumpfunFeed | null) ?? null);
      } catch {
        /* a broken frame: the next one replaces it */
      }
    };
    ws.onclose = () => {
      if (closed) return;
      if (!opened && ++neverOpened >= SOCKET_TRIES) {
        void poll();
        return;
      }
      handlers.onState("retrying");
      timer = setTimeout(open, wait);
      wait = Math.min(wait * 2, 30_000);
    };
  };
  open();
  return () => {
    closed = true;
    if (timer != null) clearTimeout(timer);
    ws?.close();
  };
}
