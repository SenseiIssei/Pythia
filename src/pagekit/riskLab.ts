// Pure helpers for the Risk, Backtest, Optimizer and Composer pages: the
// limit sliders and how their values read, the three risk numbers on top,
// the spike-trim sentence, sizing words and the optimizer's summary lines.
// No React here, so every rule is covered by a test.

import { signedPct } from "../design/format";
import { usage, type Level } from "./format";
import type { RiskLimits, SizingMode } from "../types";

export type LimitGroup = "losses" | "size" | "stops" | "pace";

export interface LimitSpec {
  key: keyof RiskLimits;
  /** The label, also the glossary key for the "?". */
  label: string;
  /** What the setting does, in one plain line. */
  meaning: string;
  group: LimitGroup;
  min: number;
  max: number;
  step: number;
  /** How the value reads. */
  unit: "pct" | "pctEquity" | "pctYear" | "pctBar" | "times" | "timesTarget" | "atr" | "losses" | "seconds" | "perMin";
  /** Zero switches this limit off. */
  zeroOff?: boolean;
}

/** Every slider on the Risk page, in the order they show inside their group. */
export const LIMITS: LimitSpec[] = [
  { key: "maxDailyLossPct", label: "Max daily loss", meaning: "Lose this much in one day and it stops opening trades until tomorrow.", group: "losses", min: 1, max: 25, step: 0.5, unit: "pct" },
  { key: "maxDrawdownPct", label: "Max drawdown (breaker)", meaning: "Fall this far below the best point and everything new stops.", group: "losses", min: 2, max: 50, step: 1, unit: "pct" },
  { key: "maxConsecutiveLosses", label: "Loss streak → cooldown", meaning: "After this many losing trades in a row a strategy takes a break.", group: "losses", min: 0, max: 12, step: 1, unit: "losses", zeroOff: true },
  { key: "cooldownSec", label: "Cooldown duration", meaning: "How long that break lasts.", group: "losses", min: 30, max: 1800, step: 30, unit: "seconds" },
  { key: "maxPositionPct", label: "Max position size", meaning: "The most of the account in any one market.", group: "size", min: 1, max: 50, step: 1, unit: "pctEquity" },
  { key: "maxGrossExposurePct", label: "Max gross exposure", meaning: "The most of the account in the market at once.", group: "size", min: 10, max: 100, step: 5, unit: "pctEquity" },
  { key: "maxCorrelatedExposurePct", label: "Max correlated exposure", meaning: "The same, with markets that move together counted as one bet.", group: "size", min: 0, max: 100, step: 5, unit: "pctEquity", zeroOff: true },
  { key: "portfolioVolTargetPct", label: "Book volatility target", meaning: "How much the whole account may swing in a typical year.", group: "size", min: 0, max: 80, step: 1, unit: "pctYear", zeroOff: true },
  { key: "volSpikeTrimMult", label: "Volatility spike trim", meaning: "Cut every position back when the swing stays this far over the target.", group: "size", min: 0, max: 4, step: 0.25, unit: "timesTarget", zeroOff: true },
  { key: "perStrategyBudgetPct", label: "Per-strategy budget", meaning: "The most of the account any one strategy may use.", group: "size", min: 5, max: 60, step: 1, unit: "pctEquity" },
  { key: "kellyFraction", label: "Kelly fraction", meaning: "How much of the textbook bet size it uses. Smaller is more careful.", group: "size", min: 0.05, max: 1, step: 0.05, unit: "times" },
  { key: "volTargetPct", label: "Vol-target sizing", meaning: "Size each trade so it moves about this much per candle.", group: "size", min: 0, max: 5, step: 0.1, unit: "pctBar", zeroOff: true },
  { key: "stopAtrMult", label: "Stop-loss (ATR)", meaning: "Sell when the price falls this many typical moves below the entry.", group: "stops", min: 0, max: 10, step: 0.5, unit: "atr", zeroOff: true },
  { key: "takeProfitAtrMult", label: "Take-profit (ATR)", meaning: "Take the profit this many typical moves above the entry.", group: "stops", min: 0, max: 15, step: 0.5, unit: "atr", zeroOff: true },
  { key: "trailingAtrMult", label: "Trailing stop (ATR)", meaning: "Follow the price up and sell after a drop this big from the high.", group: "stops", min: 0, max: 10, step: 0.5, unit: "atr", zeroOff: true },
  { key: "maxOrdersPerMin", label: "Max orders / min", meaning: "A speed limit, so a bug can never fire a flood of orders.", group: "pace", min: 1, max: 60, step: 1, unit: "perMin" },
  { key: "maxDataStalenessSec", label: "Max data staleness", meaning: "Refuse to trade on prices older than this.", group: "pace", min: 5, max: 120, step: 5, unit: "seconds" },
];

