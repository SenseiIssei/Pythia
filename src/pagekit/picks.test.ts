import { describe, expect, it } from "vitest";
import type { AiView, ForecastStats } from "../types";
import {
  actionWord,
  ageText,
  bps,
  directionWord,
  forecastCall,
  gateValue,
  plainReason,
  predictionSummary,
  recentViews,
  sortByEdge,
  stateInfo,
  strategyBlurb,
  strategySummary,
  strengthWord,
  viewCounts,
} from "./picks";

describe("forecastCall", () => {
  it("calls event markets yes or no, with a toss-up band", () => {
    expect(forecastCall({ kind: "outcome", ensembleP: 0.85 })).toMatchObject({ call: "Very likely yes", lean: "up", chance: "85%", of: "chance of yes" });
    expect(forecastCall({ kind: "outcome", ensembleP: 0.62 }).call).toBe("Likely yes");
    expect(forecastCall({ kind: "outcome", ensembleP: 0.55 }).call).toBe("Leans yes");
    expect(forecastCall({ kind: "outcome", ensembleP: 0.5 })).toMatchObject({ call: "Too close to call", lean: "flat" });
    expect(forecastCall({ kind: "outcome", ensembleP: 0.45 }).call).toBe("Leans no");
    expect(forecastCall({ kind: "outcome", ensembleP: 0.3 }).call).toBe("Likely no");
    expect(forecastCall({ kind: "outcome", ensembleP: 0.1 })).toMatchObject({ call: "Very likely no", lean: "down" });
  });
  it("calls price markets up or down, and admits when it has no idea", () => {
    expect(forecastCall({ kind: "direction", ensembleP: 0.56 })).toMatchObject({ call: "Leans up", lean: "up", of: "chance it rises" });
    expect(forecastCall({ kind: "direction", ensembleP: 0.44 })).toMatchObject({ call: "Leans down", lean: "down" });
    expect(forecastCall({ kind: "direction", ensembleP: 0.505 })).toMatchObject({ call: "No clear direction", lean: "flat", chance: "51%" });
  });
  it("treats a broken number as 50 %", () => {
    expect(forecastCall({ kind: "direction", ensembleP: NaN })).toMatchObject({ lean: "flat", chance: "50%" });
  });
});

describe("prediction helpers", () => {
  it("says what it would do", () => {
    expect(actionWord("buy")).toEqual({ label: "Would buy", tone: "good" });
    expect(actionWord("sell")).toEqual({ label: "Would sell", tone: "bad" });
    expect(actionWord("hold")).toEqual({ label: "Not acting", tone: "neutral" });
  });
  it("sorts by net edge without touching the input", () => {
    const input = [{ netEdgeBps: -5 }, { netEdgeBps: 30 }, { netEdgeBps: 0 }];
    expect(sortByEdge(input).map((f) => f.netEdgeBps)).toEqual([30, 0, -5]);
    expect(input[0].netEdgeBps).toBe(-5);
  });
  it("summarises the page", () => {
    const stats: ForecastStats = { recorded: 120, resolved: 80, pending: 40, trustedSources: 1 };
    const s = predictionSummary([{ action: "hold" }, { action: "buy" }, { action: "sell" }], stats, [{ source: "a" }, { source: "a" }, { source: "b" }]);
    expect(s).toEqual({ total: 3, acting: 2, trusted: 1, sources: 2, checked: 80, waiting: 40, recorded: 120 });
  });
  it("never reports fewer sources than trusted ones", () => {
    const s = predictionSummary([], { recorded: 0, resolved: 0, pending: 0, trustedSources: 3 }, []);
    expect(s.sources).toBe(3);
  });
  it("translates the engine's reasons", () => {
    expect(plainReason("no track record beats the market")).toMatch(/proven itself/);
    expect(plainReason("edge below the round-trip cost")).toMatch(/fees/);
    expect(plainReason("edge below the minimum")).toMatch(/too small/);
    expect(plainReason("no forecaster")).toMatch(/no opinion|Nothing has an opinion/);
    expect(plainReason("something new")).toBe("something new");
  });
  it("writes basis points with a real minus", () => {
    expect(bps(12.4)).toBe("+12 bps");
    expect(bps(-40)).toBe("−40 bps");
    expect(bps(0.2)).toBe("0 bps");
    expect(bps(NaN)).toBe("n/a");
  });
});

