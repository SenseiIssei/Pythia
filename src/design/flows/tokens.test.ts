import { describe, expect, it } from "vitest";
import { contrastRatio } from "../../practice";

// Read as plain text in Node: vitest stubs CSS imports, and the app's
// TypeScript setup has no Node types, hence the untyped dynamic import.
const fsName = "node:fs";
const fs = (await import(/* @vite-ignore */ fsName)) as { readFileSync: (p: URL, enc: string) => string };
const css = fs.readFileSync(new URL("./flows.css", import.meta.url), "utf8");

// Every text colour of the flows has to read at WCAG AA (4.5:1) on every
// surface it sits on, in light and in dark.

function block(selector: string): Record<string, string> {
  const at = css.indexOf(selector);
  const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("}", at));
  return Object.fromEntries([...body.matchAll(/--fl-([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]));
}

describe("flow tokens", () => {
  const themes: [string, Record<string, string>][] = [
    ["light", block(".fl {")],
    ["dark", block(':root[data-theme="dark"] .fl,')],
  ];
  for (const [name, t] of themes) {
    it(`reads at AA in ${name}`, () => {
      for (const fg of ["text", "muted", "up", "down", "warn"]) {
        for (const bg of ["surface", "surface-2", "bg"]) {
          expect(contrastRatio(t[fg], t[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
        }
      }
    });
  }
});
