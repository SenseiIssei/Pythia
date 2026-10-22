import { describe, expect, it } from "vitest";
import {
  DAY_MS,
  analyse,
  blendWords,
  breakdown,
  classRows,
  compareWithHold,
  curve,
  editForm,
  floorAtStart,
  forwardLine,
  groupByMoney,
  isExperiment,
  isLiveTest,
  isRealMoney,
  liveVenueCash,
  realMoneyRows,
  realMoneyState,
  LIVE_PHRASE,
  LIVE_TEST_PHRASE,
  liveConfirmed,
  liveTestCap,
  liveTestProblems,
  lossAllowance,
  loosensLoss,
  startPhrase,
  maturity,
  planEdit,
  sleeveExposure,
  worstDip,
} from "./autopilot";
import type { AutopilotConfig, AutopilotStatus } from "./types";

function status(over: Partial<AutopilotStatus> = {}): AutopilotStatus {
  return {
    config: {
      id: "a",
      name: "A",
      mode: "paper",
      venue: "kraken",
      capitalUsd: 10_000,
      sleeves: [],
      stop: { onTakeProfit: "stop" },
      flattenOnStop: true,
    },
    state: "running",
    stopReason: null,
    pausedReason: null,
    stoppedMs: null,
    targetEquity: null,
    openPositions: 0,
    lastAction: null,
    startedMs: 0,
    startCapital: 10_000,
    equity: 10_000,
    pnl: 0,
    pnlPct: 0,
    peakEquity: 10_000,
    drawdownPct: 0,
    floorEquity: 0,
    trades: 0,
    fees: 0,
    bySleeve: [],
    history: [],
    ...over,
  };
}

describe("floorAtStart", () => {
  it("has no floor when no loss rule is set", () => {
    expect(floorAtStart(10_000, { onTakeProfit: "stop" }).floor).toBeNull();
  });

  it("takes the highest of the loss rules, because that one is hit first", () => {
    const p = floorAtStart(10_000, { maxLossPct: 15, maxLossUsd: 1_000, trailingPct: 20, onTakeProfit: "stop" });
    expect(p.floor).toBe(9_000);
    expect(p.by).toBe("lossUsd");
  });

  it("ignores empty and zero limits", () => {
    expect(floorAtStart(10_000, { maxLossPct: 0, maxLossUsd: NaN, onTakeProfit: "stop" }).floor).toBeNull();
  });

  it("never goes below zero and reports the take-profit level", () => {
    const p = floorAtStart(500, { maxLossUsd: 900, takeProfitPct: 20, onTakeProfit: "lock" });
    expect(p.floor).toBe(0);
    expect(p.takeProfitAt).toBe(600);
  });
});

describe("worstDip", () => {
  it("finds the deepest fall from a high to a later low", () => {
    const d = worstDip([
      [0, 100],
      [1, 120],
      [2, 90],
      [3, 130],
      [4, 110],
    ]);
    expect(d?.pct).toBeCloseTo(25);
    expect(d?.usd).toBe(30);
    expect(d?.peakMs).toBe(1);
    expect(d?.troughMs).toBe(2);
  });

  it("is null for a curve that only rises", () => {
    expect(worstDip([[0, 1], [1, 2], [2, 3]])).toBeNull();
  });
});

describe("breakdown", () => {
  it("treats pnl as net of fees and reports the cost share of gross", () => {
    const b = breakdown(status({ pnl: 900, fees: 100 }));
    expect(b.gross).toBe(1_000);
    expect(b.costShare).toBeCloseTo(0.1);
    expect(b.costHeavy).toBe(false);
  });

  it("flags fees paid on no gross profit", () => {
    const b = breakdown(status({ pnl: -150, fees: 50 }));
    expect(b.costShare).toBeUndefined();
    expect(b.costHeavy).toBe(true);
  });
});

describe("maturity", () => {
  it("needs both 30 days and 30 trades", () => {
    expect(maturity(40, 12)).toMatchObject({ enough: false, daysLeft: 0, tradesLeft: 18 });
    expect(maturity(29.2, 50)).toMatchObject({ enough: false, daysLeft: 1, tradesLeft: 0 });
    expect(maturity(30, 30).enough).toBe(true);
  });
});

describe("curve", () => {
  it("ends at the current equity", () => {
    const pts = curve(status({ history: [[0, 10_000], [10, 10_100]], equity: 10_200 }), 20);
    expect(pts[pts.length - 1]).toEqual([20, 10_200]);
  });

  it("draws start to now when there is no history yet", () => {
    expect(curve(status({ startedMs: 5, equity: 9_900 }), 50)).toEqual([[5, 10_000], [50, 9_900]]);
  });
});

