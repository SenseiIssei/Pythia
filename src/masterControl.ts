// The owner's master controls of both live bots, in plain logic (the Master
// panel, components/MasterPanel.tsx): the share of the wallet a bot may use,
// Stop (no new buys from now) and Start. The engine writes the control file,
// the bots read it every 2 seconds. Separate from the kill switch, which the
// app can only set. Nothing here moves money.

import type { ControlFile, ControlPatch, LimitsKind, LowFunds, StatusControl } from "./pumpfunLive";

export type Bot = "pumpfun" | "onchain";

/** The share buttons: 5, 10, 25, 50, 75 and 100 % of the wallet. */
export const SHARE_BUTTONS: readonly number[] = [0.05, 0.1, 0.25, 0.5, 0.75, 1.0];

/** Raising the share above this asks first. */
export const CONFIRM_ABOVE = 0.5;

/** The most the pump.fun bot's share may be without limits=wallet in the confirmation file (the code default). */
export const FIXED_MAX_SHARE = 0.1;

export type MasterAction = { kind: "share"; share: number } | { kind: "reset" } | { kind: "stop" } | { kind: "start" };

/** What the panel posts for an action. */
export function patchOf(a: MasterAction): ControlPatch {
  switch (a.kind) {
    case "share":
      return { share: a.share };
    case "reset":
      return { resetShare: true };
    case "stop":
      return { paused: true };
    case "start":
      return { paused: false };
  }
}

/** Start always asks; a share asks only when it raises above 50 %. Stop and the reset never ask. */
export function needsConfirm(a: MasterAction, current: number | null | undefined): boolean {
  if (a.kind === "start") return true;
  if (a.kind !== "share") return false;
  return a.share > CONFIRM_ABOVE + 1e-9 && (current == null || a.share > current + 1e-9);
}

/** A share in words: "25 %", "12.5 %". */
export function shareText(share: number | null | undefined): string {
  if (share == null || !Number.isFinite(share)) return "n/a";
  return `${Math.round(share * 1000) / 10} %`;
}

/** A custom percent ("12", "12.5", "12,5", "12 %") into a share; valid from 1 % to 100 %. Empty: nothing yet. */
export function parseShare(text: string): { share: number | null; error: string | null } {
  const raw = text.trim().replace(/%$/, "").trim().replace(",", ".");
  if (!raw) return { share: null, error: null };
  const v = /^\d+(\.\d+)?$/.test(raw) ? Number(raw) : NaN;
  if (!Number.isFinite(v) || v < 1 || v > 100) return { share: null, error: "A percent from 1 to 100." };
  return { share: Number((v / 100).toFixed(4)), error: null };
}

/** A time of day in local time: "14:05". */
export function hhmm(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** Where the bot's limits come from: the status, else the confirmation file; missing means fixed. */
export function limitsKind(...kinds: (LimitsKind | null | undefined)[]): LimitsKind {
  return kinds.find((k) => k === "wallet" || k === "fixed") ?? "fixed";
}

export function limitsText(kind: LimitsKind): string {
  return kind === "wallet" ? "limits: wallet" : "limits: fixed";
}

/** Where the share in force comes from, in words: "code default", "confirmation file", "your override since 14:05". */
export function shareSourceText(c: StatusControl | null | undefined, file?: ControlFile | null): string {
  if (c?.shareSource === "owner") return c.shareSince != null ? `your override since ${hhmm(c.shareSince)}` : "your override";
  if (c?.shareSource === "default") return "code default";
  if (c?.shareSource === "ack") return "confirmation file";
  if (file?.share != null) return file.shareSetAt != null ? `your override since ${hhmm(file.shareSetAt)}` : "your override";
  return "confirmation file";
}

/** Is it paused by the owner: the control file (what was asked) first, else the bot's status. */
export function isPaused(c: StatusControl | null | undefined, file?: ControlFile | null): boolean {
  return file ? file.paused : !!c?.paused;
}

/** "paused by you since 14:05", or null while not paused. */
export function pausedText(c: StatusControl | null | undefined, file?: ControlFile | null): string | null {
  if (!isPaused(c, file)) return null;
  const since = (file?.paused ? file.pausedAt : null) ?? c?.pausedSince ?? null;
  return since != null ? `paused by you since ${hhmm(since)}` : "paused by you";
}

/** The owner has an override set (the reset button shows). */
export function hasOverride(c: StatusControl | null | undefined, file?: ControlFile | null): boolean {
  return file ? file.share != null : c?.shareSource === "owner";
}

/** The highest share the owner may set: pump.fun without limits=wallet only the file's share or the default, at most 10 %. */
export function maxShare(bot: Bot, kind: LimitsKind, ackShare: number | null | undefined): number {
  if (bot === "onchain" || kind === "wallet") return 1;
  return ackShare != null && ackShare > 0 ? Math.min(ackShare, FIXED_MAX_SHARE) : FIXED_MAX_SHARE;
}

/** Why a share cannot be set, or null when it can. */
export function shareRefusal(share: number, bot: Bot, kind: LimitsKind, ackShare: number | null | undefined): string | null {
  const max = maxShare(bot, kind, ackShare);
  return share > max + 1e-9 ? `Without limits=wallet in the confirmation file the share can only be lowered, at most ${shareText(max)}.` : null;
}

/** The wallet is too small for one trade, in words; null when it is not. */
export function lowText(low: LowFunds | null | undefined): string | null {
  if (!low || low.have == null || low.need == null) return null;
  const u = low.unit ?? "SOL";
  const f = (x: number) => (u === "USD" ? `${x.toFixed(2)} USD` : `${Number(x.toFixed(4))} ${u}`);
  return `The wallet is below what one trade needs: have ${f(low.have)}, need ${f(low.need)}.`;
}

/** The question before an action that asks first. */
export function confirmQuestion(a: MasterAction, bot: Bot): string {
  if (a.kind === "start") {
    return bot === "pumpfun"
      ? "The bot buys again from the next signal, with real money, within the limits in force."
      : "The books trade again from the next signal, with real money, within the limits in force.";
  }
  if (a.kind === "share") {
    return bot === "pumpfun"
      ? `Each trade will stake ${shareText(a.share)} of the wallet. A few losing trades in a row can take most of it.`
      : `The books may use ${shareText(a.share)} of the wallet's value. A few losing trades can take a large part of it.`;
  }
  return "";
}
