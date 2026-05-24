import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        obsidian:  "#050505",
        "obsidian-2": "#0a0a0a",
        "obsidian-3": "#111111",
        "steel":   "#1a1a1a",
        "steel-2": "#242424",
        "muted":   "#404040",
        "faint":   "#606060",
        "dim":     "#a0a0a0",
        // Electric Purple — Shadow Agency accent
        purple: {
          DEFAULT: "#7C3AED",
          light:   "#A855F7",
          dark:    "#5B21B6",
          glow:    "rgba(124,58,237,0.3)",
          faint:   "rgba(124,58,237,0.08)",
        },
        // Status colors
        threat:  "#ef4444",
        warn:    "#f59e0b",
        safe:    "#22c55e",
      },
      fontFamily: {
        mono: ["'Courier New'", "Courier", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      boxShadow: {
        "purple-glow": "0 0 20px rgba(124,58,237,0.3), 0 0 40px rgba(124,58,237,0.1)",
        "card":        "0 1px 3px rgba(0,0,0,0.8)",
      },
      borderColor: {
        "purple-subtle": "rgba(124,58,237,0.2)",
        "purple-mid":    "rgba(124,58,237,0.4)",
        "steel-subtle":  "rgba(255,255,255,0.06)",
      },
      backgroundImage: {
        "grid-pattern": "url(\"data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32' width='32' height='32' fill='none' stroke='rgb(255,255,255,0.03)'%3e%3cpath d='M0 .5H31.5V32'/%3e%3c/svg%3e\")",
      },
    },
  },
  plugins: [],
};

export default config;
