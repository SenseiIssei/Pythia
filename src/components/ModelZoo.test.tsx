import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ModelZoo } from "./ModelZoo";
import type { ZooModel, ZooStatus } from "../zoo";

const model = (over: Partial<ZooModel>): ZooModel => ({
  code: "M8q",
  name: "m8_quantiles",
  title: "Next-day return range",
  target: "the 10, 50 and 90 % quantiles",
  horizon: "next UTC day",
  universe: "the 15 Alpaca coins",
  metric: "pinball",
  higherBetter: false,
  baseline: "the usual spread",
  managedBy: "zoo",
  shadowWhere: "lab",
  status: "shadow",
  statusDetail: "champion v1",
  everyDays: 7,
  usedBy: [],
  useRule: "Informational.",
  notes: "",
  results: "model_zoo.md",
  lastRetrainMs: Date.now(),
  lastStatus: "ok",
  nextDue: "2026-10-25",
  champion: { version: "v1", promotedMs: 1, trainTo: "2026-10-13" },
  gate: { passed: true, why: "lower, DM p 0.012" },
  modelScore: 0.01167,
  baselineScore: 0.01179,
  gainPct: 0.97,
  dmP: 0.0117,
  foldsWon: 15,
  foldsTotal: 24,
  history: [
    { label: "2025Q1", from: "2025-01-01", model: 0.9, baseline: 1 },
    { label: "2025Q2", from: "2025-04-01", model: 1.1, baseline: 1 },
  ],
  decisions: [],
  live: null,
  drift: { level: "stable", why: "all inside", features: [] },
  extra: {},
  ...over,
});

describe("ModelZoo", () => {
  it("lists every model with its edge, status in words and the headline", () => {
    const z: ZooStatus = {
      generatedMs: 1,
      generated: "2026-10-15 07:15 UTC",
      headline: "1 of 5 zoo models beat their baseline out of sample (M8q).",
      alerts: [],
      models: [
        model({}),
        model({ code: "M12", title: "Correlation regime", status: "failed its gate", gainPct: -13.9, gate: { passed: false, why: "not lower" } }),
        model({ code: "M2", title: "Weekly ranking", higherBetter: true, modelScore: 0.05, baselineScore: 0, managedBy: "learn" }),
      ],
    };
    const html = renderToStaticMarkup(<ModelZoo z={z} />);
    expect(html).toContain("1 of 5 zoo models beat their baseline");
    expect(html).toContain("+1.0%");
    expect(html).toContain("13.9%");
    expect(html).toContain("does not beat baseline");
    expect(html).toContain("IC 0.050");
    expect(html).not.toContain("need a look");
  });

  it("asks for a look when a model drifts", () => {
    const z: ZooStatus = {
      generatedMs: 1,
      generated: "now",
      alerts: [],
      models: [model({ drift: { level: "drift", why: "1 of 23 inputs", features: [] } })],
    };
    const html = renderToStaticMarkup(<ModelZoo z={z} />);
    expect(html).toContain("M8q need a look");
    expect(html).toContain("outside trained range");
  });
});
