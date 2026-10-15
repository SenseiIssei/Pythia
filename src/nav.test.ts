import { describe, expect, it } from "vitest";
import { NAV, isVisible, navFor, resolvePage } from "./nav";

describe("navFor", () => {
  it("keeps simple mode to the beginner destinations", () => {
    expect(navFor("simple").map((n) => n.id)).toEqual(["home", "autopilot", "activity", "notifications", "predictions", "wallets", "settings", "about"]);
  });

  it("shows everything in advanced mode", () => {
    expect(navFor("advanced")).toEqual(NAV);
  });

  it("never hides the stop-the-money pages from beginners", () => {
    // Home carries the mode banner and the stop button; Settings carries the
    // switch back. Simple mode must always reach both.
    for (const id of ["home", "settings"] as const) {
      expect(navFor("simple").some((n) => n.id === id)).toBe(true);
    }
  });

  it("puts Autopilot first after Home, Practice merged into it", () => {
    expect(navFor("simple").slice(0, 2).map((n) => n.id)).toEqual(["home", "autopilot"]);
    expect(NAV.some((n) => n.id === "practice")).toBe(false);
  });

  it("marks every simple-mode page as not advanced", () => {
    expect(navFor("simple").every((n) => !n.advanced)).toBe(true);
  });
});

describe("isVisible", () => {
  it("hides advanced pages in simple mode and shows them in advanced", () => {
    expect(isVisible("strategies", "simple")).toBe(false);
    expect(isVisible("strategies", "advanced")).toBe(true);
    expect(isVisible("optimizer", "simple")).toBe(false);
  });

  it("shows the always-visible pages in both modes", () => {
    for (const id of ["home", "practice", "autopilot", "activity", "notifications", "predictions", "wallets", "settings", "about"] as const) {
      expect(isVisible(id, "simple")).toBe(true);
      expect(isVisible(id, "advanced")).toBe(true);
    }
  });
});

describe("resolvePage", () => {
  it("sends the old Practice page to Autopilot", () => {
    expect(resolvePage("practice")).toBe("autopilot");
    expect(resolvePage("home")).toBe("home");
  });
});
