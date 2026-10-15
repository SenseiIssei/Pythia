import { describe, expect, it } from "vitest";
import readme from "../research/lab/README.md?raw";
import {
  BOOKS,
  autopilotLine,
  buildBooks,
  buildStudies,
  gateLine,
  mergeDocs,
  oneLine,
  parseResultsTable,
  parseSweepTable,
  shortQuestion,
  studyDate,
  studyTitle,
  studyVerdict,
  verdictKind,
} from "./researchView";
import type { ForwardReport, ForwardRow, PaperBook } from "./lab";

const files = import.meta.glob<string>("../research/lab/results/*.md", { query: "?raw", import: "default", eager: true });
const DOCS: Record<string, string> = Object.fromEntries(
  Object.entries(files).map(([p, md]) => [p.split("/").pop()!.replace(/\.md$/, ""), md]),
);

const README = `# lab

## Results so far

| Experiment | What it asks | Answer (2026-10-06) |
|---|---|---|
| \`spread\` | Does the spread clear fees? | No. Edge 2 to 9 bps against 50 bps of fees. |
| \`xs_daily\` (M4) | Daily ranking | Signal yes, money not proven. See \`results/m4_funding.md\`. (2026-10-07) |
| \`xs_daily\` round 3 | Funding-aware labels? | Partly. Better net of funding. See \`results/m4_funding.md\`. (2026-10-08) |
| \`breakout_study\` | Is it robust? | A real family, an unproven number. (2026-10-08) |

## Next section

| a | b | c |
|---|---|---|
| \`ignored\` | x | y |
`;

