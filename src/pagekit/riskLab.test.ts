import { describe, expect, it } from "vitest";
import {
  LIMITS,
  LIMIT_GROUPS,
  credibleCount,
  degradationText,
  finalValue,
  fixed,
  gauge,
  limitText,
  monthlyVol,
  paramLine,
  ratioWord,
  riskGauges,
  sizingWord,
  spikeTrimState,
} from "./riskLab";

describe("LIMITS", () => {
  it("keeps all seventeen sliders, each in a known group, with no duplicates", () => {
    expect(LIMITS).toHaveLength(17);
    expect(new Set(LIMITS.map((l) => l.key)).size).toBe(17);
    const groups = new Set(LIMIT_GROUPS.map((g) => g.id));
    for (const l of LIMITS) {
      expect(groups.has(l.group)).toBe(true);
      expect(l.min).toBeLessThan(l.max);
      expect(l.meaning).not.toContain(String.fromCharCode(0x2014));
    }
  });
});

describe("limitText", () => {
  it("reads each unit plainly", () => {
    expect(limitText({ unit: "pct" }, 2.5)).toBe("2.5%");
    expect(limitText({ unit: "pctEquity" }, 25)).toBe("25% of equity");
    expect(limitText({ unit: "pctYear" }, 40)).toBe("40% a year");
    expect(limitText({ unit: "pctBar" }, 1.2)).toBe("1.2% per candle");
    expect(limitText({ unit: "times" }, 0.25)).toBe("0.25×");
    expect(limitText({ unit: "timesTarget" }, 2)).toBe("2× target");
    expect(limitText({ unit: "atr" }, 1.5)).toBe("1.5× ATR");
    expect(limitText({ unit: "losses" }, 1)).toBe("1 loss");
    expect(limitText({ unit: "losses" }, 4)).toBe("4 losses");
    expect(limitText({ unit: "perMin" }, 10)).toBe("10 a minute");
  });
  it("turns seconds into minutes past one minute", () => {
    expect(limitText({ unit: "seconds" }, 30)).toBe("30 s");
    expect(limitText({ unit: "seconds" }, 60)).toBe("1 min");
    expect(limitText({ unit: "seconds" }, 90)).toBe("1 min 30 s");
  });
  it("says Off at zero only where zero switches the limit off", () => {
    expect(limitText({ unit: "atr", zeroOff: true }, 0)).toBe("Off");
    expect(limitText({ unit: "pct" }, 0)).toBe("0%");
  });
  it("cleans float noise from steps", () => {
    expect(limitText({ unit: "pctBar" }, 0.30000000000000004)).toBe("0.3% per candle");
  });
});

describe("riskGauges", () => {
  const limits = { maxDailyLossPct: 5, maxGrossExposurePct: 50 };
  it("measures today's loss against the daily limit", () => {
    const g = riskGauges({ realizedPnl: -200, unrealizedPnl: -200, dayStartEquity: 10_000, equity: 9_600, grossExposure: 4_800 }, limits);
    expect(g.loss.value).toBeCloseTo(4);
    expect(g.loss.pct).toBeCloseTo(80);
    expect(g.loss.level).toBe("near");
    expect(g.gross.value).toBeCloseTo(50);
    expect(g.gross.level).toBe("over");
  });
  it("counts a day in profit as no loss and an empty account as nothing in the market", () => {
    const g = riskGauges({ realizedPnl: 100, unrealizedPnl: 0, dayStartEquity: 0, equity: 0, grossExposure: 10 }, limits);
    expect(g.loss.value).toBe(0);
    expect(g.loss.level).toBe("ok");
    expect(g.gross.value).toBe(0);
  });
  it("gauge reads a cap of zero as off", () => {
    expect(gauge(30, 0).level).toBe("off");
    expect(gauge(30, 60).pct).toBeCloseTo(50);
  });
});

describe("monthlyVol", () => {
  it("divides a year's swing by the square root of twelve", () => {
    expect(monthlyVol(12 * Math.sqrt(12) / 12)).toBeCloseTo(1);
    expect(monthlyVol(0)).toBe(0);
  });
});

describe("spikeTrimState", () => {
  it("is off without a target or a multiple", () => {
    expect(spikeTrimState(0, 2, undefined).word).toBe("Trim off");
    expect(spikeTrimState(20, 0, undefined).tone).toBe("neutral");
  });
  it("counts the minutes of a running spike", () => {
    const s = spikeTrimState(20, 2, 0, 12 * 60_000 + 5);
    expect(s.word).toBe("Spike");
    expect(s.tone).toBe("bad");
    expect(s.text).toContain("Over 40% for 12 of 30 minutes");
  });
  it("describes the armed trim", () => {
    const s = spikeTrimState(20, 1.5, undefined);
    expect(s.word).toBe("Trim on");
    expect(s.text).toContain("above 30% (1.5× the target)");
  });
});

describe("sizing and optimizer words", () => {
  it("names each sizing mode", () => {
    expect(sizingWord("confidence").text).toBe("Signal strength");
    expect(sizingWord("measured").tone).toBe("accent");
    expect(sizingWord("noEdge").tone).toBe("bad");
  });
  it("fixed shows n/a for missing numbers", () => {
    expect(fixed(undefined)).toBe("n/a");
    expect(fixed(0.12345, 3)).toBe("0.123");
  });
  it("paramLine joins objects and tuples the same way", () => {
    expect(paramLine({ fast: 10, slow: 50 })).toBe("fast 10 · slow 50");
    expect(paramLine([["fast", 10]])).toBe("fast 10");
    expect(paramLine({})).toBe("default settings");
  });
  it("credibleCount needs both bars", () => {
    expect(
      credibleCount([
        { pValue: 0.01, oosIsRatio: 0.7 },
        { pValue: 0.01, oosIsRatio: 0.3 },
        { pValue: 0.2, oosIsRatio: 0.9 },
        { pValue: 0.01 },
      ]),
    ).toBe(1);
  });
  it("ratioWord says whether the edge held up", () => {
    expect(ratioWord(undefined)).toEqual({ text: "n/a", good: null });
    expect(ratioWord(0.75)).toEqual({ text: "0.75 held up", good: true });
    expect(ratioWord(0.2).good).toBe(false);
  });
  it("degradationText signs the change from the first batch to the new one", () => {
    expect(degradationText(3)).toBe("−3.0 percentage points");
    expect(degradationText(-1.25)).toBe("+1.3 percentage points");
    expect(degradationText(0)).toBe("0.0 percentage points");
  });
  it("finalValue is the last point", () => {
    expect(finalValue([1, 2, 3])).toBe(3);
    expect(finalValue([])).toBeNull();
  });
});