describe("compareWithHold", () => {
  const times = [0, 10, 20, 30, 40];
  const closes = [100, 110, 105, 120, 130];
  const run: [number, number][] = [[0, 1_000], [20, 1_050], [40, 1_020]];

  it("compares the same window", () => {
    const c = compareWithHold(run, times, closes, 0, 40);
    expect(c?.holdPct).toBeCloseTo(30);
    expect(c?.runPct).toBeCloseTo(2);
    expect(c?.partial).toBe(false);
  });

  it("says when the price history does not reach back to the start", () => {
    const c = compareWithHold(run, [20, 30, 40], [105, 120, 130], 0, 40);
    expect(c?.fromMs).toBe(20);
    expect(c?.partial).toBe(true);
    expect(c?.runPct).toBeCloseTo((1_020 / 1_050 - 1) * 100);
  });

  it("refuses to guess without bar times", () => {
    expect(compareWithHold(run, undefined, closes, 0, 40)).toBeNull();
    expect(compareWithHold(run, [100, 110], [1, 2], 0, 40)).toBeNull();
  });
});

describe("analyse", () => {
  it("reports trades per day and sorts strategies best first", () => {
    const a = analyse(
      status({
        startedMs: 0,
        stoppedMs: 4 * DAY_MS,
        state: "stopped",
        trades: 10,
        bySleeve: [
          { strategyId: "x", name: "X", weight: 0.5, pnl: -5, trades: 4, markets: [], why: "" },
          { strategyId: "y", name: "Y", weight: 0.5, pnl: 20, trades: 6, markets: [], why: "" },
        ],
      }),
      99 * DAY_MS,
    );
    expect(a.days).toBe(4);
    expect(a.tradesPerDay).toBe(2.5);
    expect(a.sleeves.map((s) => s.strategyId)).toEqual(["y", "x"]);
  });

  it("does not invent a daily rate in the first hour", () => {
    expect(analyse(status({ trades: 3 }), 10 * 60_000).tradesPerDay).toBeNull();
  });
});

describe("forwardLine", () => {
  const f = (over: Partial<NonNullable<AutopilotStatus["forward"]>>) => ({
    status: "ok" as const,
    days: 12,
    returnPct: 1,
    bandLowPct: -4,
    bandHighPct: 5,
    ...over,
  });

  it("says nothing without forward data", () => {
    expect(forwardLine(undefined)).toBeNull();
    expect(forwardLine(null)).toBeNull();
  });

  it("is too early under ten days, whatever the return", () => {
    expect(forwardLine(f({ status: "early", days: 3.7, returnPct: -20 }))).toEqual({
      tone: "neutral",
      text: "Too early to tell: 3 of the 10 days it needs.",
    });
    expect(forwardLine(f({ status: "early", days: 0.2 }))!.text).toBe(
      "Too early to tell: it needs 10 days before it is held against the backtest.",
    );
  });

  it("is in line, ahead, below or worth watching in plain words", () => {
    expect(forwardLine(f({}))).toEqual({ tone: "good", text: "In line with its backtest after 12 days." });
    expect(forwardLine(f({ returnPct: 9 }))!.text).toBe("Ahead of its backtest range after 12 days, which can be luck as easily as skill.");
    expect(forwardLine(f({ status: "below", returnPct: -7 }))).toEqual({ tone: "bad", text: "Below its backtest range after 12 days." });
    expect(forwardLine(f({ status: "watch" }))!.tone).toBe("warn");
    expect(forwardLine(f({ status: "none", bandLowPct: null, bandHighPct: null }))!.text).toBe("No backtest range to compare with.");
  });

  it("never uses an em dash", () => {
    for (const status of ["early", "ok", "watch", "below", "none"] as const) {
      for (const days of [0.5, 3, 12]) expect(forwardLine(f({ status, days }))!.text).not.toContain(String.fromCharCode(0x2014));
    }
  });
});

