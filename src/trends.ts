// The Trends page's data (GET /api/pumpfun/trends): what is hot on pump.fun
// right now, as the lab's paper engine sees it in its own chain data
// (research/lab/lab/pumpfun_rt/trends.py writes trends.json every 12 s), and
// the DexScreener list of the trending watcher (lab.ops.trending). Read only:
// nothing here trades, and nothing reads pump.fun's site or API. The badges'
// thresholds are the lab's (trends.BADGES); the page only shows them.

import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";

export type TrendList = "hot" | "migrating" | "fresh";

export interface TrendCoin {
  mint: string;
  name: string;
  symbol: string;
  uri: string | null;
  createdMs: number | null;
  ageS: number | null;
  vol1m: number | null;
  vol5m: number | null;
  vol15m: number | null;
  sell5m: number | null;
  net5m: number | null;
  buys5m: number | null;
  sells5m: number | null;
  buyers5m: number | null;
  chg5m: number | null;
  chg15m: number | null;
  priceSol: number | null;
  mcapSol: number | null;
  mcapUsd: number | null;
  /** 0 to 1 on the curve; null once it completed. */
  progress: number | null;
  migrated: boolean;
  migrateMs: number | null;
  /** Progress gained per minute over the last 5 minutes (0.01 = one point). */
  speedPm: number | null;
  poolVol5m: number | null;
  poolTrades5m: number | null;
  /** Market cap in SOL every 30 s over the last 15 minutes. */
  spark: number[];
  pWin: number | null;
  pRug: number | null;
  p3x: number | null;
  baseWin: number | null;
  baseRug: number | null;
  base3x: number | null;
  smartN: number | null;
  creatorMigrated: number | null;
  creatorCoins: number | null;
  devSold: number | null;
  flags: string[];
  blocked: boolean;
  badges: string[];
}

export interface DexItem {
  address: string;
  chain: string;
  symbol: string;
  name: string;
  dex: string | null;
  priceUsd: number | null;
  changeH1: number | null;
  changeH24: number | null;
  volumeH24: number | null;
  liquidityUsd: number | null;
  fdv: number | null;
  ageH: number | null;
  pairUrl: string | null;
  flags: string[];
}

export interface DexView {
  updatedMs: number | null;
  status: string | null;
  caveat: string | null;
  items: DexItem[];
}

export interface TrendsView {
  /** The engine's chain clock at the snapshot. */
  t: number | null;
  /** When the file was written (wall clock). */
  writtenMs: number | null;
  solUsd: number | null;
  tracked: number | null;
  lists: Record<TrendList, TrendCoin[]>;
  models: { win: boolean; rug: boolean; p3x: boolean };
  /** Badge id to what it needs, in the lab's words. */
  badges: Record<string, string>;
  note: string | null;
  dex: DexView | null;
  /** Whether the engine wrote anything at all. */
  present: boolean;
}

/** The engine writes every 12 s; after this the page says the view is old. */
export const STALE_MS = 90_000;
export const TRENDS_POLL_MS = 10_000;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const obj = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});

function coin(r: unknown): TrendCoin | null {
  const o = obj(r);
  const mint = str(o.mint);
  if (!mint) return null;
  return {
    mint,
    name: str(o.name),
    symbol: str(o.symbol),
    uri: str(o.uri) || null,
    createdMs: num(o.created_ms),
    ageS: num(o.age_s),
    vol1m: num(o.vol_1m),
    vol5m: num(o.vol_5m),
    vol15m: num(o.vol_15m),
    sell5m: num(o.sell_5m),
    net5m: num(o.net_5m),
    buys5m: num(o.buys_5m),
    sells5m: num(o.sells_5m),
    buyers5m: num(o.buyers_5m),
    chg5m: num(o.chg_5m),
    chg15m: num(o.chg_15m),
    priceSol: num(o.price_sol),
    mcapSol: num(o.mcap_sol),
    mcapUsd: num(o.mcap_usd),
    progress: num(o.progress),
    migrated: o.migrated === true,
    migrateMs: num(o.migrate_ms),
    speedPm: num(o.speed_pm),
    poolVol5m: num(o.pool_vol_5m),
    poolTrades5m: num(o.pool_trades_5m),
    spark: Array.isArray(o.spark) ? o.spark.filter((x): x is number => typeof x === "number" && Number.isFinite(x)) : [],
    pWin: num(o.p_win),
    pRug: num(o.p_rug),
    p3x: num(o.p_3x),
    baseWin: num(o.base_win),
    baseRug: num(o.base_rug),
    base3x: num(o.base_3x),
    smartN: num(o.smart_n),
    creatorMigrated: num(o.creator_migrated),
    creatorCoins: num(o.creator_coins),
    devSold: num(o.dev_sold),
    flags: strs(o.flags),
    blocked: o.blocked === true,
    // A blocked coin is never highlighted, whatever the file says.
    badges: o.blocked === true ? [] : strs(o.badges),
  };
}

