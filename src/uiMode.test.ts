import { describe, expect, it } from "vitest";
import { getUiMode, setUiMode } from "./uiMode";

describe("uiMode", () => {
  it("defaults to simple when there is no storage at all", () => {
    // The test runs in Node, where localStorage does not exist: the same
    // situation as a private window that refuses storage.
    expect(getUiMode()).toBe("simple");
  });

  it("switches modes even when it cannot persist the choice", () => {
    setUiMode("advanced");
    expect(getUiMode()).toBe("advanced");
    setUiMode("simple");
    expect(getUiMode()).toBe("simple");
  });
});
