import { describe, expect, it } from "vitest";
import { pumpfunStudies, sharePct, strategyRows } from "./pumpfunLab";
import { LAB } from "./pumpfunLab.fixture";
import type { StudyView } from "./researchView";

describe("strategyRows", () => {
  it("lists every strategy with readiness and book, the newest book first, a book without readiness too", () => {
    const rows = strategyRows(LAB);
    expect(rows.map((r) => r.rule)).toEqual(["P_press10", "P_pool0", "P_new", "P_snipe_dev"]);
    const pool = rows.find((r) => r.rule === "P_pool0")!;
    expect(pool.checks.map((c) => `${c.label}:${c.ok}`)).toEqual(["days:false", "trades:false", "positive:true", "gates:false", "shadow:false"]);
    expect(pool.shadow?.n).toBe(17);
    expect(pool.book?.entries).toBe(1);
    expect(rows.find((r) => r.rule === "P_new")!.checks).toEqual([]);
    expect(strategyRows(null)).toEqual([]);
  });

  it("puts a ready strategy first", () => {
    const lab = { ...LAB, readiness: { ...LAB.readiness, P_snipe_dev: { ready: true } } };
    expect(strategyRows(lab)[0].rule).toBe("P_snipe_dev");
  });
});

describe("pumpfunStudies", () => {
  const s = (file: string | null, code: string): StudyView => ({ id: file ?? code, title: file ?? code, code, verdict: "No.", kind: "ruled_out", date: null, file, group: "study" });
  it("keeps the pump.fun write-ups in the order given, at most the limit", () => {
    const list = [s("pumpfun_exits_y8", "pumpfun_exits_y8"), s("tsmom", "tsmom"), s(null, "`pumpfun_rt` speed (Y3)"), s("pumpfun_speed", "x")];
    expect(pumpfunStudies(list).map((x) => x.id)).toEqual(["pumpfun_exits_y8", "`pumpfun_rt` speed (Y3)", "pumpfun_speed"]);
    expect(pumpfunStudies(list, 1)).toHaveLength(1);
  });
});

describe("sharePct", () => {
  it("signs a share as percent", () => {
    expect(sharePct(0.041)).toBe("+4.1 %");
    expect(sharePct(-0.2)).toBe("-20.0 %");
    expect(sharePct(null)).toBe("n/a");
  });
});