describe("parseResultsTable", () => {
  it("reads one row per experiment with its date and write-up", () => {
    const rows = parseResultsTable(README, ["breakout_study"]);
    expect(rows.map((r) => r.key)).toEqual(["spread", "xs_daily", "xs_daily", "breakout_study"]);
    expect(rows[0]).toMatchObject({ label: "spread", question: "Does the spread clear fees?", date: "2026-10-06", file: null });
    expect(rows[1]).toMatchObject({ label: "xs_daily (M4)", date: "2026-10-07", file: "m4_funding" });
    expect(rows[3].file).toBe("breakout_study");
  });

  it("is empty without the section", () => {
    expect(parseResultsTable("# nothing here")).toEqual([]);
  });

  it("reads the lab's real README", () => {
    const rows = parseResultsTable(readme, Object.keys(DOCS));
    expect(rows.length).toBeGreaterThanOrEqual(15);
    for (const r of rows) {
      expect(r.key).toMatch(/^[a-z0-9_]+$/);
      expect(r.answer.length).toBeGreaterThan(10);
      expect(r.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
    expect(rows.find((r) => r.key === "alpaca_universe")?.file).toBe("alpaca_universe");
  });
});

describe("one-line verdicts", () => {
  it("keeps a bare answer's reason and drops the pointer to the write-up", () => {
    expect(oneLine("No. Edge p99 2 to 9 bps against about 50 bps of fees. Logger keeps running.")).toBe(
      "No. Edge p99 2 to 9 bps against about 50 bps of fees.",
    );
    expect(oneLine("Partly. Lower funding. See `results/m4_funding.md`.", 5)).toBe("Partly.");
    expect(oneLine("Partly. Lower funding. See `results/m4_funding.md`.")).toBe("Partly. Lower funding.");
  });

  it("does not split on decimals and cuts long text on a word", () => {
    expect(oneLine("Sharpe 0.72 and p 0.82 here. Next.", 10)).toBe("Sharpe 0.72 and p 0.82 here.");
    const long = oneLine(`${"word ".repeat(80)}end.`, 40, 60);
    expect(long.length).toBeLessThanOrEqual(63);
    expect(long.endsWith("...")).toBe(true);
  });

  it("finds a write-up's verdict paragraph in either spelling", () => {
    expect(studyVerdict("# T\n\n**Verdict: nothing passes.** Because\nreasons.\n\nNext para.")).toBe("nothing passes. Because reasons.");
    expect(studyVerdict("**Verdict:** Event rate 0.18.")).toBe("Event rate 0.18.");
    expect(studyVerdict("no verdict")).toBeNull();
  });

  it("classifies verdicts", () => {
    expect(verdictKind("No. Too thin.")).toBe("ruled_out");
    expect(verdictKind("Nothing passes.")).toBe("ruled_out");
    expect(verdictKind("negative. No use.")).toBe("ruled_out");
    expect(verdictKind("Yes. 24 of 24 quarters.")).toBe("works");
    expect(verdictKind("Candidate. OOS Sharpe 0.72.")).toBe("open");
    expect(verdictKind("A real family, an unproven number.")).toBe("open");
    expect(verdictKind("Spreads are far tighter than the guesses.")).toBe("info");
    expect(verdictKind("Nobody")).toBe("info");
  });

  it("titles and dates a write-up", () => {
    expect(studyTitle("# Breakout robustness study (pre-registration)\n", "breakout_study")).toBe("Breakout robustness study");
    expect(studyTitle("# alpaca_universe\n", "alpaca_universe")).toBe("Alpaca universe");
    expect(studyTitle("no heading", "vol_daily")).toBe("Vol daily");
    expect(studyDate("# x\n\nWritten 2026-10-11 before any code.")).toBe("2026-10-11");
    expect(studyDate("## Results (generated 2026-10-15, data to 2026-10-14)")).toBe("2026-10-15");
    expect(studyDate("nothing")).toBeNull();
    expect(shortQuestion("Does the Kraken/Binance spread ever clear fees? More words.")).toBe("Does the Kraken/Binance spread ever clear fees?");
    expect(shortQuestion("Faster trades on the 15 Alpaca coins: 4h and 1h")).toBe("Faster trades on the 15 Alpaca coins");
  });
});

describe("buildStudies", () => {
  it("joins README rows and write-ups without listing a write-up twice", () => {
    const docs = {
      m4_funding: "# M4 round three\n\n**Verdict: partly.**",
      breakout_study: "# Breakout\n",
      family_lowvol: "# Family: lowvol\n\nLow vol in the cross-section.",
      vol_daily: "# M6\n\nWritten 2026-10-09.\n\n**Verdict:** Next day LGBM beats HAR.",
    };
    const s = buildStudies(README, docs);
    expect(s.map((x) => x.id).sort()).toEqual(["breakout_study", "family_lowvol", "m4_funding", "m4_funding#2", "spread", "vol_daily"]);
    const vol = s.find((x) => x.id === "vol_daily")!;
    expect(vol).toMatchObject({ title: "M6", verdict: "Next day LGBM beats HAR.", date: "2026-10-09", file: "vol_daily", group: "study" });
    expect(s.find((x) => x.id === "family_lowvol")).toMatchObject({ group: "sweep", verdict: "Low vol in the cross-section.", kind: "info" });
    expect(s.find((x) => x.id === "spread")).toMatchObject({ kind: "ruled_out", file: null, title: "Does the spread clear fees?" });
    // Newest first, undated last.
    expect(s[0].date! >= s[1].date!).toBe(true);
    expect(s[s.length - 1].date).toBeNull();
  });

  it("gives every bundled write-up a place and a verdict", () => {
    const s = buildStudies(readme, DOCS);
    const covered = new Set(s.map((x) => x.file).filter(Boolean));
    for (const name of Object.keys(DOCS)) expect(covered.has(name)).toBe(true);
    for (const x of s) {
      expect(x.verdict.length).toBeGreaterThan(3);
      expect(x.verdict.length).toBeLessThanOrEqual(243);
    }
    expect(new Set(s.map((x) => x.id)).size).toBe(s.length);
  });

  it("gives each sweep family the README's verdicts for its sub-families", () => {
    const sweep = parseSweepTable(readme);
    expect(sweep.date).toBe("2026-10-07");
    expect(sweep.summary).toBe("Nothing passes.");
    expect(new Set(sweep.rows.map((r) => r.family))).toEqual(new Set([1, 2, 3, 4, 5, 6, 7, 8, 9]));
    const s = buildStudies(readme, DOCS);
    const breakout = s.find((x) => x.id === "family_breakout")!;
    expect(breakout).toMatchObject({ group: "sweep", kind: "ruled_out", date: "2026-10-07" });
    expect(breakout.verdict).toContain("top 10: Fails deflation only.");
    expect(breakout.title).toMatch(/^Donchian/);
    expect(s.find((x) => x.id === "families_summary")?.verdict).toBe("Nothing passes.");
    expect(parseSweepTable("# none")).toEqual({ date: null, summary: null, rows: [] });
  });

  it("prefers the engine's newer copy of a write-up", () => {
    expect(mergeDocs({ a: "old", b: "keep" }, [{ name: "a", markdown: "new" }, { name: "c", markdown: " " }])).toEqual({ a: "new", b: "keep" });
  });
});

function fwdRow(over: Partial<ForwardRow>): ForwardRow {
  return {
    kind: "book",
    name: "x",
    label: "X",
    variant: "",
    since: null,
    days: 12,
    elapsedDays: 12,
    returnPct: 1.2,
    maxDdPct: null,
    turnover: null,
    costs: null,
    fundingPct: null,
    expected: null,
    position: null,
    gate7: { days: 12, daysNeeded: 30, trades: 40, tradesNeeded: 30, tradesLabel: "rebalances", progress: 0.4, ready: false },
    status: "early",
    sentence: "",
    mode: null,
    state: null,
    startEquity: null,
    equity: null,
    floorEquity: null,
    btcReturnPct: null,
    fees: null,
    feesShareOfGross: null,
    feesPctOfCapital: null,
    tradesPerDay: null,
    slippage: [],
    labBook: null,
    ...over,
  };
}

describe("buildBooks", () => {
  const forward: ForwardReport = {
    generated: "",
    generatedMs: 0,
    verdict: "",
    books: [fwdRow({ name: "tsmom_tranches" }), fwdRow({ name: "new_book", label: "A new book" })],
    autopilots: [
      fwdRow({ kind: "autopilot", name: "ap1", label: "Steady", labBook: "tsmom_tranches" }),
      fwdRow({ kind: "autopilot", name: "ap2", label: "Calm", labBook: "tsmom_tranches" }),
    ],
    engine: null,
  };
  const paper: PaperBook[] = [
    { name: "m4_ls", variant: "", started: "2026-10-01", days: 14, equity: [], dates: [], returnPct: -1, lastRebalance: {} },
  ];

  it("lists forward books first, then paper books, then the rest of the catalogue", () => {
    const books = buildBooks(forward, paper);
    expect(books.slice(0, 3).map((b) => b.name)).toEqual(["tsmom_tranches", "new_book", "m4_ls"]);
    expect(books).toHaveLength(Object.keys(BOOKS).length + 1);
    expect(books[1]).toMatchObject({ title: "A new book", info: null });
    expect(books[0].autopilots).toEqual(["Steady", "Calm"]);
  });

  it("says whether an autopilot uses the book", () => {
    const books = buildBooks(forward, paper);
    const by = (n: string) => books.find((b) => b.name === n)!;
    expect(autopilotLine(by("tsmom_tranches"))).toBe("Used by 2 autopilots: Steady, Calm.");
    expect(autopilotLine({ ...by("tsmom_tranches"), autopilots: ["Steady"] })).toBe('Used by the autopilot "Steady".');
    expect(autopilotLine(by("breakout_top10"))).toBe("An autopilot can run it; none does right now.");
    expect(autopilotLine(by("m4_ls"))).toBe("No autopilot uses it; it runs in the lab only.");
  });

  it("puts gate 7 in one sentence from the forward report, else the paper book", () => {
    const books = buildBooks(forward, paper);
    const by = (n: string) => books.find((b) => b.name === n)!;
    expect(gateLine(by("tsmom_tranches"))).toEqual({ text: "Paper test: 12 of 30 days, 30 of 30 rebalances.", pct: 40, ready: false });
    expect(gateLine(by("m4_ls"))).toEqual({ text: "Paper test: 14 of 30 days.", pct: 47, ready: false });
    expect(gateLine(by("picks_ls")).text).toBe("No paper test running.");
    const ready = { ...by("tsmom_tranches"), forward: fwdRow({ gate7: { days: 31, daysNeeded: 30, trades: 31, tradesNeeded: 30, tradesLabel: "", progress: 1, ready: true } }) };
    expect(gateLine(ready).ready).toBe(true);
  });

  it("shows the whole catalogue without any lab data", () => {
    expect(buildBooks(null, []).map((b) => b.name)).toEqual(Object.keys(BOOKS));
  });

  it("links every catalogued book to a write-up that ships with the app", () => {
    for (const [name, info] of Object.entries(BOOKS)) {
      if (info.study) expect(DOCS[info.study], `${name} -> ${info.study}`).toBeTruthy();
    }
  });
});
