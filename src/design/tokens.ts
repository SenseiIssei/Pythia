// Pythia's design tokens: the one place colours, type, spacing and radii live.
//
// Calm and mostly white, with a true black dark mode. One accent colour for
// links, focus and the selected state; green and red only ever mean up and
// down. Everything else is ink on paper.
//
// Components never hard-code a colour. They use the Tailwind names
// (bg-surface, text-ink, text-muted, text-up, ...) or the CSS variables
// (var(--color-up)), both generated from the tables below. `themeCss()` turns
// the tables into the stylesheet main.tsx installs before the first render.

export type ThemeName = "light" | "dark";

/** Every colour role. Text roles must read at WCAG AA on every surface role. */
export interface Palette {
  /** The page behind everything. */
  bg: string;
  /** Cards, sheets, the tab bar. */
  surface: string;
  /** Inputs, chips, segmented controls, skeletons, row hover. */
  "surface-2": string;
  /** The selected pill inside a segmented control: lifted off surface-2. */
  raised: string;
  /** Hairlines between rows and around cards. */
  line: string;
  /** A slightly stronger line, for inputs on hover and dividers that must show. */
  "line-strong": string;
  /** Body text and big numbers. */
  text: string;
  /** Labels and second lines. */
  muted: string;
  /** The quietest text that still reads (timestamps, hints). */
  faint: string;
  /** The one accent: links, focus rings, selected chips, the active tab. */
  accent: string;
  /** Text on a filled accent. */
  "on-accent": string;
  /** Gains. */
  up: string;
  /** Losses and danger. */
  down: string;
  /** Caution. */
  warn: string;
  /** The filled main button: ink on paper. */
  primary: string;
  "on-primary": string;
  /** Text on a filled red button. */
  "on-down": string;
}

export const PALETTES: Record<ThemeName, Palette> = {
  light: {
    bg: "#ffffff",
    surface: "#ffffff",
    "surface-2": "#f3f3f5",
    raised: "#ffffff",
    line: "#e8e8ec",
    "line-strong": "#d4d4da",
    text: "#0b0b0f",
    muted: "#5b5b66",
    faint: "#6b6b76",
    accent: "#2e55d6",
    "on-accent": "#ffffff",
    up: "#0a7d3b",
    down: "#c8102e",
    warn: "#8a5a00",
    primary: "#0b0b0f",
    "on-primary": "#ffffff",
    "on-down": "#ffffff",
  },
  dark: {
    bg: "#000000",
    surface: "#111113",
    "surface-2": "#1c1c1f",
    raised: "#2e2e33",
    line: "#232327",
    "line-strong": "#34343a",
    text: "#f5f5f7",
    muted: "#a6a6b0",
    faint: "#8e8e99",
    accent: "#8aa4ff",
    "on-accent": "#000000",
    up: "#3ddc84",
    down: "#ff6b6b",
    warn: "#f5b942",
    primary: "#f5f5f7",
    "on-primary": "#000000",
    "on-down": "#000000",
  },
};

/**
 * Series colours for charts that compare several lines. Calm, distinct in
 * both themes, and none of them reads as "up" or "down".
 */
export const SERIES: Record<ThemeName, string[]> = {
  light: ["#2e55d6", "#0b0b0f", "#8a5a00", "#7a3fb8", "#0f7a8a", "#b0457a"],
  dark: ["#8aa4ff", "#f5f5f7", "#f5b942", "#c39bff", "#5fd4e0", "#ff9ccf"],
};

/** Text roles, and the surfaces each has to read on. */
export const TEXT_ROLES = ["text", "muted", "faint", "accent", "up", "down", "warn"] as const;
export const SURFACE_ROLES = ["bg", "surface", "surface-2"] as const;

/** Type scale in px: [size, line height, weight]. */
export const TYPE = {
  /** The portfolio total. */
  display: [40, 44, 700],
  /** Page titles. */
  title: [28, 34, 700],
  /** Section titles and sheet titles. */
  headline: [20, 26, 600],
  /** Row titles, buttons. */
  body: [15, 22, 500],
  /** Second lines, labels. */
  caption: [13, 18, 400],
  /** Tab labels, badges. */
  small: [11, 14, 600],
} as const;

/** Spacing steps in px. Generous: a card pads 20, rows breathe 14 top and bottom. */
export const SPACE = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 28, section: 40 } as const;

export const RADIUS = { control: 12, card: 20, sheet: 28, pill: 999 } as const;

/** The font stack: Inter when the system has it, the platform UI font otherwise. */
export const FONT_SANS = '"Inter", "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, "SF Pro Text", Roboto, "Helvetica Neue", sans-serif';
export const FONT_CODE = 'ui-monospace, "SF Mono", "Cascadia Mono", Consolas, "Liberation Mono", monospace';

/** "#0a7d3b" to "10 125 59", the form Tailwind's alpha modifiers need. */
export function hexToTriplet(hex: string): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`not a six digit hex colour: ${hex}`);
  const n = parseInt(m[1], 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

/** WCAG contrast ratio of two six digit hex colours. */
export function contrast(a: string, b: string): number {
  const lum = (hex: string) => {
    const n = parseInt(hex.slice(1), 16);
    const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/** The variable block for one theme: `--pt-x` triplets for Tailwind, `--color-x` for CSS and SVG. */
export function themeVars(theme: ThemeName): string {
  const p = PALETTES[theme];
  const lines = (Object.keys(p) as (keyof Palette)[]).flatMap((k) => [`--pt-${k}: ${hexToTriplet(p[k])};`, `--color-${k}: ${p[k]};`]);
  SERIES[theme].forEach((c, i) => lines.push(`--color-series-${i + 1}: ${c};`));
  // Lightness of ticker badge letters, so they read on either background.
  lines.push(`--ticker-l: ${theme === "dark" ? "74%" : "32%"};`);
  lines.push(`color-scheme: ${theme};`);
  return lines.join(" ");
}

/**
 * The theme stylesheet. Light by default; dark follows the system unless the
 * person picked a theme, which sets data-theme on <html>.
 */
export function themeCss(): string {
  const fixed = [
    `--font-sans: ${FONT_SANS};`,
    `--font-code: ${FONT_CODE};`,
    ...Object.entries(RADIUS).map(([k, v]) => `--radius-${k}: ${v}px;`),
    ...Object.entries(SPACE).map(([k, v]) => `--space-${k}: ${v}px;`),
  ].join(" ");
  return [
    `:root { ${fixed} ${themeVars("light")} }`,
    `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ${themeVars("dark")} } }`,
    `:root[data-theme="dark"] { ${themeVars("dark")} }`,
  ].join("\n");
}
