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
          bg: '#dce5ef',
          panel: '#ffffff',
          raise: '#edf2f8',
          line: '#c8d3df',
          line2: '#a9bbcb',
          ink: '#192e42',
          mute: '#40566b',
          dim: '#4a6073',
          accent: '#466b36',
          ok: '#28794d',
          warn: '#946317',
          stop: '#b84237',
          info: '#426b8a',
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
