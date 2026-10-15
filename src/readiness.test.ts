import { describe, expect, it } from "vitest";
import { ordered, parseReadiness, profileFor, profileWords, progressWords, type ReadinessItem } from "./readiness";

const rule = (id: string, pass: boolean) => ({ id, label: id, pass, value: "", need: "", detail: "" });

const file = {
  title: "Real money readiness",
  generated_ms: 1_792_000_000_000,
  rule_date: "2026-10-15",
  profile: { step: 3, label: "balanced", max_dd_pct: 10, etf_hurdle_pct: 10, min_positive_weeks: 3, min_days: 38 },
  profiles: [
    { step: 1, label: "careful", max_dd_pct: 5, etf_hurdle_pct: 7, min_positive_weeks: 4, min_days: 45 },
    { step: 2, label: "cautious", max_dd_pct: 7.5, etf_hurdle_pct: 8.5, min_positive_weeks: 4, min_days: 41 },
    { step: 3, label: "balanced", max_dd_pct: 10, etf_hurdle_pct: 10, min_positive_weeks: 3, min_days: 38 },
  ],
  inflation: { pct: 3.8, source: "euro area HICP (Eurostat)", month: "2026-09", cached: false },
  headline: "None ready.",
  autopilots: [
    {
      kind: "sleeve",
      key: "sleeve:ap-1:1:lab:a",
      id: "lab:a",
      name: "A (sleeve of One)",
      parent: "ap-1",
      on_account: true,
      days: 12,
      ready: false,
      passed: 5,
      total: 9,
      days_to_go: 41,
      rules: [rule("record", false), rule("profit", true)],
    },
    {
      kind: "autopilot",
      key: "autopilot:ap-1:1",
      id: "ap-1",
      name: "One",
      parent: null,
      on_account: true,
      days: 12,
      ready: false,
      passed: 7,
      total: 9,
      days_to_go: 26,
      annualised_pct: 31.2,
      rules: [rule("record", false), rule("profit", true), rule("weeks", false)],
    },
  ],
};

describe("readiness", () => {
  it("reads the lab's file and refuses anything else", () => {
    const r = parseReadiness(file)!;
    expect(r.profile.label).toBe("balanced");
    expect(r.profiles).toHaveLength(3);
    expect(r.items[1].annualisedPct).toBe(31.2);
    expect(r.items[0].kind).toBe("sleeve");
    expect(r.inflation.pct).toBe(3.8);
    expect(parseReadiness(null)).toBeNull();
    expect(parseReadiness({ autopilots: [] })).toBeNull();
    expect(parseReadiness([1, 2])).toBeNull();
  });

  it("lists each autopilot before its sleeves", () => {
    const r = parseReadiness(file)!;
    expect(ordered(r.items).map((i) => i.id)).toEqual(["ap-1", "lab:a"]);
  });

  it("keeps the same autopilot id on two accounts apart", () => {
    const two = {
      ...file,
      autopilots: [
        { ...file.autopilots[1], key: "autopilot:main:ap-1:1", account: "main" },
        { ...file.autopilots[1], key: "autopilot:safe:ap-1:2", account: "safe", name: "One (safe)" },
        { ...file.autopilots[0], key: "sleeve:safe:ap-1:2:lab:a", account: "safe", parent_key: "autopilot:safe:ap-1:2" },
      ],
    };
    const r = parseReadiness(two)!;
    expect(ordered(r.items).map((i) => i.key)).toEqual([
      "autopilot:main:ap-1:1",
      "autopilot:safe:ap-1:2",
      "sleeve:safe:ap-1:2:lab:a",
    ]);
    expect(r.items[1].account).toBe("safe");
  });

  it("says days to go, what it waits on, or that it is ready", () => {
    const r = parseReadiness(file)!;
    const ap = r.items[1];
    expect(progressWords(ap)).toBe("26 days to go at the earliest");
    const waiting: ReadinessItem = { ...ap, daysToGo: 0 };
    expect(progressWords(waiting)).toBe("Waiting on days and trades, good weeks");
    expect(progressWords({ ...ap, ready: true })).toBe("Ready for a real money proposal");
    expect(progressWords({ ...ap, onAccount: false })).toBe("Not on the Alpaca paper account");
    expect(progressWords({ ...ap, daysToGo: 1 })).toBe("1 day to go at the earliest");
  });

  it("shows the numbers a risk step sets", () => {
    const r = parseReadiness(file)!;
    expect(profileWords(profileFor(r.profiles, 2)!)).toBe("drawdown at most 7.5 %, beat 8.5 % a year, 4 of 4 weeks positive, 41 days");
    expect(profileFor(r.profiles, 9)).toBeNull();
  });
});