function dexItem(r: unknown): DexItem | null {
  const o = obj(r);
  const address = str(o.address);
  if (!address) return null;
  const url = str(o.pair_url);
  return {
    address,
    chain: str(o.chain) || "solana",
    symbol: str(o.symbol),
    name: str(o.name),
    dex: str(o.dex) || null,
    priceUsd: num(o.price_usd),
    changeH1: num(o.change_h1),
    changeH24: num(o.change_h24),
    volumeH24: num(o.volume_h24),
    liquidityUsd: num(o.liquidity_usd),
    fdv: num(o.fdv),
    ageH: num(o.age_h),
    pairUrl: url.startsWith("https://") ? url : null,
    flags: strs(o.flags),
  };
}

const list = <T,>(v: unknown, f: (r: unknown) => T | null): T[] => (Array.isArray(v) ? v.map(f).filter((x): x is T => x != null) : []);

/** The endpoint's answer, every field checked; odd entries are dropped. */
export function parseTrends(raw: unknown): TrendsView {
  const top = obj(raw);
  const t = obj(top.trends);
  const lists = obj(t.lists);
  const m = obj(t.models);
  const badges: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj(t.badges))) if (typeof v === "string") badges[k] = v;
  const d = top.dexscreener == null ? null : obj(top.dexscreener);
  return {
    t: num(t.t),
    writtenMs: num(t.written_ms),
    solUsd: num(t.sol_usd),
    tracked: num(t.tracked),
    lists: { hot: list(lists.hot, coin), migrating: list(lists.migrating, coin), fresh: list(lists.fresh, coin) },
    models: { win: m.win === true, rug: m.rug === true, p3x: m.p3x === true },
    badges,
    note: str(t.note) || null,
    dex: d ? { updatedMs: num(d.updatedMs), status: str(d.status) || null, caveat: str(d.caveat) || null, items: list(d.items, dexItem) } : null,
    present: top.trends != null && typeof top.trends === "object",
  };
}

/** The page reads the server's files; only the connected backend has them. */
export function canReadTrends(): boolean {
  return liveMode() === "server";
}

export async function fetchTrends(): Promise<TrendsView> {
  if (!canReadTrends()) throw new Error("The Trends page needs the connected backend on the server.");
  const r = await fetch(`${serverUrl()}/api/pumpfun/trends`, { cache: "no-store" });
  if (!r.ok) throw new Error(`backend answered ${r.status}`);
  return parseTrends(await r.json());
}

// ── what a row shows ──

export type BadgeTone = "good" | "bad" | "warn" | "accent";

export interface BadgeUi {
  id: string;
  label: string;
  tone: BadgeTone;
  why: string;
}

const BADGE_TEXT: Record<string, { label: (c: TrendCoin) => string; tone: BadgeTone; why: string }> = {
  win_high: { label: (c) => `P(win) ${pct(c.pWin)}`, tone: "good", why: "The selection model rates a buy at the migration above most others." },
  win_low: { label: (c) => `P(win) ${pct(c.pWin)}`, tone: "warn", why: "The selection model rates a buy at the migration well below its usual rate." },
  rug_risk: { label: (c) => `Rug risk ${pct(c.pRug)}`, tone: "bad", why: "The selection model sees a high chance the pool's price halves within a minute of the migration." },
  p3x_high: { label: (c) => `P(3x) ${pct(c.p3x)}`, tone: "accent", why: "The early model sees a high chance the price triples within the hour. It was trained on the first minute and the 25, 50 and 75 % marks, so it is a rough read later." },
  smart: { label: (c) => `${c.smartN ?? 0} smart buyers`, tone: "accent", why: "Early buyers whose earlier early buys often completed their curve." },
  creator_mig: { label: (c) => `Creator: ${c.creatorMigrated ?? 0} migrated`, tone: "accent", why: "The creator made earlier coins that completed their curve." },
  dev_sold: { label: (c) => `Dev sold ${pct(c.devSold, 0)}`, tone: "warn", why: "The creator sold a large share of what it bought." },
};