describe("sleeveExposure", () => {
  const base = { strategyId: "lab:a", name: "Lab A", weight: 0.6, pnl: 0, trades: 0, why: "", markets: [] };
  it("names the weight and what it holds", () => {
    expect(sleeveExposure({ ...base, exposure: 6_012.4, exposurePct: 60.1 })).toBe("60% of the amount, holds $6,012 (60% of its worth)");
  });
  it("says in cash when it holds nothing, also for an older engine without the field", () => {
    expect(sleeveExposure({ ...base, exposure: 0, exposurePct: 0 })).toBe("60% of the amount, in cash right now");
    expect(sleeveExposure(base)).toBe("60% of the amount, in cash right now");
  });
  it("says a dropped sleeve is being sold down or done", () => {
    expect(sleeveExposure({ ...base, weight: 0, dropped: true, exposure: 120 })).toBe("Taken out, what it holds winds down at the next rebalance");
    expect(sleeveExposure({ ...base, weight: 0, dropped: true, exposure: 0 })).toBe("Taken out, holds nothing");
  });
});

describe("editing a running autopilot", () => {
  const cfg = (over: Partial<AutopilotConfig> = {}): AutopilotConfig => ({
    id: "a",
    name: "Momentum",
    mode: "paper",
    venue: "alpaca",
    assetClass: "crypto",
    capitalUsd: 10_000,
    sleeves: [{ strategyId: "lab:tsmom_top20", weight: 1 }],
    stop: { onTakeProfit: "stop", maxLossPct: 10, maxLossUsd: null, trailingPct: null, takeProfitPct: 30 },
    flattenOnStop: true,
    ...over,
  });

  it("fills the form with what runs now and sends nothing when nothing changed", () => {
    const f = editForm(cfg());
    expect(f).toMatchObject({ name: "Momentum", amount: "10000", pick: "manual", lossPct: "10", lossUsd: "", trailing: "" });
    expect(f.weights).toEqual({ "lab:tsmom_top20": "1" });
    const p = planEdit(cfg(), f);
    expect(p.changed).toBe(false);
    expect(p.update).toEqual({});
    expect(p.problems).toEqual([]);
  });

  it("switches strategies without touching the rest", () => {
    const f = { ...editForm(cfg()), weights: { "lab:tsmom_top20": "", "lab:tsmom_tranches": "1" } };
    const p = planEdit(cfg(), f);
    expect(p.update).toEqual({ sleeves: [{ strategyId: "lab:tsmom_tranches", weight: 1 }] });
    expect(p.looser).toBe(false);
    expect(planEdit(cfg(), { ...f, pick: "auto" }).update).toEqual({ sleeves: [] });
    expect(planEdit(cfg(), { ...f, weights: {} }).problems).toContain("Pick at least one strategy with a share above zero.");
  });

  it("keeps the profit target and end time and flags a looser loss limit", () => {
    const tighter = planEdit(cfg(), { ...editForm(cfg()), lossPct: "5", trailing: "8" });
    expect(tighter.update.stop).toMatchObject({ maxLossPct: 5, trailingPct: 8, takeProfitPct: 30, onTakeProfit: "stop" });
    expect(tighter.looser).toBe(false);
    expect(planEdit(cfg(), { ...editForm(cfg()), lossPct: "20" }).looser).toBe(true);
    expect(planEdit(cfg(), { ...editForm(cfg()), lossPct: "" }).looser).toBe(true);
    // More money at the same percent can lose more dollars.
    const more = planEdit(cfg(), { ...editForm(cfg()), amount: "20000" });
    expect(more.update).toEqual({ capitalUsd: 20_000 });
    expect(more.looser).toBe(true);
    const less = planEdit(cfg(), { ...editForm(cfg()), amount: "5,000" });
    expect(less.update).toEqual({ capitalUsd: 5_000 });
    expect(less.looser).toBe(false);
  });

  it("says what is wrong in plain words, and live keeps a loss limit", () => {
    expect(planEdit(cfg(), { ...editForm(cfg()), amount: "0" }).problems).toContain("Enter an amount above zero.");
    expect(planEdit(cfg(), { ...editForm(cfg()), lossUsd: "20000" }).problems[0]).toMatch(/at most the amount/);
    const live = cfg({ mode: "live" });
    expect(planEdit(live, { ...editForm(live), lossPct: "" }).problems).toContain("Real money needs a loss limit, in percent or in dollars.");
    expect(lossAllowance({ onTakeProfit: "stop", maxLossPct: 10, maxLossUsd: 500 }, 10_000)).toEqual({ usd: 500, pct: 5 });
    expect(loosensLoss({ onTakeProfit: "stop" }, 1_000, { onTakeProfit: "stop", maxLossPct: 50 }, 1_000)).toBe(false);
  });
});

