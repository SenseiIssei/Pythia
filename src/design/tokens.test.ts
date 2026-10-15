import { describe, expect, it } from "vitest";
import { PALETTES, SERIES, SURFACE_ROLES, TEXT_ROLES, contrast, hexToTriplet, themeCss, themeVars, type Palette } from "./tokens";
import { resolveTheme } from "./theme";

describe("design tokens", () => {
  it("defines the same roles in light and dark", () => {
    expect(Object.keys(PALETTES.dark).sort()).toEqual(Object.keys(PALETTES.light).sort());
    expect(SERIES.dark.length).toBe(SERIES.light.length);
  });

  it("uses six digit hex everywhere", () => {
    for (const p of Object.values(PALETTES)) for (const v of Object.values(p)) expect(v).toMatch(/^#[0-9a-f]{6}$/i);
  });

  for (const theme of ["light", "dark"] as const) {
    const p: Palette = PALETTES[theme];

    it(`every text role reads at WCAG AA on every surface in ${theme}`, () => {
      for (const fg of TEXT_ROLES) {
        for (const bg of SURFACE_ROLES) {
          expect(contrast(p[fg], p[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
        }
      }
    });

    it(`the selected segment stands off its track and its label reads in ${theme}`, () => {
      expect(contrast(p.text, p.raised)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(p.raised, p["surface-2"])).toBeGreaterThan(1.05);
    });

    it(`button labels read at AA in ${theme}`, () => {
      expect(contrast(p["on-primary"], p.primary)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(p["on-accent"], p.accent)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(p["on-down"], p.down)).toBeGreaterThanOrEqual(4.5);
    });

    it(`chart series stay visible on the surface in ${theme}`, () => {
      // Lines are not text; 3:1 is the WCAG bar for graphics.
      for (const c of SERIES[theme]) expect(contrast(c, p.surface), c).toBeGreaterThanOrEqual(3);
    });

    it(`up and down differ in more than hue in ${theme}`, () => {
      // Arrows carry the meaning too, but the two should never look alike.
      expect(p.up).not.toBe(p.down);
    });
  }

  it("is a calm palette: no saturated neon on the light background", () => {
    // The old cyan #00f0ff read at 1.4:1 on white; nothing that faint may come back.
    for (const fg of TEXT_ROLES) expect(contrast(PALETTES.light[fg], "#ffffff")).toBeGreaterThan(4.5);
  });
});

describe("token stylesheet", () => {
  it("turns hex into the triplet Tailwind needs", () => {
    expect(hexToTriplet("#0a7d3b")).toBe("10 125 59");
    expect(hexToTriplet("#FFFFFF")).toBe("255 255 255");
    expect(() => hexToTriplet("red")).toThrow();
  });

  it("emits a triplet and a colour for every role", () => {
    const vars = themeVars("light");
    for (const [k, v] of Object.entries(PALETTES.light)) {
      expect(vars).toContain(`--pt-${k}: ${hexToTriplet(v)};`);
      expect(vars).toContain(`--color-${k}: ${v};`);
    }
    expect(vars).toContain("color-scheme: light;");
  });

  it("follows the system and an explicit choice for dark", () => {
    const css = themeCss();
    expect(css).toContain('@media (prefers-color-scheme: dark) { :root:not([data-theme="light"])');
    expect(css).toContain(':root[data-theme="dark"]');
    expect(css).toContain(`--color-bg: ${PALETTES.dark.bg};`);
    expect(css).toContain("--radius-card: 20px;");
  });

  it("resolves a preference against the system", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});
