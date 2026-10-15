import { describe, expect, it } from "vitest";
import { capitalise, feeShare, floorRoom, modeLabel, moveWords, parseInput, pointsWord, setupProblems, splitCurve, stillToGo, type SetupCheck } from "./autopilotView";

describe("parseInput", () => {
  it("reads amounts with dollar signs, commas, spaces and percent", () => {
    expect(parseInput("$1,000")).toBe(1000);
    expect(parseInput(" 10 %")).toBe(10);
    expect(parseInput("2.5")).toBe(2.5);
  });
  it("is NaN for words", () => {
    expect(parseInput("abc")).toBeNaN();
  });
});

describe("modeLabel", () => {
  it("always says real money in red for live", () => {
    expect(modeLabel("live", true)).toEqual({ tone: "bad", text: "Real money" });
    expect(modeLabel("live", false).tone).toBe("bad");
    expect(modeLabel("live", false).text).toMatch(/real money/i);
  });
  it("names demo and practice", () => {
    expect(modeLabel("demo", true).text).toBe("Demo account");
    expect(modeLabel("paper", true).text).toBe("Practice money");
    expect(modeLabel("paper", false).text).toBe("Paper");
  });
});

describe("floorRoom", () => {
  it("is null without a floor", () => {
    expect(floorRoom(1000, null, 1000)).toBeNull();
    expect(floorRoom(1000, 0, 1000)).toBeNull();
  });
  it("measures the room from the floor to the best point", () => {
    const r = floorRoom(950, 900, 1000)!;
    expect(r.floor).toBe(900);
    expect(r.room).toBe(50);
    expect(r.pct).toBeCloseTo(50);
    expect(r.level).toBe("near");
    expect(r.word).toBe("Getting closer");
  });
  it("says plenty and close in words", () => {
    expect(floorRoom(1000, 900, 1000)!.level).toBe("ok");
    expect(floorRoom(1000, 900, 1000)!.word).toBe("Plenty of room");
    expect(floorRoom(910, 900, 1000)!.level).toBe("over");
    expect(floorRoom(910, 900, 1000)!.word).toBe("Close to the floor");
  });
  it("never shows negative room", () => {
    const r = floorRoom(880, 900, 1000)!;
    expect(r.room).toBe(0);
    expect(r.pct).toBe(0);
  });
});

describe("moveWords", () => {
  it("says up, down or no change with a signed percent", () => {
    expect(moveWords(12, 1.2)).toBe("Up $12.00 (+1.20%)");
    expect(moveWords(-5, -0.5)).toBe("Down $5.00 (−0.50%)");
    expect(moveWords(0.001, 0)).toBe("No change");
  });
});

describe("feeShare", () => {
  it("is the share of the gain before fees", () => {
    expect(feeShare(10, 30)).toBeCloseTo(0.25);
  });
  it("is null when nothing was made before fees", () => {
    expect(feeShare(10, -10)).toBeNull();
    expect(feeShare(10, -20)).toBeNull();
  });
});

describe("pointsWord", () => {
  it("counts points and says better or worse", () => {
    expect(pointsWord(2.54)).toBe("2.5 percentage points better");
    expect(pointsWord(-1)).toBe("1.0 percentage point worse");
    expect(pointsWord(0)).toBe("0.0 percentage points better");
  });
});

describe("stillToGo", () => {
  it("joins what is left", () => {
    expect(stillToGo(3, 5)).toBe("3 more days and 5 more trades");
    expect(stillToGo(1, 0)).toBe("1 more day");
    expect(stillToGo(0, 1)).toBe("1 more trade");
    expect(stillToGo(0, 0)).toBe("");
  });
});

describe("capitalise and splitCurve", () => {
  it("capitalises the first letter", () => {
    expect(capitalise("less than a day")).toBe("Less than a day");
    expect(capitalise("")).toBe("");
  });
  it("splits points into times and values", () => {
    expect(splitCurve([[1, 10], [2, 11]])).toEqual({ times: [1, 2], values: [10, 11] });
  });
});

describe("setupProblems", () => {
  const ok: SetupCheck = { capital: 1000, manual: false, chosen: 0, lossPctOn: false, lossUsdOn: false, tpOn: false, trailOn: false, endOn: false, now: 1000 };
  it("is empty for a plain start", () => {
    expect(setupProblems(ok)).toEqual([]);
  });
  it("asks for an amount and a strategy", () => {
    expect(setupProblems({ ...ok, capital: NaN })).toContain("Enter how much it may use, more than zero.");
    expect(setupProblems({ ...ok, manual: true })).toContain("Pick at least one strategy and give it a share above zero.");
  });
  it("checks every limit that is switched on", () => {
    expect(setupProblems({ ...ok, lossPctOn: true, lossPct: 100 })).toHaveLength(1);
    expect(setupProblems({ ...ok, lossPctOn: true, lossPct: 10 })).toEqual([]);
    expect(setupProblems({ ...ok, lossUsdOn: true, lossUsd: 1000 })).toHaveLength(1);
    expect(setupProblems({ ...ok, lossUsdOn: true, lossUsd: 100 })).toEqual([]);
    expect(setupProblems({ ...ok, tpOn: true, tp: 0 })).toHaveLength(1);
    expect(setupProblems({ ...ok, trailOn: true, trail: NaN })).toHaveLength(1);
    expect(setupProblems({ ...ok, endOn: true, endMs: 500 })).toEqual(["The end date has to be in the future."]);
    expect(setupProblems({ ...ok, endOn: true, endMs: 5000 })).toEqual([]);
  });
  it("ignores limits that are off", () => {
    expect(setupProblems({ ...ok, lossPct: 500, tp: -1 })).toEqual([]);
  });
});