describe("portfolio across asset classes", () => {
  const portfolio = status({
    classes: [
      { class: "crypto", label: "Crypto", weight: 0.62, pnl: 40, exposure: 3_100.4, books: 2 },
      { class: "alpaca", label: "US shares", weight: 0.38, pnl: 0, exposure: 0, books: 1, note: "Rebalances only in the regular session: US regular session closed." },
    ],
    benchmark: {
      symbol: "BTC/USD+SPY",
      name: "Blend",
      returnPct: 1,
      excessPct: 0,
      legs: [
        { symbol: "BTC/USD", weight: 0.62, returnPct: 1.2 },
        { symbol: "SPY", weight: 0.38, returnPct: 0.7 },
      ],
    },
  });

  it("lists each class with its share, what it holds and why it waits", () => {
    expect(classRows(portfolio)).toEqual([
      { key: "crypto", label: "Crypto", share: "62%", detail: "Holds $3,100 in 2 lab books", pnl: 40, note: null },
      { key: "alpaca", label: "US shares", share: "38%", detail: "In cash, 1 lab book", pnl: 0, note: "Rebalances only in the regular session: US regular session closed." },
    ]);
    const none = status({ classes: [{ class: "alpaca", label: "US shares", weight: 0, pnl: 0, exposure: 0, books: 0 }] });
    expect(classRows(none)[0].detail).toBe("No book with evidence");
    expect(classRows(status())).toEqual([]);
  });

  it("says the blend in a few words, and nothing for a single benchmark", () => {
    expect(blendWords(portfolio)).toBe("62% BTC, 38% SPY");
    expect(blendWords(status({ benchmark: { symbol: "SPY", name: "SPY buy and hold", returnPct: 1, excessPct: 0 } }))).toBeNull();
  });
});

describe("isExperiment", () => {
  it("knows an experimental lab book by the engine's flag or the lab's label", () => {
    expect(isExperiment({ experimental: true, name: "Lab · memes" })).toBe(true);
    expect(isExperiment({ name: "Lab · EXPERIMENT, failed deflation · memecoins top 1" })).toBe(true);
    expect(isExperiment({ name: "Lab · Donchian 20/10" })).toBe(false);
    expect(isExperiment({ experimental: false, name: "an experimental idea" })).toBe(false);
    expect(isExperiment(undefined)).toBe(false);
  });
});

describe("a capped live test", () => {
  const live = (over: Partial<AutopilotConfig> = {}): AutopilotConfig => ({
    id: "t",
    name: "Test",
    mode: "live",
    venue: "kraken",
    capitalUsd: 100,
    sleeves: [{ strategyId: "lab:tsmom_top20", weight: 1 }],
    stop: { onTakeProfit: "stop", maxLossPct: 20 },
    flattenOnStop: true,
    liveTest: true,
    ...over,
  });

  it("reads the cap from the engine, falls back to 120 and never goes above 300", () => {
    expect(liveTestCap(undefined)).toBe(120);
    expect(liveTestCap({})).toBe(120);
    expect(liveTestCap({ liveTestCapUsd: 0 })).toBe(120);
    expect(liveTestCap({ liveTestCapUsd: 80 })).toBe(80);
    expect(liveTestCap({ liveTestCapUsd: 1_000 })).toBe(300);
  });

  it("is a test only in live mode", () => {
    expect(isLiveTest(live())).toBe(true);
    expect(isLiveTest(live({ mode: "paper" }))).toBe(false);
    expect(isLiveTest(live({ liveTest: undefined }))).toBe(false);
    expect(isLiveTest(undefined)).toBe(false);
  });

  it("is confirmed with its own phrase, distinct from a normal live start", () => {
    expect(LIVE_TEST_PHRASE).not.toBe(LIVE_PHRASE);
    expect(startPhrase(live())).toBe("START LIVE TEST");
    expect(startPhrase(live({ liveTest: false }))).toBe("START LIVE");
    expect(liveConfirmed(live(), " start live test ")).toBe(true);
    expect(liveConfirmed(live(), LIVE_PHRASE)).toBe(false);
    expect(liveConfirmed(live({ liveTest: false }), LIVE_TEST_PHRASE)).toBe(false);
    expect(liveConfirmed(live({ liveTest: false }), LIVE_PHRASE)).toBe(true);
    expect(liveConfirmed(live(), undefined)).toBe(false);
  });

  it("names every cap it breaks, as the engine does", () => {
    const stop = { onTakeProfit: "stop" as const, maxLossPct: 20 };
    expect(liveTestProblems({ capital: 100, cap: 120, stop })).toEqual([]);
    expect(liveTestProblems({ capital: 150, cap: 120, stop })).toEqual(["A capped live test may trade at most $120.00, not $150.00."]);
    expect(liveTestProblems({ capital: 100, cap: 120, stop: { onTakeProfit: "stop" } })[0]).toMatch(/needs a loss limit of at most 25%/);
    expect(liveTestProblems({ capital: 100, cap: 120, stop: { onTakeProfit: "stop", maxLossPct: 30 } })).toEqual([
      "A capped live test needs a loss limit of at most 25% of the amount; this one allows $30.00 (30%).",
    ]);
    // The tighter of two rules is what it may lose.
    expect(liveTestProblems({ capital: 100, cap: 120, stop: { onTakeProfit: "stop", maxLossPct: 50, maxLossUsd: 25 } })).toEqual([]);
    expect(liveTestProblems({ capital: 100, cap: 120, stop, otherTest: "First" })).toEqual([
      '"First" is already a capped live test, and only one runs at a time. Stop it first.',
    ]);
  });

  it("keeps its caps when it is changed", () => {
    const c = live();
    const f = editForm(c);
    expect(planEdit(c, f).problems).toEqual([]);
    expect(planEdit(c, { ...f, amount: "200" }).problems).toContain("A capped live test may trade at most $120.00, not $200.00.");
    expect(planEdit(c, { ...f, amount: "200" }, 300).problems).toEqual([]);
    expect(planEdit(c, { ...f, lossPct: "40" }).problems[0]).toMatch(/at most 25%/);
    expect(planEdit(c, { ...f, pick: "auto" }).problems).toContain("A capped live test runs only strategies you name.");
    // A plain live autopilot has no such caps.
    expect(planEdit(live({ liveTest: false }), { ...f, amount: "5000", lossPct: "40" }).problems).toEqual([]);
  });
});

