import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ageText, daysToGo, de, fetchProgress, freshness, missingGate, parseProgress, pctText, share } from "./progress";
import { ProgressBody } from "./pages/Progress";
import { readDeepLink } from "./deepLink";
import { NAV, isPageId } from "./nav";

const NOW = 1_793_200_000_000;
const H = 3_600_000;

const RAW = {
  found: true,
  updated_ms: NOW - 5 * 60_000,
  ladder: {
    file: "reports/ladder/latest.json", found: true, at_ms: NOW - 10 * 60_000, stale_ms: 2 * H, top_step: 2, top_name: "getestet",
    steps: { "0": "keine", "1": "Idee", "2": "getestet" }, counts: { "0": 1, "1": 1, "2": 1 }, n_trials: 2690, sr0_annual: 2.7624,
    rows: [
      { id: "book:small40_spy_trend", name: "small40_spy_trend", step: 2, step_name: "getestet", next: "30 Tage im Schatten", tainted: 0 },
      { id: "book:btc_gated", name: "btc_gated", step: 1, step_name: "Idee", next: "kein getesteter Bericht", tainted: 0 },
      { id: "book:tsmom", name: "tsmom", step: 0, step_name: "keine", next: "vorregistriert", tainted: 0 },
      { step: 9 },
    ],
  },
  ten: { file: "reports/pumpfun_rt/realistic.json", found: true, at_ms: NOW - 40 * H, stale_ms: 36 * H, started: false, books: [] },
  gap: {
    file: "reports/pumpfun_rt/realistic.json", found: true, at_ms: NOW - 40 * H, stale_ms: 36 * H,
    calibration: { rule: "P_pool0_wait", pairs: 14, live: 41, paper: 524, days: 4.2, median_pts: -0.4856, mean_pts: -2.742, verdict: "noch nicht" },
    p2: null,
  },
  gate7: {
    file: "reports/paper_review/latest.json", found: true, at_ms: NOW - 8 * H, stale_ms: 36 * H,
    books: [{ book: "tsmom", since: "2026-10-06", days: 23, rebalances: 18, need_days: 30, need_rebalances: 30, ready: false, paper_pct: -6.2, backtest_pct: -7.2 }],
  },
  weekly: { file: "reports/weekly/latest.md", found: false, at_ms: null, stale_ms: 8 * 24 * H, lines: [] },
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("reading the progress file", () => {
  it("parses every section and drops rows without a name", () => {
    const d = parseProgress(RAW);
    expect(d.found).toBe(true);
    expect(d.ladder.rows.map((r) => r.name)).toEqual(["small40_spy_trend", "btc_gated", "tsmom"]);
    expect(d.ladder.counts.map((c) => c.step)).toEqual([2, 1, 0]);
    expect(d.ten.started).toBe(false);
    expect(d.gap.calibration?.medianPts).toBe(-0.4856);
    expect(d.gate7.books[0]).toMatchObject({ book: "tsmom", days: 23, needDays: 30, ready: false });
    expect(parseProgress(null)).toMatchObject({ found: false, ladder: { found: false, rows: [] }, ten: { started: false } });
  });

  it("only ever GETs", async () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "/api/pythia");
    const calls: { url: string; method: string }[] = [];
    vi.stubGlobal("fetch", async (u: string, init?: RequestInit) => {
      calls.push({ url: u, method: init?.method ?? "GET" });
      return new Response(JSON.stringify(RAW));
    });
    const d = await fetchProgress();
    expect(d.ladder.topStep).toBe(2);
    expect(calls).toEqual([{ url: "/api/pythia/api/lab/progress", method: "GET" }]);
  });
});

