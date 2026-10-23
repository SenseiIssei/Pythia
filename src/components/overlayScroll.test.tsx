import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
// @ts-expect-error The app carries no Node types; the tests run on Node.
import { readFileSync } from "node:fs";
import { LegalGate } from "./LegalGate";
import { Onboarding } from "./Onboarding";
import { lockScroll, type ScrollRoot } from "../design";

const css = readFileSync(new URL("../App.css", import.meta.url), "utf8");

/** The rule block for one selector in App.css. */
function rule(selector: string): string {
  const at = css.indexOf(`${selector} {`);
  expect(at, `${selector} in App.css`).toBeGreaterThanOrEqual(0);
  return css.slice(at, css.indexOf("}", at));
}

describe("full-screen overlays on a phone", () => {
  it("the first-run gate scrolls inside itself and keeps its checkboxes and button in that scroller", () => {
    const html = renderToStaticMarkup(<LegalGate onAccept={() => {}} />);
    expect(html).toMatch(/^<div class="pt-screen" data-scroll-container=""/);
    // The old window class clipped the gate: overflow hidden won over overflow-y-auto.
    expect(html).not.toContain("app-window");
    expect(html.match(/role="checkbox"/g)).toHaveLength(5);
    expect(html).toContain("Tick all 5 points");
  });

  it("the tour does the same", () => {
    const html = renderToStaticMarkup(<Onboarding onDone={() => {}} />);
    expect(html).toMatch(/^<div class="pt-screen" data-scroll-container=""/);
    expect(html).toContain("Continue");
  });

  it("the overlay class scrolls, is capped at the screen with a 100vh fallback and clears the safe areas", () => {
    const r = rule(".pt-screen");
    expect(r).toContain("overflow-y: auto");
    expect(r).toContain("overscroll-behavior: contain");
    expect(r.indexOf("max-height: 100vh")).toBeGreaterThan(-1);
    expect(r.indexOf("max-height: 100dvh")).toBeGreaterThan(r.indexOf("max-height: 100vh"));
    expect(r).toContain("safe-area-inset-bottom");
    expect(r).toContain("safe-area-inset-top");
  });

  it("sheets are capped at the screen and their footer clears the home indicator", () => {
    const s = rule(".pt-sheet");
    expect(s).toContain("max-height: 92vh");
    expect(s).toContain("max-height: 92dvh");
    expect(rule(".pt-sheet-body")).toContain("overscroll-behavior: contain");
    expect(rule(".pt-sheet-pad")).toContain("safe-area-inset-bottom");
  });
});

describe("lockScroll", () => {
  const root = (): ScrollRoot => ({ body: { style: { overflow: "auto" } }, documentElement: { style: { overflow: "" } } });

  it("locks the page while open and puts back what was there after", () => {
    const r = root();
    const release = lockScroll(r);
    expect([r.documentElement.style.overflow, r.body.style.overflow]).toEqual(["hidden", "hidden"]);
    release();
    expect([r.documentElement.style.overflow, r.body.style.overflow]).toEqual(["", "auto"]);
  });

  it("stays locked until the last of two nested overlays closes, and a double release does nothing", () => {
    const r = root();
    const a = lockScroll(r);
    const b = lockScroll(r);
    a();
    a();
    expect(r.body.style.overflow).toBe("hidden");
    b();
    expect(r.body.style.overflow).toBe("auto");
  });
});