describe("real money apart from practice", () => {
  const cfg = (id: string, mode: AutopilotConfig["mode"], over: Partial<AutopilotConfig> = {}) =>
    status({ config: { ...status().config, id, name: id, mode, ...over } });
  const armed = { armed: true, venues: ["crypto" as const], dryRun: false, paper: false };

  it("groups live and live tests as real money and keeps the order inside each group", () => {
    const list = [cfg("p1", "paper"), cfg("l1", "live"), cfg("d1", "demo"), cfg("t1", "live", { liveTest: true }), cfg("p2", "paper")];
    const g = groupByMoney(list);
    expect(g.real.map((s) => s.config.id)).toEqual(["l1", "t1"]);
    expect(g.practice.map((s) => s.config.id)).toEqual(["p1", "d1", "p2"]);
    expect(isRealMoney(cfg("x", "demo"))).toBe(false);
    expect(groupByMoney([])).toEqual({ real: [], practice: [] });
  });

  it("says whether live trading is armed for it, and why it is paused", () => {
    const s = cfg("l", "live");
    expect(realMoneyState(s, armed)).toEqual({ tone: "good", text: "Armed" });
    expect(realMoneyState(s, { ...armed, armed: false }).text).toBe("Live trading is disarmed");
    expect(realMoneyState(s, { ...armed, venues: ["alpaca"] }).tone).toBe("bad");
    const paused = { ...s, state: "paused" as const };
    expect(realMoneyState(paused, { ...armed, armed: false })).toEqual({ tone: "bad", text: "Paused: live trading is disarmed" });
    expect(realMoneyState(paused, armed).text).toBe("Armed, paused");
    expect(realMoneyState(s, { ...armed, dryRun: true }).tone).toBe("warn");
    const shares = cfg("a", "live", { venue: "alpaca" });
    expect(realMoneyState(shares, { ...armed, venues: ["alpaca"], paper: true }).text).toBe("Armed on the Alpaca paper endpoint");
  });

  it("uses the live venue's own cash, never the paper account's", () => {
    const live = { liveCash: [{ venue: "crypto" as const, exchange: "kraken" as const, cash: 412.5, readMs: 1 }] };
    expect(liveVenueCash(live, "crypto")?.cash).toBe(412.5);
    expect(liveVenueCash(live, "alpaca")).toBeUndefined();
    expect(liveVenueCash({}, "crypto")).toBeUndefined();
    expect(liveVenueCash(undefined, "crypto")).toBeUndefined();

    const t = { ...cfg("t", "live", { liveTest: true }), startCapital: 100, equity: 92, pnl: -8, pnlPct: -8 };
    const rows = realMoneyRows([cfg("p", "paper"), t], { ...armed, ...live });
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ id: "t", liveTest: true, exchange: "kraken", amount: 100, equity: 92, pnl: -8, state: { text: "Armed" } });
    expect(rows[0].venueCash?.cash).toBe(412.5);
  });
});
