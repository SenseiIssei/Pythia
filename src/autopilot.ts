// The arithmetic behind the Autopilot page: the floor a set of stop rules
// produces, and the plain-language analysis of a run. Pure functions, so the
// numbers the owner reads are tested, not eyeballed.
//
// Units: every `...Pct` in the autopilot contract is a percent (12.5 means
// 12.5 %), like `RiskStatus.drawdownPct`. Sleeve weights are fractions that
// add up to 1.

import type {
  AutopilotConfig,
  AutopilotForward,
  AutopilotSleeveConfig,
  AutopilotSleeveStatus,
  AutopilotStatus,
  AutopilotUpdate,
  Market,
  PnlBreakdown,
} from "./types";

export const DAY_MS = 86_400_000;

/**
 * How much evidence a run needs before its result says more than luck. The
 * same bar a strategy has to clear before it may touch real money: 30 trading
 * days and 30 trades on live prices (PROFIT-PLAN, gate 7).
 */
export const MEANINGFUL_DAYS = 30;
export const MEANINGFUL_TRADES = 30;

/** The phrase a live start has to be confirmed with. Travels as `confirm`. */
export const LIVE_PHRASE = "START LIVE";

export type Stop = AutopilotConfig["stop"];

/** Positive, finite, or nothing: an empty or zero field means "no limit". */
export function limit(n: number | null | undefined): number | undefined {
  return n != null && Number.isFinite(n) && n > 0 ? n : undefined;
}

export interface FloorPlan {
  /** The lowest equity it can reach before a stop rule ends the run; null when no rule sets one. */
  floor: number | null;
  /** Which rule sets it. */
  by: "lossPct" | "lossUsd" | "trailing" | null;
  /** Equity at which take-profit fires, if set. */
  takeProfitAt: number | null;
}

/**
 * The floor at the start, before it has gained anything. The highest of the
 * loss rules wins, because whichever is hit first stops it. A trailing limit
 * starts from the start capital (the best point so far) and only ever rises.
 */
export function floorAtStart(capital: number, stop: Stop): FloorPlan {
  const candidates: { v: number; by: FloorPlan["by"] }[] = [];
  const lossPct = limit(stop.maxLossPct);
  const lossUsd = limit(stop.maxLossUsd);
  const trail = limit(stop.trailingPct);
  if (lossPct !== undefined) candidates.push({ v: capital * (1 - Math.min(lossPct, 100) / 100), by: "lossPct" });
  if (lossUsd !== undefined) candidates.push({ v: capital - lossUsd, by: "lossUsd" });
  if (trail !== undefined) candidates.push({ v: capital * (1 - Math.min(trail, 100) / 100), by: "trailing" });
  const tp = limit(stop.takeProfitPct);
  const takeProfitAt = tp !== undefined ? capital * (1 + tp / 100) : null;
  if (candidates.length === 0) return { floor: null, by: null, takeProfitAt };
  const best = candidates.reduce((a, b) => (b.v > a.v ? b : a));
  return { floor: Math.max(0, best.v), by: best.by, takeProfitAt };
}

/** Equity points of a run, always ending at its current equity. */
export function curve(s: AutopilotStatus, now: number): [number, number][] {
  const pts = s.history.filter(([t, v]) => Number.isFinite(t) && Number.isFinite(v));
  const end = s.stoppedMs ?? now;
  if (pts.length === 0) return [[s.startedMs, s.startCapital], [Math.max(end, s.startedMs + 1), s.equity]];
  const last = pts[pts.length - 1];
  if (last[1] !== s.equity && end > last[0]) return [...pts, [end, s.equity]];
  return pts;
}

export interface Dip {
  /** Fall from the high, as a percent of the high. */
  pct: number;
  usd: number;
  peakMs: number;
  troughMs: number;
}

/** The deepest fall from a high point to a later low. Null when it never fell. */
export function worstDip(points: [number, number][]): Dip | null {
  let peak = points[0];
  let worst: Dip | null = null;
  for (const p of points) {
    if (p[1] > peak[1]) peak = p;
    const usd = peak[1] - p[1];
    if (usd > 0 && peak[1] > 0 && (!worst || usd / peak[1] > worst.pct / 100)) {
      worst = { pct: (usd / peak[1]) * 100, usd, peakMs: peak[0], troughMs: p[0] };
    }
  }
  return worst;
}

