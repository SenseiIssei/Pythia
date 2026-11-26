import { describe, expect, it } from "vitest";

// Numbers are written the same way on every machine. Without a locale a German
// Windows shows "1.234" where the next line shows "$1,234", and in a trading
// app nobody should have to guess which one is the decimal point.
const files = import.meta.glob<string>(["./**/*.ts", "./**/*.tsx", "!./**/*.test.*"], { query: "?raw", import: "default", eager: true });

/** Calls that format with the machine's locale, except dates. */
function machineLocale(src: string): string[] {
  return src
    .split("\n")
    .filter((l) => /\.toLocaleString\(\s*(\)|undefined|\[\])/.test(l))
    .filter((l) => !/new Date\([^)]*\)\.toLocaleString\(/.test(l))
    .map((l) => l.trim());
}

describe("number formatting", () => {
  it("never depends on the machine's locale", () => {
    expect(Object.keys(files).length).toBeGreaterThan(50);
    const hits = Object.entries(files).flatMap(([f, src]) => machineLocale(src).map((l) => `${f}: ${l}`));
    expect(hits).toEqual([]);
  });

  it("catches a number without a locale and leaves dates alone", () => {
    expect(machineLocale("x.toLocaleString()")).toHaveLength(1);
    expect(machineLocale("x.toLocaleString(undefined, { style: 'currency' })")).toHaveLength(1);
    expect(machineLocale("new Date(ms).toLocaleString([], {})")).toHaveLength(0);
    expect(machineLocale('x.toLocaleString("en-US")')).toHaveLength(0);
  });
});
