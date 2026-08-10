import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    screens: {
      sm: "360px",
      md: "768px",
      lg: "1440px",
    },
    extend: {
      colors: {
        ink: "#0B1B2B",
        "ink-muted": "#5A6B7C",
        paper: "#F6F8FA",
        surface: "#FFFFFF",
        line: "#E3E8ED",
        cobalt: "#1B4DFF",
        "cobalt-soft": "#E9EEFF",
        pass: "#0E9F6E",
        warn: "#E4A11B",
        alert: "#D7263D",
      },
      fontFamily: {
        display: ["var(--font-space-grotesk)", "sans-serif"],
        body: ["var(--font-inter)", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "monospace"],
      },
      fontSize: {
        xs: "12px",
        sm: "14px",
        base: "16px",
        lg: "20px",
        xl: "26px",
        "2xl": "34px",
        "3xl": "48px",
        "4xl": "64px",
      },
      spacing: {
        "1": "4px",
        "2": "8px",
        "3": "12px",
        "4": "16px",
        "6": "24px",
        "8": "32px",
        "12": "48px",
        "16": "64px",
        "24": "96px",
      },
      borderRadius: {
        control: "6px",
        card: "10px",
      },
      maxWidth: {
        content: "1120px",
        reading: "680px",
      },
      lineHeight: {
        prose: "1.55",
        display: "1.2",
      },
    },
  },
};

export default config;
