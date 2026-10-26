import { describe, expect, it } from "vitest";
import { armRows, euro, factoryViews, zooPicks } from "./labFactory";
import { FACTORY } from "./labFactory.fixture";

describe("factoryViews", () => {
  it("shows F3 with its best candidate, its held-back result and its books in EUR, and F2 without a report", () => {
    const [f3, f2] = factoryViews(FACTORY);
    expect(f3.code).toBe("F3");
    expect(f3.best?.id).toBe("F3_00042");
    expect(f3.held?.pnl_sol).toBe(-0.031);
    expect(f3.books.map((b) => b.eurNow)).toEqual([97.6, 80]);
    expect(f2.code).toBe("F2");
    expect(f2.report).toBeNull();
    expect(f2.books).toEqual([]);
    expect(factoryViews(null).map((f) => f.report)).toEqual([null, null]);
  });

  it("has no held-back result when the best candidate was not held back", () => {
    const d = { ...FACTORY, factories: { F3: { ...FACTORY.factories!.F3!, holdback: [] } } };
    expect(factoryViews(d)[0].held).toBeNull();
  });
});

describe("armRows and zooPicks", () => {
  it("puts the most likely best strategy first and marks the pick and the live one", () => {
    const rows = armRows(FACTORY.allocator);
    expect(rows.map((r) => r.name)).toEqual(["P_pool5_top30t", "P_pool0_wait", "P_pool0_wait_lock"]);
    expect(rows[0].chosen && !rows[0].live).toBe(true);
    expect(rows[1].live && rows[1].guarded).toBe(true);
    expect(armRows(null)).toEqual([]);
  });

  it("lists the zoo's pick per label with its last change", () => {
    expect(zooPicks(FACTORY)).toEqual([
      { label: "win30", pick: "lgb", days: 4, changed: null },
      { label: "rug0t", pick: "hgb", days: 3, changed: "lgb → hgb on 2026-10-25" },
    ]);
    expect(zooPicks(null)).toEqual([]);
  });

  it("writes euro in the app's English", () => {
    expect(euro(97.6)).toBe("€97.60");
    expect(euro(null)).toBe("n/a");
  });
});
