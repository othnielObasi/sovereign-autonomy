/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      // Mission-control palette. Status colours are reserved for gate verdicts:
      // ok = approved / safe, warn = slow / caution, stop = denied / stop.
      colors: {
        mc: {
          bg: '#070b12',
          panel: '#0c131e',
          raise: '#111b29',
          line: '#1b2636',
          line2: '#253246',
          ink: '#e6edf5',
          mute: '#94a3b8',
          dim: '#64748b',
          accent: '#22d3ee',
          ok: '#22c55e',
          warn: '#f59e0b',
          stop: '#ef4444',
          info: '#60a5fa',
          nv: '#76b900',       // NVIDIA green, used only for model attribution
        },
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
    },
  },
  plugins: [],
}
