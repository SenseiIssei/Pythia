import { describe, expect, it } from "vitest";
import { bandScale, costLine, forwardStatus, gatePct, signedPct } from "./lab";

describe("bandScale", () => {
  it("keeps the band, zero and the actual return on the track, in order", () => {
    const s = bandScale(1, { lowPct: -2, highPct: 3, medianPct: 0.5 });
    for (const v of Object.values(s)) {
      expect(v).toBeGreaterThan(0);
      expect(v).toBeLessThan(100);
    }
    expect(s.low).toBeLessThan(s.zero);
    expect(s.zero).toBeLessThan(s.median);
    expect(s.median).toBeLessThan(s.actual);
    expect(s.actual).toBeLessThan(s.high);
  });

  it("stretches the axis to a return far outside the band", () => {
    const s = bandScale(-10, { lowPct: -2, highPct: 3, medianPct: 0.5 });
    expect(s.actual).toBeLessThan(s.low);
    expect(s.actual).toBeGreaterThan(0);
    // The band takes less than half the track when the return is that far out.
    expect(s.high - s.low).toBeLessThan(50);
  });

  it("survives a band of zero width", () => {
    const s = bandScale(0, { lowPct: 0, highPct: 0, medianPct: 0 });
    expect(s.low).toBe(s.high);
    expect(Number.isFinite(s.actual)).toBe(true);
  });
});

describe("gatePct", () => {
  const gate = { days: 12, daysNeeded: 30, trades: 3, tradesNeeded: 30, tradesLabel: "rebalances", progress: 0, ready: false };

  it("is the slower of days and trades", () => {
    expect(gatePct(gate)).toBe(10);
    expect(gatePct({ ...gate, trades: 30 })).toBe(40);
  });

  it("stops at 100", () => {
    expect(gatePct({ ...gate, days: 60, trades: 45 })).toBe(100);
  });
});

describe("forward words", () => {
  it("names every status in plain words", () => {
    expect(forwardStatus("on_track")).toEqual({ label: "on track", tone: "green" });
    expect(forwardStatus("watch").tone).toBe("amber");
    expect(forwardStatus("early").label).toBe("too early to say");
    expect(forwardStatus("something new").label).toBe("no range to compare");
  });

  it("formats signed percentages and missing values", () => {
    expect(signedPct(1.234)).toBe("+1.23 %");
    expect(signedPct(-0.5)).toBe("−0.50 %");
    expect(signedPct(null)).toBe("n/a");
    expect(signedPct(Number.NaN)).toBe("n/a");
  });

  it("puts paper costs next to the model", () => {
    expect(costLine({ paperPct: 0.084, modelPct: 0.111, ratio: 0.757, modelledOnly: false })).toBe(
      "0.084 % paid vs 0.111 % modelled, 0.76x",
    );
    expect(costLine({ paperPct: 0.1, modelPct: 0.1, ratio: null, modelledOnly: true })).toContain("modelled cost");
    expect(costLine(null)).toBeNull();
  });
});