export const LIMIT_GROUPS: { id: LimitGroup; title: string; hint: string }[] = [
  { id: "losses", title: "Losses and breakers", hint: "When it stops opening new trades after losing." },
  { id: "size", title: "Size and exposure", hint: "How big each trade may be, and how much may be in the market at once." },
  { id: "stops", title: "Stops", hint: "When an open position is closed on its own. Measured in typical daily moves (ATR)." },
  { id: "pace", title: "Pace and data", hint: "Safety limits on how fast it trades and how fresh prices must be." },
];

/** Trims a slider value to the digits its step needs: 0.25 stays, 2.50 reads 2.5. */
function trim(v: number): string {
  return String(Number(v.toFixed(2)));
}

/** How a limit's value reads next to its slider: "5%", "Off", "2× ATR", "1 min 30 s". */
export function limitText(spec: Pick<LimitSpec, "unit" | "zeroOff">, v: number): string {
  if (!Number.isFinite(v)) return "n/a";
  if (spec.zeroOff && v === 0) return "Off";
  const n = trim(v);
  switch (spec.unit) {
    case "pct":
      return `${n}%`;
    case "pctEquity":
      return `${n}% of equity`;
    case "pctYear":
      return `${n}% a year`;
    case "pctBar":
      return `${n}% per candle`;
    case "times":
      return `${n}×`;
    case "timesTarget":
      return `${n}× target`;
    case "atr":
      return `${n}× ATR`;
    case "losses":
      return `${n} ${v === 1 ? "loss" : "losses"}`;
    case "perMin":
      return `${n} a minute`;
    case "seconds": {
      if (v < 60) return `${n} s`;
      const m = Math.floor(v / 60);
      const s = Math.round(v - m * 60);
      return s ? `${m} min ${s} s` : `${m} min`;
    }
  }
}

export interface RiskInputs {
  realizedPnl: number;
  unrealizedPnl: number;
  dayStartEquity: number;
  equity: number;
  grossExposure: number;
}

export interface Gauge {
  /** The measured value, percent of equity. */
  value: number;
  /** The cap it is measured against, percent. */
  cap: number;
  pct: number;
  level: Level;
}

/**
 * The numbers on top of the Risk page: today's loss against the daily limit,
 * and money in the market against the gross cap. A day in profit counts as
 * no loss; an empty account as nothing in the market.
 */
export function riskGauges(p: RiskInputs, limits: Pick<RiskLimits, "maxDailyLossPct" | "maxGrossExposurePct">): { loss: Gauge; gross: Gauge } {
  const dayPnl = p.realizedPnl + p.unrealizedPnl;
  const raw = p.dayStartEquity > 0 ? (-dayPnl / p.dayStartEquity) * 100 : 0;
  const lost = Number.isFinite(raw) ? Math.max(0, raw) : 0;
  const grossPct = p.equity > 0 ? (p.grossExposure / p.equity) * 100 : 0;
  return {
    loss: { value: lost, cap: limits.maxDailyLossPct, ...usage(lost, limits.maxDailyLossPct) },
    gross: { value: grossPct, cap: limits.maxGrossExposurePct, ...usage(grossPct, limits.maxGrossExposurePct) },
  };
}

