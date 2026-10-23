import { describe, expect, it } from "vitest";
import { LAB_POLL_MS, isShown, shouldRefresh, updatedText } from "./pageVisible";

describe("shouldRefresh", () => {
  it("reads at once when a shown page never read, then every 30 s, never while hidden", () => {
    expect(LAB_POLL_MS).toBe(30_000);
    expect(shouldRefresh(1_000, 0, true)).toBe(true);
    expect(shouldRefresh(1_000, 0, false)).toBe(false);
    expect(shouldRefresh(40_000, 20_000, true)).toBe(false);
    expect(shouldRefresh(50_000, 20_000, true)).toBe(true);
    expect(shouldRefresh(500_000, 20_000, false)).toBe(false);
  });
});

describe("updatedText", () => {
  it("says hh:mm in the reader's clock", () => {
    const d = new Date(2026, 9, 23, 9, 5);
    expect(updatedText(d.getTime())).toBe("updated 09:05");
    expect(updatedText(null)).toBe("");
  });
});

describe("isShown", () => {
  it("is false for a missing element and for one inside a hidden page", () => {
    expect(isShown(null)).toBe(false);
    expect(isShown({ offsetParent: null } as unknown as HTMLElement)).toBe(false);
  });
});
