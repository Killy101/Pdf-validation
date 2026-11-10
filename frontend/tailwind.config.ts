import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/context/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        sky: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
          950: '#082f49',
        },
      },
      backgroundImage: {
        'soft-radial': 'radial-gradient(circle at 50% -20%, #e0f2fe 0%, #f0f9ff 35%, #ffffff 80%)',
        'subtle-card': 'linear-gradient(135deg, #ffffff 0%, #f0f9ff 100%)',
        'subtle-card-hover': 'linear-gradient(135deg, #ffffff 0%, #e0f2fe 100%)',
        'gradient-sky': 'linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%)',
        'gradient-sky-light': 'linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%)',
        'gradient-sky-soft': 'linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 50%, #ffffff 100%)',
        'gradient-header': 'linear-gradient(90deg, #ffffff 0%, #f0f9ff 50%, #ffffff 100%)',
      },
      boxShadow: {
        'soft-sky': '0 8px 24px -6px rgba(14, 165, 233, 0.2), 0 3px 8px -2px rgba(14, 165, 233, 0.1)',
        'soft-card': '0 8px 24px -4px rgba(12, 74, 110, 0.06), 0 2px 6px -2px rgba(12, 74, 110, 0.03)',
        'premium-card': '0 12px 32px -8px rgba(14, 165, 233, 0.12), 0 2px 8px -2px rgba(14, 165, 233, 0.04)',
        'glow-sky': '0 0 24px -2px rgba(56, 189, 248, 0.35)',
        'soft-focus': '0 0 0 3px rgba(56, 189, 248, 0.3)',
      },
      animation: {
        'pulse-subtle': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};
export default config;

