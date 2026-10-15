import { describe, expect, it } from "vitest";
import {
  bunching,
  coinName,
  corrTint,
  corrWord,
  curveReturn,
  drawdownSeries,
  driftChip,
  forwardTally,
  icTone,
  labChip,
  outlook,
  sumPnl,
  signedNum,
  topPairs,
  worstDip,
} from "./insight";

describe("curves", () => {
  it("measures the dip below the running high", () => {
    expect(drawdownSeries([100, 110, 99, 120])).toEqual([0, 0, -10, 0]);
    expect(worstDip([100, 110, 99, 120])).toBeCloseTo(-10);
    expect(worstDip([])).toBe(0);
    expect(worstDip([100, 101, 102])).toBe(0);
  });
  it("gives the return from first to last point", () => {
    expect(curveReturn([100, 90, 110])).toBeCloseTo(10);
    expect(curveReturn([100])).toBeNull();
    expect(curveReturn([0, 5])).toBeNull();
    expect(curveReturn([100, NaN, 95])).toBeCloseTo(-5);
  });
  it("adds up gross, costs and net", () => {
    expect(sumPnl([])).toEqual({ gross: 0, costs: 0, net: 0 });
    expect(sumPnl([{ gross: 10, costs: 2, net: 8 }, { gross: -5, costs: 1, net: -6 }])).toEqual({ gross: 5, costs: 3, net: 2 });
  });
});

describe("correlation", () => {
  const corr = {
    ids: ["a", "b", "c", "d"],
    matrix: [
      [1, 0.9, -0.5, null],
      [0.9, 1, 0.2, 0.3],
      [-0.5, 0.2, 1, 0.1],
      [null, 0.3, 0.1, 1],
    ],
  };
  it("tints with theme tokens, never a hex colour", () => {
    expect(corrTint(0.9)).toMatch(/^rgb\(var\(--pt-down\) \/ 0\.\d+\)$/);
    expect(corrTint(-0.9)).toMatch(/^rgb\(var\(--pt-up\) \//);
    expect(corrTint(null)).toBe("transparent");
    expect(corrTint(1)).not.toMatch(/#/);
  });
  it("says what a number means", () => {
    expect(corrWord(0.85)).toBe("move almost as one");
    expect(corrWord(0.5)).toBe("often move together");
    expect(corrWord(0)).toBe("mostly independent");
    expect(corrWord(-0.5)).toBe("often move opposite");
    expect(corrWord(-0.9)).toBe("move almost opposite");
    expect(corrWord(null)).toBe("cannot be compared");
  });
  it("lists the strongest pairs, skipping the diagonal and unknowns", () => {
    const p = topPairs(corr, [], 3);
    expect(p.map((x) => `${x.a}${x.b}`)).toEqual(["ab", "ac", "bd"]);
    expect(p.every((x) => !x.held)).toBe(true);
  });
  it("puts held pairs first", () => {
    const p = topPairs(corr, ["c", "d"], 2);
    expect(p[0]).toMatchObject({ a: "c", b: "d", held: true });
    expect(p[1]).toMatchObject({ a: "a", b: "b", held: false });
    expect(topPairs(corr, ["c", "d"], 1, false)[0]).toMatchObject({ a: "a", b: "b" });
    expect(topPairs(corr, [], 0)).toEqual([]);
  });
  it("judges how bunched the positions are", () => {
    expect(bunching(1, 1).tone).toBe("plain");
    expect(bunching(4, 1.5).tone).toBe("down");
    expect(bunching(4, 2.8).tone).toBe("warn");
    expect(bunching(4, 3.6).tone).toBe("up");
  });
});

describe("models", () => {
  it("compares the forecast with the week", () => {
    expect(outlook(130, 100)).toEqual({ word: "busier than usual", tone: "bad" });
    expect(outlook(70, 100)).toEqual({ word: "calmer than usual", tone: "good" });
    expect(outlook(100, 100).word).toBe("normal");
    expect(outlook(100, 0).word).toBe("normal");
  });
  it("names drift levels", () => {
    expect(driftChip("stable").tone).toBe("good");
    expect(driftChip("shift").tone).toBe("accent");
    expect(driftChip("drift")).toEqual({ word: "outside trained range", tone: "bad" });
  });
  it("judges live ranking skill against the lab", () => {
    expect(icTone(null, 0.05)).toBe("plain");
    expect(icTone(0.03, 0.05)).toBe("up");
    expect(icTone(0.01, 0.05)).toBe("warn");
    expect(icTone(-0.01, 0.05)).toBe("down");
    expect(icTone(0.02, null)).toBe("warn");
  });
});

describe("lab", () => {
  it("maps old tones to chip tones", () => {
    expect(labChip("green")).toBe("good");
    expect(labChip("cyan")).toBe("good");
    expect(labChip("amber")).toBe("warn");
    expect(labChip("red")).toBe("bad");
    expect(labChip("purple")).toBe("accent");
    expect(labChip("neutral")).toBe("neutral");
  });
  it("tallies forward tests", () => {
    const g = (ready: boolean) => ({ ready });
    expect(
      forwardTally([
        { status: "on_track", gate7: g(true) },
        { status: "ahead", gate7: g(false) },
        { status: "watch", gate7: g(false) },
        { status: "early", gate7: g(false) },
      ]),
    ).toEqual({ total: 4, fine: 2, watch: 1, ready: 1 });
    expect(forwardTally([])).toEqual({ total: 0, fine: 0, watch: 0, ready: 0 });
  });
  it("signs plain numbers with a real minus", () => {
    expect(signedNum(0.1234)).toBe("+0.123");
    expect(signedNum(-0.04)).toBe("−0.040");
    expect(signedNum(0.0001)).toBe("0.000");
    expect(signedNum(null)).toBe("n/a");
    expect(signedNum(2.5, 1)).toBe("+2.5");
  });
  it("shortens coin names", () => {
    expect(coinName("BTCUSDT")).toBe("BTC");
    expect(coinName("ETH")).toBe("ETH");
  });
});