describe("the age of a number", () => {
  it("says fresh, stale, unknown or missing against this device's clock", () => {
    expect(freshness({ found: true, atMs: NOW - H, staleMs: 2 * H }, NOW)).toBe("fresh");
    expect(freshness({ found: true, atMs: NOW - 3 * H, staleMs: 2 * H }, NOW)).toBe("stale");
    expect(freshness({ found: true, atMs: null, staleMs: 2 * H }, NOW)).toBe("unknown");
    expect(freshness({ found: false, atMs: null, staleMs: 2 * H }, NOW)).toBe("missing");
    // the same file goes stale later, when its job has stopped
    expect(freshness({ found: true, atMs: NOW - H, staleMs: 2 * H }, NOW + 2 * H)).toBe("stale");
  });

  it("says how old, in German", () => {
    expect(ageText(NOW - 30_000, NOW)).toBe("gerade eben");
    expect(ageText(NOW - 10 * 60_000, NOW)).toBe("vor 10 Min.");
    expect(ageText(NOW - 40 * H, NOW)).toBe("vor 1 Tag");
    expect(ageText(NOW - 72 * H, NOW)).toBe("vor 3 Tagen");
    expect(ageText(null, NOW)).toBe("Zeit unbekannt");
  });

  it("writes German numbers and gate helpers", () => {
    expect(de(-0.4856, 1, true)).toBe("-0,5");
    expect(de(2690, 0)).toBe("2.690");
    expect(de(null)).toBe("k. A.");
    expect(pctText(0.021)).toBe("+2,1 %");
    expect(daysToGo(23, 30)).toBe(7);
    expect(daysToGo(31, 30)).toBe(0);
    expect(share(45, 30)).toBe(1);
    const b = parseProgress({ ...RAW, ten: { found: true, started: true, books: [{ book: "T10", started: true, gate: [{ id: "days", label: "30 Tage", ok: false }, { id: "gap", label: "P2", ok: true }] }] } }).ten.books[0];
    expect(missingGate(b)).toEqual(["30 Tage"]);
  });
});

describe("the progress page", () => {
  it("opens embedded and has its place in the menu", () => {
    expect(isPageId("progress")).toBe(true);
    expect(readDeepLink("?page=progress&embed=1")).toEqual({ page: "progress", embed: true });
    expect(NAV.find((n) => n.id === "progress")?.label).toBe("Progress");
  });

  it("shows every section with its age, stale ones marked", () => {
    const html = renderToStaticMarkup(<ProgressBody d={parseProgress(RAW)} nowMs={NOW} />);
    expect(html).toContain("Leiter zum Echtgeld");
    expect(html).toContain("small40_spy_trend");
    expect(html).toContain("Als Nächstes fehlt: 30 Tage im Schatten");
    expect(html).toContain("Nicht gestartet");
    expect(html).toContain("Papier minus live");
    expect(html).toContain("nicht gemessen");
    expect(html).toContain("tsmom-Bücher: Tor 7");
    expect(html).toContain("noch 7 Tage");
    expect(html).toContain("Noch keine Wochenseite");
    expect(html).toContain("Stand vor 10 Min.");
    // realistic.json is 40 hours old: both of its cards say so
    expect(html.match(/data-age="stale"/g)).toHaveLength(2);
    expect(html.match(/veraltet/g)).toHaveLength(2);
    expect(html.match(/data-age="fresh"/g)).toHaveLength(2);
    expect(html).not.toContain("Die Seite selbst ist alt");
  });

  it("says when the page itself is old, and when there is nothing yet", () => {
    const old = renderToStaticMarkup(<ProgressBody d={parseProgress(RAW)} nowMs={NOW + 3 * H} />);
    expect(old).toContain("Die Seite selbst ist alt");
    expect(old.match(/data-age="stale"/g)?.length).toBe(3);
    expect(renderToStaticMarkup(<ProgressBody d={parseProgress({ found: false })} nowMs={NOW} />)).toContain("Noch keine Daten");
  });

  it("shows the weekly page's first lines once it exists", () => {
    const d = parseProgress({ ...RAW, weekly: { file: "reports/weekly/latest.md", found: true, at_ms: NOW - 2 * H, stale_ms: 8 * 24 * H, lines: ["# Pythia, Woche bis 2026-11-01", "Vorwoche: kein Stand"] } });
    const html = renderToStaticMarkup(<ProgressBody d={d} nowMs={NOW} />);
    expect(html).toContain("Pythia, Woche bis 2026-11-01");
    expect(html).not.toContain("# Pythia");
  });
});
