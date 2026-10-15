/** @type {import('tailwindcss').Config} */

// Every colour is a CSS variable from src/design/tokens.ts, so light and dark
// swap without a single `dark:` class. The old cyber/neon names stay as
// aliases of the new roles: a page still written against them shows the calm
// look without being touched.
const v = (name) => `rgb(var(--pt-${name}) / <alpha-value>)`;

export default {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: v("bg"),
        surface: v("surface"),
        "surface-2": v("surface-2"),
        line: v("line"),
        "line-strong": v("line-strong"),
        ink: v("text"),
        muted: v("muted"),
        faint: v("faint"),
        accent: { DEFAULT: v("accent"), hover: v("accent"), dim: v("accent") },
        "on-accent": v("on-accent"),
        up: v("up"),
        down: v("down"),
        warn: v("warn"),
        primary: v("primary"),
        "on-primary": v("on-primary"),
        "on-down": v("on-down"),

        // Old names, now aliases. New code uses the names above.
        purple: { neon: v("accent"), dim: v("accent") },
        cyber: {
          bg: v("bg"),
          surface: v("surface"),
          "surface-2": v("surface-2"),
          border: v("line"),
          "border-bright": v("line-strong"),
          text: v("text"),
          "text-dim": v("muted"),
          "text-faint": v("faint"),
        },
        success: v("up"),
        warning: v("warn"),
        danger: v("down"),
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        // `font-mono` used to switch to a terminal face. Numbers now stay in
        // the sans with tabular figures (see App.css); real code uses font-code.
        mono: ["var(--font-sans)"],
        code: ["var(--font-code)"],
      },
      // A bare `border` or `divide-y` draws a hairline in the theme, not Tailwind grey.
      borderColor: { DEFAULT: v("line") },
      divideColor: { DEFAULT: v("line") },
      borderRadius: {
        control: "var(--radius-control)",
        card: "var(--radius-card)",
        sheet: "var(--radius-sheet)",
      },
      boxShadow: {
        card: "0 1px 2px rgb(0 0 0 / 0.04), 0 1px 1px rgb(0 0 0 / 0.02)",
        sheet: "0 -8px 40px rgb(0 0 0 / 0.18)",
        pop: "0 8px 30px rgb(0 0 0 / 0.14)",
      },
      keyframes: {
        // The old glow and scan animations are kept as names so classes in
        // older pages still resolve, but they no longer move or glow.
        "glow-pulse": { "0%, 100%": {} },
        "pulse-red": { "0%, 100%": {} },
        "scan-line": { "0%, 100%": {} },
        "spin-slow": { to: { transform: "rotate(360deg)" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "sheet-up": { from: { transform: "translateY(24px)", opacity: "0" }, to: { transform: "translateY(0)", opacity: "1" } },
      },
      animation: {
        "glow-pulse": "none",
        "pulse-red": "none",
        "scan-line": "none",
        "spin-slow": "spin-slow 3s linear infinite",
        "fade-in": "fade-in 0.2s ease-out",
        "slide-up": "slide-up 0.25s ease-out",
        "sheet-up": "sheet-up 0.22s cubic-bezier(0.2, 0.8, 0.2, 1)",
      },
    },
  },
  plugins: [],
};
