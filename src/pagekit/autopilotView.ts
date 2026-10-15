// Pure helpers for the autopilot details view (src/pages/Autopilot.tsx): the
// words for its money mode, the room left to its floor, the plain "up or
// down" line, the fee share and the setup form's checks. No React here, so
// every rule is covered by a test.

import { money, signedPct } from "../design/format";
import type { AutopilotConfig } from "../types";
import type { Level } from "./format";

export type ApMode = AutopilotConfig["mode"];
export type ApChipTone = "neutral" | "accent" | "bad";

/** A typed amount or percent as a number: "$1,000", "10 %" and "1000" all read. NaN when it is not a number. */
export function parseInput(s: string): number {
  const n = Number(s.replace(/[$,\s%]/g, ""));
  return Number.isFinite(n) ? n : NaN;
}

/**
 * The label for where the money comes from. Real money is always said in
 * words and always red, in both views.
 */
export function modeLabel(mode: ApMode, simple: boolean): { tone: ApChipTone; text: string } {
  if (mode === "live") return { tone: "bad", text: simple ? "Real money" : "Live, real money" };
  if (mode === "demo") return { tone: "accent", text: "Demo account" };
  return { tone: "neutral", text: simple ? "Practice money" : "Paper" };
}

export interface FloorRoom {
  floor: number;
  /** Dollars above the floor, never below zero. */
  room: number;
  /** Share of the way from the floor to the best point that is still left, 0 to 100. */
  pct: number;
  /** For the meter: lots of room is ok, under half is near, under a fifth is over. */
  level: Level;
  /** The same in words, so colour is never the only signal. */
  word: string;
}

/**
 * How far the value can still fall before the floor stops it. Null when no
 * loss or trailing rule is set (the engine sends no floor then).
 */
export function floorRoom(equity: number, floorEquity: number | null | undefined, peakEquity: number): FloorRoom | null {
  const floor = floorEquity ?? 0;
  if (!(floor > 0)) return null;
  const raw = equity - floor;
  const span = Math.max(1e-9, peakEquity - floor);
  const pct = Math.max(0, Math.min(100, (raw / span) * 100));
  const level: Level = pct > 50 ? "ok" : pct > 20 ? "near" : "over";
  const word = level === "ok" ? "Plenty of room" : level === "near" ? "Getting closer" : "Close to the floor";
  return { floor, room: Math.max(0, raw), pct, level, word };
}

/** "No change", "Up $12.00 (+1.20%)", "Down $5.00 (−0.50%)". */
export function moveWords(pnl: number, pnlPct: number, dp = 2): string {
  if (Math.abs(pnl) < 0.005) return "No change";
  return `${pnl > 0 ? "Up" : "Down"} ${money(Math.abs(pnl), 2)} (${signedPct(pnlPct, dp)})`;
}

/** Fees as a share (0 to 1) of the gain before fees; null when there was no gain before fees. */
export function feeShare(fees: number, pnl: number): number | null {
  const gross = pnl + fees;
  return gross > 0 ? fees / gross : null;
}

/** "2.5 percentage points better", "1.0 percentage point worse". */
export function pointsWord(diff: number): string {
  const v = Math.abs(diff).toFixed(1);
  return `${v} percentage point${v === "1.0" ? "" : "s"} ${diff >= 0 ? "better" : "worse"}`;
}

/** "3 more days and 5 more trades", or "" when nothing is left. */
export function stillToGo(daysLeft: number, tradesLeft: number): string {
  const left: string[] = [];
  if (daysLeft > 0) left.push(`${daysLeft} more day${daysLeft === 1 ? "" : "s"}`);
  if (tradesLeft > 0) left.push(`${tradesLeft} more trade${tradesLeft === 1 ? "" : "s"}`);
  return left.join(" and ");
}

/** The first letter in upper case: "less than a day" reads "Less than a day". */
export function capitalise(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

/** Times and values of an equity curve, split for a chart. */
export function splitCurve(points: [number, number][]): { times: number[]; values: number[] } {
  return { times: points.map((p) => p[0]), values: points.map((p) => p[1]) };
}

export interface SetupCheck {
  capital: number;
  manual: boolean;
  chosen: number;
  lossPctOn: boolean;
  lossPct?: number | null;
  lossUsdOn: boolean;
  lossUsd?: number | null;
  tpOn: boolean;
  tp?: number | null;
  trailOn: boolean;
  trail?: number | null;
  endOn: boolean;
  endMs?: number;
  now: number;
}

const on = (n: number | null | undefined): n is number => n != null && Number.isFinite(n) && n > 0;

/** What is wrong with the start form, in plain sentences. Empty when it may start. */
export function setupProblems(c: SetupCheck): string[] {
  const out: string[] = [];
  if (!(c.capital > 0)) out.push("Enter how much it may use, more than zero.");
  if (c.manual && c.chosen === 0) out.push("Pick at least one strategy and give it a share above zero.");
  if (c.lossPctOn && !(on(c.lossPct) && c.lossPct < 100)) out.push("The loss limit in percent has to be between 0 and 100.");
  if (c.lossUsdOn && !(on(c.lossUsd) && c.capital > 0 && c.lossUsd < c.capital)) out.push("The loss limit in dollars has to be above zero and below the amount.");
  if (c.tpOn && !on(c.tp)) out.push("The take-profit has to be above zero.");
  if (c.trailOn && !(on(c.trail) && c.trail < 100)) out.push("The trailing limit has to be between 0 and 100 percent.");
  if (c.endOn && !(c.endMs && c.endMs > c.now)) out.push("The end date has to be in the future.");
  return out;
}
