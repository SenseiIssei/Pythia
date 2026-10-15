import { describe, expect, it } from "vitest";
import { domainOf, pathOf, ticksOf, yOf } from "./chart";
import { contrastRatio } from "../practice";

describe("domainOf", () => {
  it("spans every series with a little padding", () => {
    const d = domainOf([[0, 10], [5, 20]], 0.1)!;
    expect(d.min).toBeCloseTo(-2);
    expect(d.max).toBeCloseTo(22);
  });
  it("skips gaps and gives a flat line some height", () => {
    const d = domainOf([[NaN, 100, 100]])!;
    expect(d.min).toBeLessThan(100);
    expect(d.max).toBeGreaterThan(100);
    expect(domainOf([[0, 0]])).toEqual({ min: -1, max: 1 });
  });
  it("is null with no numbers at all", () => {
    expect(domainOf([])).toBeNull();
    expect(domainOf([[NaN]])).toBeNull();
  });
});

describe("pathOf", () => {
  const d = { min: 0, max: 10 };
  it("draws left to right, bottom is the minimum", () => {
    expect(pathOf([0, 10], d, 100, 50)).toBe("M0.0,50.0L100.0,0.0");
  });
  it("lines a short series up on the left of a longer one", () => {
    expect(pathOf([0, 10], d, 100, 50, 3)).toBe("M0.0,50.0L50.0,0.0");
  });
  it("breaks the line at a gap", () => {
    expect(pathOf([0, NaN, 10], d, 100, 50)).toBe("M0.0,50.0M100.0,0.0");
  });
});

describe("ticksOf", () => {
  it("picks round values inside the range", () => {
    const t = ticksOf({ min: 0, max: 100 }, 3);
    expect(t).toEqual([0, 25, 50, 75]);
    for (const v of ticksOf({ min: 9_812, max: 10_377 })) {
      expect(v).toBeGreaterThanOrEqual(9_812);
      expect(v).toBeLessThan(10_377);
    }
  });
  it("copes with a zero-width range", () => {
    expect(ticksOf({ min: 5, max: 5 })).toEqual([5]);
  });
  it("places a value on the y axis", () => {
    expect(yOf(5, { min: 0, max: 10 }, 100)).toBe(50);
  });
});

// The chart colours and the accent have to stand out on every surface, in
// light and in dark: 4.5:1 for the accent (it is used for text and links),
// 3:1 for the other series lines (graphics).
const fsName = "node:fs";
const fs = (await import(/* @vite-ignore */ fsName)) as { readFileSync: (p: URL, enc: string) => string };
const kit = fs.readFileSync(new URL("./pagekit.css", import.meta.url), "utf8");
const flows = fs.readFileSync(new URL("../design/flows/flows.css", import.meta.url), "utf8");

function block(css: string, selector: string, prefix: string): Record<string, string> {
  const at = css.indexOf(selector);
  const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("}", at));
  return Object.fromEntries([...body.matchAll(new RegExp(`--${prefix}-([\\w-]+):\\s*(#[0-9a-f]{6})`, "gi"))].map((m) => [m[1], m[2]]));
}

describe("page kit colours", () => {
  const themes: [string, Record<string, string>, Record<string, string>][] = [
    ["light", block(kit, ".fl {", "pk"), block(flows, ".fl {", "fl")],
    ["dark", block(kit, ':root[data-theme="dark"] .fl,', "pk"), block(flows, ':root[data-theme="dark"] .fl,', "fl")],
  ];
  for (const [name, pk, fl] of themes) {
    it(`reads in ${name}`, () => {
      for (const bg of ["surface", "surface-2", "bg"]) {
        expect(contrastRatio(pk.accent, fl[bg]), `accent on ${bg}`).toBeGreaterThanOrEqual(4.5);
        for (const s of ["s2", "s3", "s4", "s5"]) expect(contrastRatio(pk[s], fl[bg]), `${s} on ${bg}`).toBeGreaterThanOrEqual(3);
      }
    });
  }
  it("keeps the media-query dark block in step with the explicit one", () => {
    expect(block(kit, ':root:not([data-theme="light"]) .fl {', "pk")).toEqual(block(kit, ':root[data-theme="dark"] .fl,', "pk"));
  });
});
