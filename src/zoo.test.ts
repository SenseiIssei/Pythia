import { describe, expect, it } from "vitest";
import { ago, driftTone, edgeSeries, fmtScore, statusTone, winShare } from "./zoo";

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
  it("colours status and drift", () => {
    expect(statusTone("in use")).toBe("green");
    expect(statusTone("failed its gate")).toBe("amber");
    expect(statusTone("something new")).toBe("neutral");
    expect(driftTone("drift")).toBe("red");
    expect(driftTone(undefined)).toBe("neutral");
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
