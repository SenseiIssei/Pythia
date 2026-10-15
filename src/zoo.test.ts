import { describe, expect, it } from "vitest";
import { ago, driftChip, edgeNow, edgePoints, edgeSeries, fmtP, fmtScore, needsAttention, statusTone, statusWord, winShare, type ZooModel } from "./zoo";

describe("edgeSeries", () => {
  it("is positive when a loss is lower than the baseline's", () => {
    const e = edgeSeries(
      [
        { model: 0.9, baseline: 1.0 },
        { model: 1.1, baseline: 1.0 },
      ],
      false,
    );
    expect(e[0]).toBeCloseTo(10);
    expect(e[1]).toBeCloseTo(-10);
  });

  it("is the difference in points when higher is better (rank-IC)", () => {
    expect(edgeSeries([{ model: 0.05, baseline: 0 }], true)[0]).toBeCloseTo(5);
  });

  it("skips points without both numbers or with a zero baseline loss", () => {
    expect(
      edgeSeries(
        [
          { model: null, baseline: 1 },
          { model: 1, baseline: 0 },
          { model: Number.NaN, baseline: 1 },
        ],
        false,
      ),
    ).toEqual([]);
  });
});

describe("winShare", () => {
  it("counts the periods the model beat its baseline", () => {
    const pts = [
      { model: 1, baseline: 2 },
      { model: 3, baseline: 2 },
      { model: 1, baseline: 2 },
      { model: 1, baseline: 2 },
    ];
    expect(winShare(pts, false)).toBe(0.75);
    expect(winShare([], false)).toBeNull();
  });
});

describe("words and tones", () => {
  it("colours status and drift with the design system's tones", () => {
    expect(statusTone("in use")).toBe("good");
    expect(statusTone("failed its gate")).toBe("warn");
    expect(statusTone("something new")).toBe("neutral");
    expect(driftChip("drift")).toEqual({ word: "outside trained range", tone: "bad" });
    expect(driftChip("stable").tone).toBe("good");
    expect(driftChip(undefined).word).toBe("not checked");
    expect(statusWord("failed its gate")).toBe("does not beat baseline");
  });

  it("reads p-values and the edge now", () => {
    expect(fmtP(0.0117)).toBe("0.012");
    expect(fmtP(1e-12)).toBe("< 0.001");
    expect(fmtP(null)).toBe("n/a");
    const base = { higherBetter: false, gainPct: 1.2, modelScore: 0.1, baselineScore: 0.2 } as unknown as ZooModel;
    expect(edgeNow(base)).toBe(1.2);
    expect(edgeNow({ ...base, higherBetter: true, modelScore: 0.05, baselineScore: 0 })).toBeCloseTo(5);
    expect(edgeNow({ ...base, gainPct: null })).toBeNull();
  });

  it("flags drift, a failed retrain and a broken shadow score", () => {
    const m = { status: "shadow", drift: { level: "stable" }, live: null, lastStatus: "ok" } as unknown as ZooModel;
    expect(needsAttention(m)).toBe(false);
    expect(needsAttention({ ...m, drift: { level: "drift", why: "", features: [] } })).toBe(true);
    expect(needsAttention({ ...m, lastStatus: "failed" })).toBe(true);
  });

  it("keeps each point's label for the chart", () => {
    const pts = edgePoints(
      [
        { label: "2025Q1", from: "2025-01-01", model: 0.9, baseline: 1 },
        { label: null, from: "2025-04-01", model: 1, baseline: 1 },
        { label: "2025Q3", model: null, baseline: 1 },
      ],
      false,
    );
    expect(pts.map((p) => p.label)).toEqual(["2025Q1", "2025-04-01"]);
    expect(pts[0].edge).toBeCloseTo(10);
  });

  it("formats scores per metric", () => {
    expect(fmtScore(0.69312, "logloss")).toBe("0.6931");
    expect(fmtScore(2.246, "mae")).toBe("2.25 bps");
    expect(fmtScore(null, "qlike")).toBe("n/a");
  });

  it("says how long ago", () => {
    const now = Date.UTC(2026, 9, 18);
    expect(ago(null, now)).toBe("never");
    expect(ago(now - 3600_000, now)).toBe("today");
    expect(ago(now - 86_400_000, now)).toBe("yesterday");
    expect(ago(now - 9 * 86_400_000, now)).toBe("9 days ago");
  });
});