/** The row's badges with their words; the lab's rule (from the file) follows the short explanation. */
export function badgeUi(c: TrendCoin, rules: Record<string, string> = {}): BadgeUi[] {
  if (c.blocked) return [];
  return c.badges.flatMap((id) => {
    const b = BADGE_TEXT[id];
    if (!b) return [];
    const rule = rules[id];
    return [{ id, label: b.label(c), tone: b.tone, why: rule ? `${b.why} Rule: ${rule}.` : b.why }];
  });
}

const FLAG_TEXT: Record<string, string> = {
  mayhem: "Mayhem mode",
  cashback: "Cashback",
  quote: "Quote not SOL",
  irregular: "Irregular curve",
};

export function flagText(f: string): string {
  return FLAG_TEXT[f] ?? f;
}

/** 0.412 as "41 %"; "n/a" when unknown. */
export function pct(v: number | null | undefined, dp = 0): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  return `${(v * 100).toFixed(dp)} %`;
}

/** A change as "+23 %" or "-8.5 %"; "n/a" when unknown. */
export function changeText(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const p = v * 100;
  const s = Math.abs(p) >= 10 ? Math.abs(p).toFixed(0) : Math.abs(p).toFixed(1);
  return `${p > 0 ? "+" : p < 0 ? "-" : ""}${s} %`;
}

/** SOL with sensible digits: "12.3 SOL", "0.45 SOL". */
export function solText(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const a = Math.abs(v);
  return `${v < 0 ? "-" : ""}${a >= 100 ? a.toFixed(0) : a >= 10 ? a.toFixed(1) : a.toFixed(2)} SOL`;
}

/** Dollars compact: "$9.1k", "$1.2M", "$640". */
export function usdShort(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const a = Math.abs(v);
  const s = a >= 1e9 ? `${(a / 1e9).toFixed(1)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `${(a / 1e3).toFixed(1)}k` : a.toFixed(0);
  return `${v < 0 ? "-" : ""}$${s}`;
}

/** An age as "45 s", "12 min", "3 h". */
export function ageText(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s) || s < 0) return "n/a";
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86_400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86_400)} d`;
}

/** "updated 14:05:09" in the reader's 24 hour clock; "" without a time. */
export function updatedClock(ms: number | null | undefined): string {
  if (!ms || !Number.isFinite(ms)) return "";
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `updated ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** Whether the engine's file is older than STALE_MS. */
export function isStale(v: TrendsView, now = Date.now()): boolean {
  return v.writtenMs == null || now - v.writtenMs > STALE_MS;
}

export function dexscreenerToken(mint: string): string {
  return `https://dexscreener.com/solana/${encodeURIComponent(mint)}`;
}

/** A metadata URI that is itself an image (or an ipfs:// one, through the public gateway); null otherwise. */
export function directImage(uri: string | null | undefined): string | null {
  if (!uri) return null;
  const u = uri.startsWith("ipfs://") ? `https://ipfs.io/ipfs/${uri.slice(7)}` : uri;
  if (!u.startsWith("https://")) return null;
  return /\.(png|jpe?g|gif|webp|avif|svg)(\?|$)/i.test(u) ? u : null;
}

/** The image named by a token's metadata JSON (its "image" field), https or ipfs only. */
export function imageOfMetadata(meta: unknown): string | null {
  const img = str(obj(meta).image);
  if (img.startsWith("ipfs://")) return `https://ipfs.io/ipfs/${img.slice(7)}`;
  return img.startsWith("https://") ? img : null;
}
