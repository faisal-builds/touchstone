import type { Config } from "tailwindcss";

/**
 * Touchstone design tokens.
 *
 * Instrument-grade graphite-on-paper. The one signature accent is the "assay
 * streak" — a bronze→gold gradient (the streak a touchstone leaves when testing
 * gold) used only for the active-nav marker and the robustness-gauge arc. Data
 * (scores, hashes, ids, timestamps) is always set in tabular monospace.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#FAFAF8",
        surface: "#FFFFFF",
        line: "#EAEAE4",
        "line-strong": "#DBDBD3",
        ink: "#16181D",
        graphite: "#23262D",
        muted: "#6B7280",
        faint: "#9AA0A8",
        // The assay streak (signature accent).
        assay: { from: "#8A5A1C", to: "#D9A94A", DEFAULT: "#B5832B" },
        // Muted semantic scale for verdicts, risk, and exploit severity.
        pass: "#2F7D5B",
        warn: "#B5832B",
        risk: "#C2533B",
        crit: "#9B2D2D",
        info: "#3A6491",
      },
      fontFamily: {
        sans: [
          "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI",
          "Helvetica Neue", "Arial", "sans-serif",
        ],
        mono: [
          "ui-monospace", "SFMono-Regular", "SF Mono", "JetBrains Mono",
          "Menlo", "Consolas", "monospace",
        ],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
      },
      borderRadius: { md: "7px", lg: "10px", xl: "14px" },
      boxShadow: {
        card: "0 1px 2px rgba(16,18,22,0.04), 0 1px 1px rgba(16,18,22,0.03)",
        pop: "0 8px 28px rgba(16,18,22,0.12), 0 2px 6px rgba(16,18,22,0.06)",
        focus: "0 0 0 3px rgba(181,131,43,0.22)",
      },
      letterSpacing: { tightish: "-0.012em", tight2: "-0.02em" },
      keyframes: {
        "fade-in": { from: { opacity: "0", transform: "translateY(2px)" }, to: { opacity: "1", transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
        sweep: { from: { strokeDashoffset: "var(--dash)" }, to: { strokeDashoffset: "var(--target)" } },
      },
      animation: {
        "fade-in": "fade-in 0.25s ease-out both",
        shimmer: "shimmer 1.5s infinite",
        sweep: "sweep 0.9s cubic-bezier(0.22,1,0.36,1) both",
      },
    },
  },
  plugins: [],
};
export default config;
