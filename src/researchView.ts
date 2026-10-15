// What the Research page shows, worked out from the lab's own files: the
// results table in research/lab/README.md, the write-ups in
// research/lab/results/*.md, the forward report and the paper books. Pure
// functions only; the page (pages/Research.tsx) does the fetching.

import { parseBlocks, plainText } from "./markdown";
import { gatePct, type ForwardReport, type ForwardRow, type PaperBook } from "./lab";

// ── studies ─────────────────────────────────────────────────────────────────

export interface ReadmeRow {
  /** The experiment's code name, from the first `code` span: "xs_daily". */
  key: string;
  /** The first cell as plain text: "xs_daily (M4)". */
  label: string;
  question: string;
  answer: string;
  /** The answer's own date, else the table's. */
  date: string | null;
  /** The write-up the row points to (`results/<name>.md`), when there is one. */
  file: string | null;
}

const DATE = /(\d{4}-\d{2}-\d{2})/;

/**
 * The "Results so far" table of the lab README: one row per experiment with
 * the question it asked and the answer it got.
 */
export function parseResultsTable(readme: string, files: readonly string[] = []): ReadmeRow[] {
  const start = readme.search(/^##\s+Results so far/m);
  if (start < 0) return [];
  const rest = readme.slice(start);
  const next = rest.slice(2).search(/^##\s/m);
  const section = next < 0 ? rest : rest.slice(0, next + 2);
  const table = parseBlocks(section).find((b) => b.t === "table");
  if (!table || table.t !== "table") return [];
  const tableDate = DATE.exec(table.head.join(" "))?.[1] ?? null;
  const known = new Set(files);
  return table.rows
    .filter((r) => r.length >= 3 && r[0].trim())
    .map((r) => {
      const key = /`([^`]+)`/.exec(r[0])?.[1] ?? plainText(r[0]);
      const answer = r[2];
      const linked = /results\/([\w-]+)\.md/.exec(answer)?.[1] ?? null;
      const dates = [...answer.matchAll(/\((\d{4}-\d{2}-\d{2})\)/g)];
      return {
        key,
        label: plainText(r[0]),
        question: plainText(r[1]),
        answer: plainText(answer),
        date: dates.length ? dates[dates.length - 1][1] : tableDate,
        file: linked ?? (known.has(key) ? key : null),
      };
    });
}

/**
 * The first sentences of a text, enough to say something (at least `min`
 * characters, so a bare "No." keeps its reason), cut at `max` on a word.
 */
export function oneLine(text: string, min = 40, max = 240): string {
  const t = plainText(text).replace(/\s*See `?results\/[\w-]+\.md`?\.?/g, "").trim();
  const sentences = t.split(/(?<=[.!?])\s+(?=[A-Z0-9"(])/);
  let out = "";
  for (const s of sentences) {
    out = out ? `${out} ${s}` : s;
    if (out.length >= min) break;
  }
  if (out.length <= max) return out;
  const cut = out.slice(0, max);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), max * 0.6)).replace(/[,;:]$/, "")}...`;
}

/** The paragraph that starts with "**Verdict", as plain text, or null. */
export function studyVerdict(md: string): string | null {
  const at = md.search(/\*\*Verdict\b/);
  if (at < 0) return null;
  const para = md.slice(at).split(/\n\s*\n/)[0];
  const text = plainText(para).replace(/^Verdict\s*:?\s*/i, "").trim();
  return text || null;
}

/** A write-up's title from its first heading, without the bookkeeping. */
export function studyTitle(md: string, name: string): string {
  const h = /^#\s+(.+)$/m.exec(md)?.[1];
  const t = h ? plainText(h).replace(/\s*\((pre-registration|generated [^)]*)\)\s*$/i, "").trim() : "";
  return t && t !== name ? t : humanName(name);
}

/** "alpaca_universe" -> "Alpaca universe". */
export function humanName(name: string): string {
  const s = name.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** The newest date a write-up mentions near its top (generated or written on). */
export function studyDate(md: string): string | null {
  const m = /(?:generated|written|^)\s*(\d{4}-\d{2}-\d{2})/im.exec(md) ?? DATE.exec(md);
  return m ? m[1] : null;
}

/** The question as a short title: up to its first stop, at most `max` characters. */
export function shortQuestion(q: string, max = 90): string {
  const t = plainText(q).replace(/\s*\([^)]*\)/g, "");
  const stop = t.search(/[?]|[.:;](\s|$)/);
  let s = stop > 0 ? t.slice(0, stop + (t[stop] === "?" ? 1 : 0)) : t;
  if (s.length > max) s = `${s.slice(0, s.lastIndexOf(" ", max)).replace(/[,;:]$/, "")}...`;
  return s;
}

export type VerdictKind = "works" | "open" | "ruled_out" | "info";

/** What a verdict amounts to, from how it starts. */
export function verdictKind(verdict: string): VerdictKind {
  const v = verdict.trim().toLowerCase();
  if (/^(yes\b|passes\b|works\b)/.test(v)) return "works";
  if (/^(candidate|partly|forward evidence|a real family|signal yes|forecast partly|promising)/.test(v)) return "open";
  // "No new book, but a useful answer": a finding, not a dead end.
  if (/^no\b[^.]*\bbut\b/.test(v)) return "info";
  if (/^(no\b|negative|nothing passes|fails?\b|dead\b)/.test(v)) return "ruled_out";
  return "info";
}

export function verdictBadge(kind: VerdictKind): { label: string; tone: "green" | "amber" | "neutral" } {
  switch (kind) {
    case "works":
      return { label: "works", tone: "green" };
    case "open":
      return { label: "promising, unproven", tone: "amber" };
    case "ruled_out":
      return { label: "ruled out", tone: "neutral" };
    default:
      return { label: "measured", tone: "neutral" };
  }
}

export interface StudyView {
  id: string;
  title: string;
  /** The code name and tag, for people who know the lab: "xs_daily (M4)". */
  code: string;
  verdict: string;
  kind: VerdictKind;
  date: string | null;
  /** The write-up's name under results/, when there is one. */
  file: string | null;
  /** "sweep" for the strategy-family sweep's write-ups, which read as one group. */
  group: "study" | "sweep";
}

const isSweep = (name: string) => name === "families_summary" || name.startsWith("family_");

export interface SweepTable {
  date: string | null;
  /** The bold line under the table: "Nothing passes." */
  summary: string | null;
  /** One row per sub-family: its number, its name and the README's verdict. */
  rows: { family: number; label: string; verdict: string }[];
}

/** The README's "Strategy-family sweep" section: its table and its one-line conclusion. */
export function parseSweepTable(readme: string): SweepTable {
  const start = readme.search(/^##\s+Strategy-family sweep/m);
  if (start < 0) return { date: null, summary: null, rows: [] };
  const rest = readme.slice(start);
  const next = rest.slice(2).search(/^##\s/m);
  const section = next < 0 ? rest : rest.slice(0, next + 2);
  const blocks = parseBlocks(section);
  const date = blocks[0]?.t === "h" ? (DATE.exec(blocks[0].text)?.[1] ?? null) : null;
  const ti = blocks.findIndex((b) => b.t === "table");
  const table = blocks[ti];
  if (!table || table.t !== "table") return { date, summary: null, rows: [] };
  const col = table.head.findIndex((h) => /verdict/i.test(h));
  const rows = table.rows
    .map((r) => {
      const m = /^(\d+)\s+(.*)$/.exec(plainText(r[0] ?? ""));
      return m && col >= 0 ? { family: Number(m[1]), label: m[2], verdict: plainText(r[col] ?? "") } : null;
    })
    .filter((r): r is { family: number; label: string; verdict: string } => r !== null);
  const after = blocks.slice(ti + 1).find((b) => b.t === "p");
  const bold = after && after.t === "p" ? /^\*\*([^*]+)\*\*/.exec(after.text)?.[1] ?? null : null;
  return { date, summary: bold, rows };
}

/** A sweep write-up's verdict from the README's table: "Breakout, top 10: Fails deflation only." */
function sweepVerdict(name: string, md: string, sweep: SweepTable): string | null {
  if (name === "families_summary") return sweep.summary;
  const n = Number(/Family (\d+):/.exec(md)?.[1]);
  const rows = sweep.rows.filter((r) => r.family === n);
  if (!rows.length) return null;
  if (rows.length === 1) return rows[0].verdict;
  return rows.map((r) => `${r.label.charAt(0).toUpperCase()}${r.label.slice(1)}: ${oneLine(r.verdict, 1)}`).join(" ");
}

/**
 * One list of studies from the README's tables and the write-ups. A README row
 * gives the verdict and the question; a write-up no row points to gets its
 * verdict from its own "**Verdict" paragraph. Newest first.
 */
export function buildStudies(readme: string, docs: Record<string, string>): StudyView[] {
  const names = Object.keys(docs);
  const rows = parseResultsTable(readme, names);
  const sweep = parseSweepTable(readme);
  const claimed = new Set<string>();
  const ids = new Set<string>();
  const out: StudyView[] = [];
  for (const r of rows) {
    if (r.file) claimed.add(r.file);
    let id = r.file ?? r.key;
    for (let n = 2; ids.has(id); n++) id = `${r.file ?? r.key}#${n}`;
    ids.add(id);
    const verdict = oneLine(r.answer);
    // A write-up's own heading names it better than a long question does.
    const md = r.file ? docs[r.file] : undefined;
    const heading = md ? studyTitle(md, r.file!) : null;
    out.push({
      id,
      title: heading && heading !== humanName(r.file!) && !claimedTwice(rows, r.file) ? heading : shortQuestion(r.question),
      code: r.label,
      verdict,
      kind: verdictKind(verdict),
      date: r.date,
      file: r.file,
      group: "study",
    });
  }
  for (const name of names.sort()) {
    if (claimed.has(name) || ids.has(name)) continue;
    const md = docs[name];
    const inSweep = isSweep(name);
    const fromSweep = inSweep ? sweepVerdict(name, md, sweep) : null;
    const raw = fromSweep ?? studyVerdict(md) ?? firstParagraph(md);
    // A family's verdict joins its sub-families' lines; keep them all.
    const verdict = raw ? (fromSweep ? oneLine(raw, 240) : oneLine(raw)) : "No verdict written yet.";
    const family = inSweep
      ? /Family \d+:\s*([\s\S]*?)(?:\n\s*\n|```|$)/.exec(md)?.[1]?.replace(/\s+/g, " ").trim().replace(/\.$/, "")
      : undefined;
    const subs = inSweep ? sweep.rows.filter((r) => r.family === Number(/Family (\d+):/.exec(md)?.[1])) : [];
    ids.add(name);
    out.push({
      id: name,
      title: family ? shortQuestion(`${family.charAt(0).toUpperCase()}${family.slice(1)}`) : studyTitle(md, name),
      code: name,
      verdict,
      kind: subs.length > 1 && subs.every((r) => verdictKind(r.verdict) === "ruled_out") ? "ruled_out" : verdictKind(verdict),
      date: inSweep && sweep.date ? sweep.date : studyDate(md),
      file: name,
      group: inSweep ? "sweep" : "study",
    });
  }
  return out.sort((a, b) => (b.date ?? "").localeCompare(a.date ?? "") || a.title.localeCompare(b.title));
}

/** Two README rows sharing a write-up keep their questions apart as titles. */
function claimedTwice(rows: ReadmeRow[], file: string | null): boolean {
  return !!file && rows.filter((r) => r.file === file).length > 1;
}

function firstParagraph(md: string): string | null {
  const p = parseBlocks(md).find((b) => b.t === "p");
  return p && p.t === "p" ? p.text : null;
}

/** Write-ups from the engine replace the bundled copy of the same name. */
export function mergeDocs(bundled: Record<string, string>, served: { name: string; markdown: string }[]): Record<string, string> {
  const out = { ...bundled };
  for (const s of served) if (s.markdown.trim()) out[s.name] = s.markdown;
  return out;
}

// ── strategy books ───────────────────────────────────────────────────────────

export interface BookInfo {
  title: string;
  /** What it does, in plain words. */
  what: string;
  /** The backtest's headline numbers, as the study reported them. */
  backtest: { label: string; value: string }[];
  /** Gates 1 to 6: what the backtest's checks said. */
  checks: string;
  /** The write-up under results/, when there is one. */
  study: string | null;
  /** Writes a signal an autopilot can run; no engine runs it on its own. */
  autopilotOnly: boolean;
  /** Failed the lab's bar and runs anyway, on paper, as a labelled
   *  experiment: never auto-picked, only where an autopilot names it. */
  experiment?: boolean;
}

const EXPERIMENT_CHECKS = "Experiment: failed the lab's deflation test. Runs on paper only; Pythia never picks it, an autopilot runs it only when you name it.";

/**
 * The lab's paper books in plain words. The numbers are the out-of-sample
 * backtests from research/lab/README.md and the write-ups, after costs.
 */
export const BOOKS: Record<string, BookInfo> = {
  breakout_top10: {
    title: "Breakout, 10 most traded coins",
    what: "Buys a coin when it closes above its highest close of the last 20 days and sells when it falls below its lowest close of the last 10. Only the 10 most traded coins of each day, long only.",
    backtest: [
      { label: "Sharpe at 15 / 41 bps", value: "1.20 / 1.08" },
      { label: "Growth a year", value: "22 %" },
      { label: "Worst dip", value: "22 %" },
      { label: "Bitcoin's worst dip", value: "53 %" },
    ],
    checks: "Every nearby setting also made money, but after counting the 100 variants tried the number could still be luck (deflated p 0.01, 0.95 needed).",
    study: "breakout_study",
    autopilotOnly: true,
  },
  tsmom_top20: {
    title: "Momentum, 20 most traded coins",
    what: "Holds each of the 20 most traded coins of the day while it is up over the last four weeks, each sized so calm and wild coins carry the same risk. Checked every day.",
    backtest: [
      { label: "Sharpe at 15 / 41 bps", value: "0.54 / 0.32" },
      { label: "Growth a year", value: "4 %" },
      { label: "Worst dip", value: "24 %" },
    ],
    checks: "Positive, but well below the bar for luck (deflated p 0.00 over 100 variants).",
    study: "family_volmom",
    autopilotOnly: true,
  },
  tsmom_tranches: {
    title: "Momentum in seven weekly slices",
    what: "The same momentum targets, but split into seven slices and only one slice is traded each day. Same idea, far fewer trades, so fees matter less.",
    backtest: [
      { label: "Sharpe at 15 / 35 bps", value: "0.58 / 0.52" },
      { label: "Worst dip", value: "23 %" },
      { label: "Turnover a year", value: "5x" },
    ],
    checks: "Below the bar for luck (deflated p 0.00 over 184 trials). Runs for forward evidence only.",
    study: "tsmom_tranches",
    autopilotOnly: true,
  },
  tsmom: {
    title: "Momentum, 20 coins",
    what: "Holds each of 20 large coins while its price is above where it was four weeks ago, sized by its volatility. The lab's first candidate.",
    backtest: [
      { label: "Sharpe", value: "0.72" },
      { label: "Worst dip", value: "25 %" },
      { label: "Coin basket's worst dip", value: "73 %" },
    ],
    checks: "Leans on survivorship: on each day's 20 most traded coins the same rule makes 0.54. Deflated p 0.82.",
    study: "family_volmom",
    autopilotOnly: false,
  },
  tsmom_regime: {
    title: "Momentum with a Bitcoin filter",
    what: "The momentum book, but only while Bitcoin trades above its 200-day average; otherwise it sits in cash.",
    backtest: [
      { label: "Sharpe", value: "1.05" },
      { label: "Worst dip", value: "19 %" },
    ],
    checks: "Deflated p 0.86 over 50 variants, short of 0.95. The filter works by sitting out bear markets; no model has beaten it.",
    study: "regime_hmm",
    autopilotOnly: false,
  },
  m4_ls: {
    title: "Model picks, long and short",
    what: "A model ranks the 100 most traded perpetual futures each day; the book buys the best 10 and sells short the worst 10. Needs perpetuals, which Pythia does not trade.",
    backtest: [
      { label: "Sharpe at 15 / 41 bps", value: "2.15 / 2.00" },
      { label: "Plain low-vol book", value: "1.87 / 1.80" },
      { label: "Turnover a year", value: "18x" },
    ],
    checks: "Fails the luck test (deflated p 0.39 over 100 variants). Forward evidence only.",
    study: "m4_funding",
    autopilotOnly: false,
  },
  picks_ls: {
    title: "Weekly coin ranking, long and short",
    what: "Uses the weekly coin ranking model (M2): long the coins it ranks best, short the ones it ranks worst, in equal amounts.",
    backtest: [],
    checks: "Forward evidence only; the backtest exists as weekly report rows, so its range is approximate.",
    study: null,
    autopilotOnly: false,
  },
  picks_ls_v2: {
    title: "Weekly coin ranking v2, long and short",
    what: "The same market-neutral book on the second version of the ranking model, which also sees perpetual-futures data.",
    backtest: [],
    checks: "Forward evidence only; the backtest exists as weekly report rows, so its range is approximate.",
    study: null,
    autopilotOnly: false,
  },
  memes_rotation: {
    title: "Experiment: memecoin rotation",
    what: "Holds the one memecoin Alpaca lists (DOGE, SHIB, PEPE, BONK, WIF, TRUMP) with the best four-week return, only while that return is positive and Bitcoin is above its 200-day average.",
    backtest: [
      { label: "Sharpe at 35 / 70 bps", value: "1.15 / 0.94" },
      { label: "Worst dip", value: "27 %" },
      { label: "Share of P&L from PEPE", value: "52 %" },
    ],
    checks: `Deflated p 0.01 over 427 trials. ${EXPERIMENT_CHECKS}`,
    study: "experiments",
    autopilotOnly: true,
    experiment: true,
  },
  memes_tsmom: {
    title: "Experiment: memecoin momentum",
    what: "Holds each of Alpaca's six memecoins while it is up over four weeks and Bitcoin is above its 200-day average, each sized for 40 % volatility over six slots.",
    backtest: [
      { label: "Sharpe at 35 / 70 bps", value: "0.67 / 0.50" },
      { label: "Bitcoin over the same days", value: "0.74" },
      { label: "Worst dip", value: "19 %" },
    ],
    checks: `Below Bitcoin, deflated p 0.00 over 427 trials. ${EXPERIMENT_CHECKS}`,
    study: "experiments",
    autopilotOnly: true,
    experiment: true,
  },
  trend4h_pullback: {
    title: "Experiment: 4-hour trend, pullback entries",
    what: "On 4-hour bars, holds an Alpaca coin while its fast average is above its slow one and Bitcoin is above its 200-day average. It buys only with a resting limit half a 4-hour move under the price, so it pays the maker fee; trades last about 8 days.",
    backtest: [
      { label: "Sharpe maker / taker", value: "0.71 / 0.51" },
      { label: "Worst dip", value: "44 %" },
      { label: "Entry orders that fill", value: "18 %" },
    ],
    checks: `Deflated p 0.00 over 841 trials, lost in 2025. ${EXPERIMENT_CHECKS}`,
    study: "experiments",
    autopilotOnly: true,
    experiment: true,
  },
  pumpfun_migration: {
    title: "Experiment: pump.fun, every graduation",
    what: "On paper only: $100 into every pump.fun token that completes its bonding curve with at least $10,000 of liquidity, sold after 24 hours or on a 30 % fall from its best. No wallet, no orders.",
    backtest: [],
    checks: "No backtest exists. Most of these tokens go to zero; a drained pool counts as a total loss.",
    study: "experiments",
    autopilotOnly: false,
    experiment: true,
  },
  pumpfun_filtered: {
    title: "Experiment: pump.fun, filtered graduations",
    what: "On paper only: graduations with $20,000 of liquidity, 300 holders or more, the top 10 under 30 % and no mint or freeze authority; held up to 72 hours with a 40 % trailing stop.",
    backtest: [],
    checks: "No backtest exists. Filters remove the obvious traps, not the risk.",
    study: "experiments",
    autopilotOnly: false,
    experiment: true,
  },
  pumpfun_filtered_quick: {
    title: "Experiment: pump.fun, filtered and quick",
    what: "On paper only: the filtered graduations, sold at +100 %, after 6 hours or on a 25 % trailing stop.",
    backtest: [],
    checks: "No backtest exists. Measures whether quick exits keep anything at all.",
    study: "experiments",
    autopilotOnly: false,
    experiment: true,
  },
};

export interface BookView {
  name: string;
  title: string;
  info: BookInfo | null;
  forward: ForwardRow | null;
  paper: PaperBook | null;
  /** Autopilots that run this book, by their label. */
  autopilots: string[];
}

/**
 * Every strategy book worth showing: the forward report's books first (in its
 * order), then paper books it does not cover, then the rest of the catalogue.
 */
export function buildBooks(forward: ForwardReport | null, paper: PaperBook[], catalogue = BOOKS): BookView[] {
  const order: string[] = [];
  const add = (n: string) => {
    if (n && !order.includes(n)) order.push(n);
  };
  forward?.books.forEach((b) => add(b.name));
  paper.forEach((b) => add(b.name));
  Object.keys(catalogue).forEach(add);
  return order.map((name) => {
    const info = catalogue[name] ?? null;
    const fwd = forward?.books.find((b) => b.name === name) ?? null;
    return {
      name,
      title: info?.title ?? fwd?.label ?? humanName(name),
      info,
      forward: fwd,
      paper: paper.find((b) => b.name === name) ?? null,
      autopilots: (forward?.autopilots ?? []).filter((a) => a.labBook === name).map((a) => a.label || a.name),
    };
  });
}

/** Whether an autopilot uses the book, in one sentence. */
export function autopilotLine(b: BookView): string {
  if (b.autopilots.length === 1) return `Used by the autopilot "${b.autopilots[0]}".`;
  if (b.autopilots.length > 1) return `Used by ${b.autopilots.length} autopilots: ${b.autopilots.join(", ")}.`;
  if (b.info?.autopilotOnly) return "An autopilot can run it; none does right now.";
  return "No autopilot uses it; it runs in the lab only.";
}

/** Gate 7 (30 days and 30 trades on paper before real money), in one sentence. */
export function gateLine(b: BookView): { text: string; pct: number; ready: boolean } {
  const g = b.forward?.gate7;
  if (g && (g.daysNeeded > 0 || g.tradesNeeded > 0)) {
    const pct = gatePct(g);
    if (g.ready) return { text: "Passed the paper test: enough days and trades to judge it.", pct: 100, ready: true };
    return {
      text: `Paper test: ${Math.min(g.days, g.daysNeeded)} of ${g.daysNeeded} days, ${Math.min(g.trades, g.tradesNeeded)} of ${g.tradesNeeded} ${g.tradesLabel || "trades"}.`,
      pct,
      ready: false,
    };
  }
  if (b.paper) {
    const days = Math.min(b.paper.days, 30);
    return { text: `Paper test: ${days} of 30 days.`, pct: Math.round((days / 30) * 100), ready: days >= 30 };
  }
  return { text: "No paper test running.", pct: 0, ready: false };
}
