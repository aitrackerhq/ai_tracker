/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "#0a0a0b",
          panel: "#101012",
          card: "#141417",
          hover: "#1a1a1f",
        },
        border: {
          DEFAULT: "#22222a",
          strong: "#2c2c36",
        },
        text: {
          primary: "#f4f4f6",
          muted: "#8b8b95",
          dim: "#5a5a64",
        },
        accent: {
          DEFAULT: "#5b8def",
          green: "#3ddc97",
          red: "#ff5d6c",
          amber: "#ffb84d",
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px -8px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};
