import { describe, expect, it } from "vitest";
import { applyFill } from "./position";

describe("applyFill", () => {
  it("opens and adds at a weighted average", () => {
    expect(applyFill(0, 0, 2, 100)).toEqual({ qty: 2, avgPrice: 100, realized: 0 });
    const r = applyFill(1, 100, 1, 110);
    expect(r.qty).toBe(2);
    expect(r.avgPrice).toBeCloseTo(105);
    expect(r.realized).toBe(0);
  });

  it("realises a full close of a long and of a short", () => {
    expect(applyFill(2, 100, -2, 110)).toEqual({ qty: 0, avgPrice: 100, realized: 20 });
    expect(applyFill(-2, 100, 2, 90)).toEqual({ qty: 0, avgPrice: 100, realized: 20 });
  });

  it("realises a partial reduction and keeps the entry price of what is left", () => {
    // The old test compared the sign of the result, so this looked like an
    // add: nothing was realised and the average drifted toward the exit.
    const r = applyFill(4, 100, -1, 120);
    expect(r.qty).toBe(3);
    expect(r.avgPrice).toBe(100);
    expect(r.realized).toBeCloseTo(20);
  });

  it("restarts the remainder at the fill price when a fill flips the side", () => {
    const r = applyFill(1, 100, -3, 90);
    expect(r.qty).toBe(-2);
    expect(r.avgPrice).toBe(90);
    expect(r.realized).toBeCloseTo(-10);
  });
});
