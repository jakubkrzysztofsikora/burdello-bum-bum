/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bb: {
          dark: "#0f172a",
          card: "#1e293b",
          border: "#334155",
          text: "#f1f5f9",
          muted: "#94a3b8",
          accent: "#3b82f6",
          success: "#22c55e",
          warning: "#f59e0b",
          danger: "#ef4444",
        },
      },
    },
  },
  plugins: [],
};
