import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      boxShadow: {
        lift: "0 16px 35px rgba(25, 37, 30, 0.10)",
      },
      colors: {
        ink: "#18241d",
        forest: "#143a2b",
        moss: "#2f6a4f",
        canvas: "#f5f6f1",
      },
    },
  },
  plugins: [],
} satisfies Config;