/** A gauge for any measured value against a cap that 0 switches off. */
export function gauge(value: number, cap: number): Gauge {
  return { value, cap, ...usage(value, cap) };
}

/** A typical month's swing from a yearly one: a year has twelve. */
export function monthlyVol(yearPct: number): number {
  return yearPct / Math.sqrt(12);
}

export interface TrimState {
  word: string;
  tone: "neutral" | "bad" | "accent";
  text: string;
}

/** What the volatility spike trim is doing, as a short word and one sentence. */
export function spikeTrimState(targetPct: number, trimMult: number, spikeSince: number | undefined, now = Date.now()): TrimState {
  const on = trimMult > 0 && targetPct > 0;
  const trigger = targetPct * Math.max(1, trimMult);
  if (!on) return { word: "Trim off", tone: "neutral", text: "Spike trim is off. A spike above the target only stops new entries; nothing is sold." };
  if (spikeSince !== undefined) {
    const mins = Math.max(0, Math.floor((now - spikeSince) / 60_000));
    return {
      word: "Spike",
      tone: "bad",
      text: `Over ${trigger.toFixed(0)}% for ${mins} of 30 minutes. If it stays there, every position is cut by the same share back to ${targetPct}%.`,
    };
  }
  return {
    word: "Trim on",
    tone: "accent",
    text: `If the book stays above ${trigger.toFixed(0)}% (${trimMult}× the target) for 30 minutes, every position is cut by the same share back to ${targetPct}%. Closing only, at most once an hour.`,
  };
}

/** What a strategy's size is based on, in words, and the badge tone. */
export function sizingWord(mode: SizingMode): { text: string; tone: "neutral" | "accent" | "bad" } {
  return mode === "measured" ? { text: "Measured edge", tone: "accent" } : mode === "noEdge" ? { text: "No edge, size 0", tone: "bad" } : { text: "Signal strength", tone: "neutral" };
}

/** A small number with fixed digits, or "n/a" when there is none. */
export function fixed(x: number | undefined, dp = 2): string {
  return x === undefined || !Number.isFinite(x) ? "n/a" : x.toFixed(dp);
}

/** Settings as one line: "fast 10 · slow 50". */
export function paramLine(params: Record<string, number> | [string, number][]): string {
  const pairs = Array.isArray(params) ? params : Object.entries(params);
  return pairs.length ? pairs.map(([k, v]) => `${k} ${v}`).join(" · ") : "default settings";
}

/** The two bars an optimizer result must clear to be believed. */
export const RATIO_BAR = 0.5;
export const P_BAR = 0.05;

/** How many sweep rows clear both bars: a significant deflated Sharpe and an OOS/IS ratio of at least 0.5. */
export function credibleCount(rows: { pValue: number; oosIsRatio?: number }[]): number {
  return rows.filter((r) => r.pValue < P_BAR && (r.oosIsRatio ?? 0) >= RATIO_BAR).length;
}

/** OOS/IS in words, so the colour is never the only signal. */
export function ratioWord(ratio: number | undefined): { text: string; good: boolean | null } {
  if (ratio === undefined) return { text: "n/a", good: null };
  return { text: `${ratio.toFixed(2)} ${ratio >= RATIO_BAR ? "held up" : "mostly noise"}`, good: ratio >= RATIO_BAR };
}

/**
 * Walk-forward change from the first batch to the new one, in percentage
 * points: `degradation` is in-sample minus out-of-sample, so a positive one
 * reads as a fall.
 */
export function degradationText(degradation: number): string {
  return `${signedPct(-degradation, 1).replace("%", "")} percentage points`;
}

/** The last value of an equity curve, or null when there is none. */
export function finalValue(curve: readonly number[]): number | null {
  return curve.length ? curve[curve.length - 1] : null;
}
