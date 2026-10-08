import { describe, expect, it } from "vitest";
import { NAV, isVisible, navFor } from "./nav";

describe("navFor", () => {
  it("keeps simple mode to the six beginner destinations", () => {
    expect(navFor("simple").map((n) => n.id)).toEqual(["home", "autopilot", "predictions", "wallets", "settings", "about"]);
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
    for (const id of ["home", "autopilot", "predictions", "wallets", "settings", "about"] as const) {
      expect(isVisible(id, "simple")).toBe(true);
      expect(isVisible(id, "advanced")).toBe(true);
    }
  });
});
