// Pure helpers for the pages about real money: Live (arming, real positions,
// checklists, execution costs, market data) and Money (account totals,
// holdings). No React here, so every rule is covered by a test.

import type { Balance, LiveStatus, PositionView, WalletAccount } from "../types";
import type { DataStatus } from "../dataHealth";
import { money } from "../design/format";

const MINUS = "−";

/** Where orders go right now, in one word. "real" is the only state that spends money. */
export type LiveMood = "off" | "dry" | "paper" | "real";

export function liveMood(l: Pick<LiveStatus, "armed" | "paper" | "dryRun">): LiveMood {
  if (!l.armed) return "off";
  if (l.dryRun) return "dry";
  return l.paper ? "paper" : "real";
}

/** The words for a live state: a short value, a badge word that fits a phone, and the line that explains it. */
export function liveMoodWords(m: LiveMood): { value: string; badge: string; detail: string } {
  switch (m) {
    case "real":
      return { value: "Armed", badge: "Real money", detail: "Orders from Live strategies go to your live account" };
    case "paper":
      return { value: "Armed", badge: "Paper", detail: "Paper endpoint, no real money" };
    case "dry":
      return { value: "Armed", badge: "Dry-run", detail: "Dry-run, nothing is sent" };
    default:
      return { value: "Off", badge: "Simulated", detail: "Everything is simulated" };
  }
}

/** The positions bought with real money: how many, what they are worth, and their open result. */
export function realExposure(positions: Pick<PositionView, "live" | "qty" | "lastPrice" | "unrealized">[]): {
  count: number;
  value: number;
  unrealized: number;
} {
  const real = positions.filter((p) => p.live);
  return {
    count: real.length,
    value: real.reduce((a, p) => a + Math.abs(p.qty) * p.lastPrice, 0),
    unrealized: real.reduce((a, p) => a + p.unrealized, 0),
  };
}

/** The typed phrase matches, ignoring case and outer spaces. */
export function phraseMatches(typed: string, phrase: string): boolean {
  return typed.trim().toUpperCase() === phrase.toUpperCase();
}

/** Arming is offered only with the phrase typed, while disarmed, and with at least one venue on. */
export function canArmNow(typed: string, phrase: string, armed: boolean, venueCount: number): boolean {
  return phraseMatches(typed, phrase) && !armed && venueCount > 0;
}

/** Whole seconds since a moment, never negative. */
export function secondsSince(ms: number, now: number): number {
  return Math.max(0, Math.round((now - ms) / 1000));
}

/** A dollar amount the broker sent as text: "$1,234.50", or the text itself when it is not a number. */
export function amountText(v: string): string {
  const n = Number(v);
  return v.trim() === "" || !Number.isFinite(n) ? v : money(n);
}

/** Basis points with a real sign: "+1.2 bps", "−0.4 bps", "0.0 bps". */
export function signedBps(n: number, dp = 1): string {
  if (!Number.isFinite(n)) return "n/a";
  const abs = Math.abs(n).toFixed(dp);
  if (Number(abs) === 0) return `${(0).toFixed(dp)} bps`;
  return `${n < 0 ? MINUS : "+"}${abs} bps`;
}

/** How many checklist steps are done. */
export function readyCount(steps: { ok: boolean }[]): { done: number; total: number; all: boolean } {
  const done = steps.filter((s) => s.ok).length;
  return { done, total: steps.length, all: steps.length > 0 && done === steps.length };
}

/** The market data status as a calm badge: tone and a word in sentence case. */
export function dataBadge(s: DataStatus | null): { tone: "good" | "warn" | "bad"; word: string } | null {
  if (!s) return null;
  if (s.tone === "red") return { tone: "bad", word: "Stale" };
  if (s.tone === "amber") {
    const l = s.label.toUpperCase();
    return { tone: "warn", word: l.includes("FAILOVER") ? "On a fallback" : l.includes("CHECK") ? "Check" : "Partly stale" };
  }
  return { tone: "good", word: "Fresh" };
}

/** Crypto amounts need more decimals than money, but not eight zeros of noise. */
export function trimQty(n: number): string {
  if (!Number.isFinite(n)) return "n/a";
  if (n === 0) return "0";
  const sign = n < 0 ? MINUS : "";
  const abs = Math.abs(n);
  if (abs >= 1) return sign + abs.toLocaleString("en-US", { maximumFractionDigits: 4 });
  return sign + abs.toFixed(8).replace(/0+$/, "").replace(/\.$/, "");
}

/** The coins actually held in an account. */
export function heldBalances(balances: Balance[]): Balance[] {
  return balances.filter((b) => b.total > 0);
}

/** How the accounts split: all, the ones Pythia can trade in, the watch-only ones, the ones that failed to read. */
export function walletCounts(accounts: Pick<WalletAccount, "canTrade" | "error">[]): {
  total: number;
  canTrade: number;
  watchOnly: number;
  failed: number;
} {
  return {
    total: accounts.length,
    canTrade: accounts.filter((a) => a.canTrade).length,
    watchOnly: accounts.filter((a) => !a.canTrade).length,
    failed: accounts.filter((a) => !!a.error).length,
  };
}

/** A long address cut for a short message: the first ten characters and an ellipsis. */
export function shortAddress(a: string): string {
  return a.length > 10 ? `${a.slice(0, 10)}…` : a;
}
