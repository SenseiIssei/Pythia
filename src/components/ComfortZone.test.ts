import { describe, expect, it } from "vitest";
import { limitsFor } from "./ComfortZone";

describe("limitsFor: risk limits from the monthly loss someone can live with", () => {
  it("trips the breaker at the monthly line and stops a day at a quarter of it", () => {
    const l = limitsFor(10);
    expect(l.maxDrawdownPct).toBe(10);
    expect(l.maxDailyLossPct).toBe(2.5);
  });

  it("keeps a single position between 5 % and 25 %", () => {
    expect(limitsFor(2).maxPositionPct).toBe(5);
    expect(limitsFor(10).maxPositionPct).toBe(20);
    expect(limitsFor(20).maxPositionPct).toBe(25);
  });

  it("bets more carefully the less someone can lose", () => {
    expect(limitsFor(2).kellyFraction).toBe(0.1);
    expect(limitsFor(10).kellyFraction).toBe(0.2);
    expect(limitsFor(20).kellyFraction).toBe(0.25);
  });
});