/** Gross, costs and net in the shape the rest of the app already explains. */
export function breakdown(s: AutopilotStatus): PnlBreakdown {
  const costs = Math.max(0, s.fees);
  const gross = s.pnl + costs;
  const costShare = gross > 0 ? costs / gross : undefined;
  return {
    gross,
    costs,
    net: s.pnl,
    costShare,
    costHeavy: costShare !== undefined ? costShare > 0.4 : costs > 0,
  };
}

export interface Maturity {
  days: number;
  trades: number;
  enough: boolean;
  daysLeft: number;
  tradesLeft: number;
}

export function maturity(days: number, trades: number): Maturity {
  const daysLeft = Math.max(0, Math.ceil(MEANINGFUL_DAYS - days));
  const tradesLeft = Math.max(0, MEANINGFUL_TRADES - trades);
  return { days, trades, enough: daysLeft === 0 && tradesLeft === 0, daysLeft, tradesLeft };
}

export interface HoldComparison {
  /** The window both series cover. */
  fromMs: number;
  toMs: number;
  /** Bitcoin's change over that window, percent. */
  holdPct: number;
  /** The autopilot's change over the same window, percent. */
  runPct: number;
  /** The window is shorter than the run: the price history does not reach back to its start. */
  partial: boolean;
}

/** The latest value at or before `t`, or the first one after it when there is none before. */
function valueAt(points: [number, number][], t: number): number {
  let v = points[0][1];
  for (const [pt, pv] of points) {
    if (pt > t) break;
    v = pv;
  }
  return v;
}

/**
 * What simply holding Bitcoin would have done over the same period, from bar
 * times and closes. Needs timestamps: a price series without them cannot be
 * lined up against the run, so it returns null rather than guess.
 */
export function compareWithHold(
  run: [number, number][],
  times: number[] | undefined,
  closes: number[] | undefined,
  startMs: number,
  endMs: number,
): HoldComparison | null {
  if (!times || !closes || run.length === 0) return null;
  const n = Math.min(times.length, closes.length);
  if (n < 2) return null;
  const prices: [number, number][] = [];
  for (let i = 0; i < n; i++) if (Number.isFinite(times[i]) && closes[i] > 0) prices.push([times[i], closes[i]]);
  if (prices.length < 2) return null;
  const fromMs = Math.max(startMs, prices[0][0]);
  const toMs = Math.min(endMs, prices[prices.length - 1][0]);
  if (toMs <= fromMs) return null;
  const p0 = valueAt(prices, fromMs);
  const p1 = valueAt(prices, toMs);
  const e0 = valueAt(run, fromMs);
  const e1 = valueAt(run, toMs);
  if (!(p0 > 0) || !(e0 > 0)) return null;
  // One bar of slack: candles are stamped at their open, a run at any moment.
  const bar = prices.length > 1 ? (prices[prices.length - 1][0] - prices[0][0]) / (prices.length - 1) : 0;
  const partial = fromMs - startMs > bar * 1.5 || endMs - toMs > bar * 1.5;
  return { fromMs, toMs, holdPct: (p1 / p0 - 1) * 100, runPct: (e1 / e0 - 1) * 100, partial };
}

/** The Bitcoin market to compare against: one with bar times if any has them. */
export function bitcoinMarket(markets: Market[], historyTimes: Record<string, number[]>): Market | undefined {
  const btc = markets.filter((m) => m.kind === "crypto" && /^BTC\b/i.test(m.symbol));
  return btc.find((m) => (historyTimes[m.id]?.length ?? 0) > 1) ?? btc[0];
}

export interface Analysis {
  startMs: number;
  endMs: number;
  days: number;
  points: [number, number][];
  tradesPerDay: number | null;
  pnl: PnlBreakdown;
  dip: Dip | null;
  sleeves: AutopilotStatus["bySleeve"];
  maturity: Maturity;
}

