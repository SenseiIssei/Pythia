/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: { DEFAULT: "#00f0ff", hover: "#00d4e6", dim: "#00a8b5" },
        purple: { neon: "#a855f7", dim: "#7c3aed" },
        cyber: {
          bg: "#0a0a0f",
          surface: "#13131a",
          "surface-2": "#1a1a24",
          border: "#1e1e2a",
          "border-bright": "#2a2a3e",
          text: "#e6e6ee",
          // Raised from #8888a0 / #555568: the faint grey failed WCAG AA on
          // the card surface (2.6:1). These two read at about 6.7:1 and 4.6:1.
          "text-dim": "#9a9ab2",
          "text-faint": "#7d7d93",
        },
        success: "#22c55e",
        warning: "#f59e0b",
        danger: "#ef4444",
      },
      fontFamily: {
        // Numbers, headings and labels stay in the monospace that gives Pythia
        // its look; running text uses the system sans, which reads far more
        // easily in paragraphs and fits a phone screen.
        mono: ['"JetBrains Mono"', '"Fira Code"', "monospace"],
        sans: ['"Inter"', '"Segoe UI Variable Text"', '"Segoe UI"', "system-ui", "-apple-system", "Roboto", "sans-serif"],
      },
      keyframes: {
        "glow-pulse": {
          "0%, 100%": { boxShadow: "0 0 8px rgba(0,240,255,0.3)" },
          "50%": { boxShadow: "0 0 20px rgba(0,240,255,0.6)" },
        },
        "pulse-red": {
          "0%, 100%": { boxShadow: "0 0 8px rgba(239,68,68,0.4)" },
          "50%": { boxShadow: "0 0 22px rgba(239,68,68,0.8)" },
        },
        "spin-slow": { to: { transform: "rotate(360deg)" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "scan-line": {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "glow-pulse": "glow-pulse 2s ease-in-out infinite",
        "pulse-red": "pulse-red 1.6s ease-in-out infinite",
        "spin-slow": "spin-slow 3s linear infinite",
        "fade-in": "fade-in 0.3s ease-out",
        "slide-up": "slide-up 0.35s ease-out",
        "scan-line": "scan-line 3s linear infinite",
      },
    },
  },
  plugins: [],
};