const view = (over: Partial<AiView>): AiView => ({
  marketId: "m",
  direction: "long",
  probability: 0.6,
  confidence: 0.5,
  rationale: "",
  model: "x",
  ts: 0,
  latencyMs: 100,
  ...over,
});

describe("AI signal helpers", () => {
  it("puts a word next to every direction", () => {
    expect(directionWord("long")).toEqual({ word: "Up", lean: "up" });
    expect(directionWord("short")).toEqual({ word: "Down", lean: "down" });
    expect(directionWord("neutral")).toEqual({ word: "No view", lean: "flat" });
  });
  it("names the strength", () => {
    expect(strengthWord(0.8)).toBe("Strong");
    expect(strengthWord(0.7)).toBe("Strong");
    expect(strengthWord(0.5)).toBe("Moderate");
    expect(strengthWord(0.1)).toBe("Weak");
    expect(strengthWord(NaN)).toBe("Unknown");
  });
  it("lists the newest views with their age and whether they still count", () => {
    const now = 100_000;
    const rows = recentViews([view({ marketId: "a", ts: 10_000 }), view({ marketId: "b", ts: 95_000 }), view({ marketId: "c", ts: 50_000 })], now, 60, 2);
    expect(rows.map((r) => r.view.marketId)).toEqual(["b", "c"]);
    expect(rows[0]).toMatchObject({ ageSec: 5, stale: false });
    expect(rows[1]).toMatchObject({ ageSec: 50, stale: false });
    expect(recentViews([view({ ts: 0 })], now, 60)[0].stale).toBe(true);
  });
  it("counts fresh views by direction", () => {
    const now = 100_000;
    const vs = [view({ ts: 99_000 }), view({ ts: 99_000, direction: "short" }), view({ ts: 99_000, direction: "neutral" }), view({ ts: 0 })];
    expect(viewCounts(vs, now, 60)).toEqual({ fresh: 3, up: 1, down: 1 });
  });
  it("writes ages briefly", () => {
    expect(ageText(12)).toBe("12 s ago");
    expect(ageText(-3)).toBe("0 s ago");
    expect(ageText(240)).toBe("4 min ago");
    expect(ageText(3 * 3600)).toBe("3 h ago");
  });
});

describe("strategy helpers", () => {
  it("describes every kind in one sentence and has a fallback", () => {
    expect(strategyBlurb("ema-cross")).toMatch(/average/);
    expect(strategyBlurb("something-new")).toMatch(/rule set/);
    expect(strategyBlurb("breakout").endsWith(".")).toBe(true);
  });
  it("names each state", () => {
    expect(stateInfo("live")).toMatchObject({ label: "Live", tone: "bad" });
    expect(stateInfo("paused").label).toBe("Paused");
    expect(stateInfo("demo").tone).toBe("accent");
    expect(stateInfo("paper").label).toBe("Paper");
  });
  it("adds up the page", () => {
    expect(
      strategySummary([
        { pnl: 10, state: "paper" },
        { pnl: -4, state: "live" },
        { pnl: NaN, state: "paused" },
      ]),
    ).toEqual({ pnl: 6, running: 2, live: 1, total: 3 });
  });
  it("formats gate numbers by unit", () => {
    expect(gateValue(0.123, "pct")).toBe("+12.3%");
    expect(gateValue(-0.05, "pct")).toBe("−5.0%");
    expect(gateValue(0.55, "share")).toBe("55%");
    expect(gateValue(41.6, "count")).toBe("42");
    expect(gateValue(1.234, "number")).toBe("1.23");
    expect(gateValue(-0.05, "number")).toBe("−0.050");
    expect(gateValue(undefined, "number")).toBe("n/a");
  });
});
