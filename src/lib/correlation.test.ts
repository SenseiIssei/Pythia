import { describe, expect, it } from "vitest";
import { alignedPearson, concentration, correlationMatrix, pearson, toReturns } from "./correlation";

/** 60 deterministic closes with the same moves as the Rust tests' `wiggle`. */
function series(n = 60, sign = 1): number[] {
  let p = 100;
  return Array.from({ length: n }, (_, i) => {
    p *= 1 + sign * (Math.sin(i * 1.7) + Math.cos(i * 0.31) * 0.5) * 0.01;
    return p;
  });
}

const FIVE_MIN = 300_000;
const times = (n: number, start = 0) => Array.from({ length: n }, (_, i) => start + i * FIVE_MIN);

describe("correlation on aligned time", () => {
  it("compares candles on the bar times both have, not on their position", () => {
    const a = series();
    const ta = times(60);
    // b is missing the bar at index 30.
    const b = a.filter((_, i) => i !== 30);
    const tb = ta.filter((_, i) => i !== 30);
    expect(alignedPearson(a, ta, b, tb)).toBeCloseTo(1, 9);
    // Lined up by position instead, the returns before the gap are shifted.
    expect(pearson(toReturns(a), toReturns(b))).toBeLessThan(0.99);
  });

  it("finds nothing to compare when the candles share no times", () => {
    const a = series();
    expect(alignedPearson(a, times(60), a, times(60, 86_400_000))).toBeNull();
  });

  it("never pairs a candle market with a tick market", () => {
    const s = series();
    const corr = correlationMatrix({ bar: s, tick: s, tick2: s }, { bar: times(60) });
    const at = (x: string, y: string) => corr.matrix[corr.ids.indexOf(x)][corr.ids.indexOf(y)];
    expect(at("bar", "tick")).toBeNull();
    expect(at("tick", "tick2")).toBeCloseTo(1, 9);
    expect(at("bar", "bar")).toBe(1);
  });

  it("counts a pair it cannot compare as moving together, like the risk manager", () => {
    const s = series();
    const corr = correlationMatrix({ bar: s, tick: series(60, -1) }, { bar: times(60) });
    const c = concentration(["bar", "tick"], corr);
    expect(c.unmeasured).toBe(1);
    expect(c.avgAbsCorr).toBe(1);
    expect(c.effectiveBets).toBeCloseTo(1, 9);
  });
});