export function analyse(s: AutopilotStatus, now: number): Analysis {
  const endMs = s.stoppedMs ?? now;
  const days = Math.max(0, (endMs - s.startedMs) / DAY_MS);
  const points = curve(s, now);
  return {
    startMs: s.startedMs,
    endMs,
    days,
    points,
    // Under an hour the rate is meaningless and would read as hundreds a day.
    tradesPerDay: days >= 1 / 24 ? s.trades / Math.max(days, 1) : null,
    pnl: breakdown(s),
    dip: worstDip(points),
    sleeves: [...s.bySleeve].sort((a, b) => b.pnl - a.pnl),
    maturity: maturity(days, s.trades),
  };
}

export function isActive(s: AutopilotStatus): boolean {
  return s.state === "running" || s.state === "paused";
}

/** "12 days", "5 h 20 min", "3 min". */
export function fmtDuration(ms: number): string {
  const min = Math.max(0, Math.round(ms / 60_000));
  if (min < 1) return "under a minute";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  if (h < 48) return min % 60 ? `${h} h ${min % 60} min` : `${h} h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d} days ${h % 24} h` : `${d} days`;
}

/** "7 Oct, 14:05". */
export function fmtWhen(ms: number): string {
  return new Date(ms).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** A day count in words: "less than a day", "1 day", "12 days". */
export function fmtDays(days: number): string {
  if (days < 1) return "less than a day";
  const d = Math.floor(days);
  return `${d} day${d === 1 ? "" : "s"}`;
}

/** Days before a forward result counts against the backtest (the engine's rule too). */
export const FORWARD_MIN_DAYS = 10;

export interface ForwardLine {
  tone: "neutral" | "good" | "warn" | "bad";
  text: string;
}

/**
 * One plain line on how a running autopilot compares with its backtest, from
 * the lab's forward report. Null when there is nothing to say.
 */
export function forwardLine(f: AutopilotForward | null | undefined): ForwardLine | null {
  if (!f) return null;
  const after = `after ${fmtDays(f.days)}`;
  switch (f.status) {
    case "early":
      return {
        tone: "neutral",
        text:
          f.days < 1
            ? `Too early to tell: it needs ${FORWARD_MIN_DAYS} days before it is held against the backtest.`
            : `Too early to tell: ${Math.floor(f.days)} of the ${FORWARD_MIN_DAYS} days it needs.`,
      };
    case "ok": {
      const ahead = f.returnPct != null && f.bandHighPct != null && f.returnPct > f.bandHighPct;
      return ahead
        ? { tone: "good", text: `Ahead of its backtest range ${after}, which can be luck as easily as skill.` }
        : { tone: "good", text: `In line with its backtest ${after}.` };
    }
    case "watch":
      return { tone: "warn", text: `Inside its backtest range ${after}, but worth watching.` };
    case "below":
      return { tone: "bad", text: `Below its backtest range ${after}.` };
    case "none":
      return { tone: "neutral", text: "No backtest range to compare with." };
    default:
      return null;
  }
}

/** Re-pick choices on the setup form, in hours; 0 is off. */
export const REPICK_CHOICES: { hours: number; label: string }[] = [
  { hours: 24, label: "every day" },
  { hours: 168, label: "every week" },
  { hours: 0, label: "never" },
];

/**
 * One sleeve's weight and what it holds right now, in plain words. A
 * dropped sleeve says so; a sleeve that holds nothing is "in cash".
 */
/** The word an experimental lab book carries wherever it is shown. */
export const EXPERIMENT_LABEL = "Experiment";

/** What an experiment is, in one line, for the badge's tooltip. */
export const EXPERIMENT_HINT =
  "Failed the lab's deflation test. Runs on paper only because you named it; Pythia never picks it.";

/**
 * Whether a strategy or sleeve is an experimental lab book: the engine's flag
 * on a sleeve, else the label the lab puts at the front of its name.
 */
export function isExperiment(s: { experimental?: boolean; name?: string } | null | undefined): boolean {
  if (!s) return false;
  return s.experimental === true || /\bEXPERIMENT\b/.test(s.name ?? "");
}

export function sleeveExposure(b: AutopilotSleeveStatus): string {
  const share = `${(b.weight * 100).toFixed(0)}% of the amount`;
  if (b.dropped) {
    const left = b.exposure != null && b.exposure >= 0.5;
    // Dropped at a re-pick or taken out by an edit: either way it winds down.
    return left ? "Taken out, what it holds winds down at the next rebalance" : "Taken out, holds nothing";
  }
  const usd = b.exposure ?? 0;
  if (!(usd >= 0.5)) return `${share}, in cash right now`;
  const pct = b.exposurePct != null && Number.isFinite(b.exposurePct) ? ` (${b.exposurePct.toFixed(0)}% of its worth)` : "";
  return `${share}, holds ${Math.round(usd).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}${pct}`;
}

// ── portfolios across asset classes ────────────────────────────────────────

/** One asset class of a portfolio, as the page lists it. */
export interface ClassRow {
  key: string;
  label: string;
  /** "62%" of the portfolio. */
  share: string;
  /** "Holds $3,100 in 2 lab books", or why it holds nothing. */
  detail: string;
  pnl: number;
  /** Why it waits or holds nothing, from the engine. */
  note: string | null;
}

/** A portfolio's asset classes, crypto first; empty for any other autopilot. */
export function classRows(s: AutopilotStatus): ClassRow[] {
  return (s.classes ?? []).map((c) => {
    const books = `${c.books} lab book${c.books === 1 ? "" : "s"}`;
    const usd = Math.round(c.exposure).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
    return {
      key: c.class,
      label: c.label,
      share: `${(c.weight * 100).toFixed(0)}%`,
      detail: c.books === 0 ? (c.exposure >= 0.5 ? `No book, ${usd} still to sell` : "No book with evidence") : c.exposure >= 0.5 ? `Holds ${usd} in ${books}` : `In cash, ${books}`,
      pnl: c.pnl,
      note: c.note ?? null,
    };
  });
}

/** "62% BTC, 38% SPY" for a portfolio's blended benchmark; null for any other. */
export function blendWords(s: AutopilotStatus): string | null {
  const legs = s.benchmark?.legs ?? [];
  if (legs.length === 0) return null;
  return legs.map((l) => `${(l.weight * 100).toFixed(0)}% ${l.symbol.split("/")[0]}`).join(", ");
}

// ── editing a running autopilot ────────────────────────────────────────────

/** The phrase a change to a live autopilot is confirmed with. */
export const LIVE_EDIT_PHRASE = "CHANGE LIVE";

/** The Edit form, as typed. An empty loss or trailing field is "off". */
export interface EditForm {
  name: string;
  amount: string;
  pick: "auto" | "manual";
  /** Strategy id to its share, as typed. */
  weights: Record<string, string>;
  lossPct: string;
  lossUsd: string;
  trailing: string;
}

const shown = (n: number | null | undefined) => (n != null && Number.isFinite(n) && n > 0 ? String(n) : "");

/** The form filled in with what the autopilot runs now. */
export function editForm(c: AutopilotConfig): EditForm {
  return {
    name: c.name,
    amount: String(c.capitalUsd),
    pick: c.sleeves.length === 0 ? "auto" : "manual",
    weights: Object.fromEntries(c.sleeves.map((s) => [s.strategyId, String(s.weight)])),
    lossPct: shown(c.stop.maxLossPct),
    lossUsd: shown(c.stop.maxLossUsd),
    trailing: shown(c.stop.trailingPct),
  };
}

function field(s: string): number | undefined {
  const t = s.replace(/[$,\s%]/g, "");
  if (t === "") return undefined;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

/**
 * The most the max-loss rules let it lose, in dollars and in % of the
 * amount; undefined is no limit. Mirrors the engine's `max_loss_allowance`.
 */
export function lossAllowance(stop: Stop, capital: number): { usd?: number; pct?: number } {
  const byPct = limit(stop.maxLossPct) !== undefined ? (capital * stop.maxLossPct!) / 100 : undefined;
  const byUsd = limit(stop.maxLossUsd);
  const usd = byPct !== undefined && byUsd !== undefined ? Math.min(byPct, byUsd) : (byPct ?? byUsd);
  if (usd === undefined) return {};
  return { usd, pct: capital > 0 ? (usd / capital) * 100 : 0 };
}

/** Does the change let it lose more, in dollars or in %? Then it needs a confirmation. */
export function loosensLoss(oldStop: Stop, oldCapital: number, newStop: Stop, newCapital: number): boolean {
  const o = lossAllowance(oldStop, oldCapital);
  const n = lossAllowance(newStop, newCapital);
  const more = (a?: number, b?: number) => a !== undefined && (b === undefined || b > a + 1e-6);
  return more(o.usd, n.usd) || more(o.pct, n.pct);
}

export interface EditPlan {
  /** Only what changed; empty when nothing did. */
  update: AutopilotUpdate;
  changed: boolean;
  /** What is wrong with the form, in plain sentences. */
  problems: string[];
  /** It lets the autopilot lose more: the owner has to confirm. */
  looser: boolean;
}

function sameSleeves(a: AutopilotSleeveConfig[], b: AutopilotSleeveConfig[]): boolean {
  if (a.length !== b.length) return false;
  const m = new Map(a.map((s) => [s.strategyId, s.weight]));
  return b.every((s) => m.has(s.strategyId) && Math.abs(m.get(s.strategyId)! - s.weight) < 1e-9);
}

/** Turn the form into the change to send, checked the way the engine checks it. */
export function planEdit(c: AutopilotConfig, f: EditForm): EditPlan {
  const problems: string[] = [];
  const update: AutopilotUpdate = {};
  const name = f.name.trim();
  if (name && name !== c.name) update.name = name;

  const capital = field(f.amount);
  if (!(capital !== undefined && capital > 0)) problems.push("Enter an amount above zero.");
  else if (Math.abs(capital - c.capitalUsd) > 1e-9) update.capitalUsd = capital;
  const x = capital !== undefined && capital > 0 ? capital : c.capitalUsd;

  // Strategies: the ones the owner already had first, in their order.
  if (f.pick === "auto") {
    if (c.sleeves.length > 0) update.sleeves = [];
  } else {
    const ids = [...c.sleeves.map((s) => s.strategyId), ...Object.keys(f.weights).filter((id) => !c.sleeves.some((s) => s.strategyId === id))];
    const sleeves = ids
      .map((id) => ({ strategyId: id, weight: field(f.weights[id] ?? "") ?? 0 }))
      .filter((s) => Number.isFinite(s.weight) && s.weight > 0);
    if (sleeves.length === 0) problems.push("Pick at least one strategy with a share above zero.");
    else if (!sameSleeves(sleeves, c.sleeves)) update.sleeves = sleeves;
  }

  const lossPct = field(f.lossPct);
  const lossUsd = field(f.lossUsd);
  const trailing = field(f.trailing);
  if (lossPct !== undefined && !(lossPct > 0 && lossPct <= 100)) problems.push("The loss limit in percent has to be above 0 and at most 100.");
  if (lossUsd !== undefined && !(lossUsd > 0 && lossUsd <= x)) problems.push("The loss limit in dollars has to be above zero and at most the amount.");
  if (trailing !== undefined && !(trailing > 0 && trailing < 100)) problems.push("The trailing limit has to be between 0 and 100 percent.");
  if (c.mode === "live" && lossPct === undefined && lossUsd === undefined) problems.push("Real money needs a loss limit, in percent or in dollars.");
  const stop: Stop = { ...c.stop, maxLossPct: lossPct ?? null, maxLossUsd: lossUsd ?? null, trailingPct: trailing ?? null };
  const same = (a: number | null | undefined, b: number | null | undefined) => (a ?? null) === (b ?? null);
  if (!same(stop.maxLossPct, c.stop.maxLossPct) || !same(stop.maxLossUsd, c.stop.maxLossUsd) || !same(stop.trailingPct, c.stop.trailingPct)) {
    update.stop = stop;
  }
  const changed = Object.keys(update).length > 0;
  return { update, changed, problems, looser: loosensLoss(c.stop, c.capitalUsd, stop, x) };
}
