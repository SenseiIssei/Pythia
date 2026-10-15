import { describe, expect, it } from "vitest";
import { brierGap, capsNote, parseCap, usd, usedShare, vsRows, type AiScores } from "./aiBudget";

describe("usedShare", () => {
  it("is the share of the cap spent, clamped", () => {
    expect(usedShare(45, 90)).toBe(0.5);
    expect(usedShare(120, 90)).toBe(1);
    expect(usedShare(-1, 90)).toBe(0);
  });
  it("treats a zero cap as fully used: it switches calls off", () => {
    expect(usedShare(0, 0)).toBe(1);
  });
});

describe("parseCap", () => {
  it("reads dollars, with or without the sign or a comma", () => {
    expect(parseCap("15")).toBe(15);
    expect(parseCap("$1.5")).toBe(1.5);
    expect(parseCap("1,5")).toBe(1.5);
    expect(parseCap("0")).toBe(0);
  });
  it("refuses what the engine would refuse", () => {
    expect(parseCap("")).toMatch(/Enter/);
    expect(parseCap("abc")).toMatch(/number/);
    expect(parseCap("-2")).toMatch(/negative/);
    expect(parseCap("5000")).toMatch(/At most/);
  });
});

describe("capsNote", () => {
  it("says when a cap can never be the one that stops calls", () => {
    expect(capsNote({ lifetimeUsd: 90, monthlyUsd: 15, dailyUsd: 1.5 })).toBeNull();
    expect(capsNote({ lifetimeUsd: 10, monthlyUsd: 15, dailyUsd: 1.5 })).toMatch(/lifetime cap is what stops/);
    expect(capsNote({ lifetimeUsd: 90, monthlyUsd: 15, dailyUsd: 0 })).toMatch(/switches every Claude call off/);
  });
});

describe("usd", () => {
  it("shows fractions of a cent", () => {
    expect(usd(0.0004)).toBe("$0.0004");
    expect(usd(12.3)).toBe("$12.30");
    expect(usd(null)).toBe("n/a");
  });
});

const scores = (llm: number | null, mom: number | null, base: number | null): AiScores => ({
  generated_ms: 0,
  horizon_days: 7,
  predictions: 40,
  resolved: 35,
  pending: 5,
  models: ["claude-haiku-5-5"],
  sources: {
    llm: { n: 35, brier: llm, logloss: 0.69, hitRate: 0.5, meanP: 0.5 },
    momentum: { n: 35, brier: mom, logloss: 0.69, hitRate: 0.5, meanP: 0.5 },
    base: { n: 35, brier: base, logloss: 0.69, hitRate: 0.5, meanP: 0.5 },
  },
  vs: { base: { n: 35, diff: null, t: null }, momentum: { n: 35, diff: null, t: null } },
  verdict: "",
  reliability: [],
  by_coin: [],
  references: { base: "share of up weeks", momentum: "28-day sign" },
});

describe("vsRows", () => {
  it("lists the LLM next to our two references and marks the lowest Brier", () => {
    const rows = vsRows(scores(0.26, 0.24, 0.25));
    expect(rows.map((r) => r.key)).toEqual(["llm", "momentum", "base"]);
    expect(rows.find((r) => r.best)?.key).toBe("momentum");
    expect(rows[0].sub).toBe("claude-haiku-5-5");
  });
  it("marks nothing before anything has resolved", () => {
    expect(vsRows(scores(null, null, null)).some((r) => r.best)).toBe(false);
  });
});

describe("brierGap", () => {
  it("is the LLM's Brier minus the reference's in points, signed", () => {
    expect(brierGap({ diff: -0.02 })).toBe("-2.00 pts");
    expect(brierGap({ diff: 0.0123 })).toBe("+1.23 pts");
    expect(brierGap({ diff: null })).toBeNull();
  });
});
