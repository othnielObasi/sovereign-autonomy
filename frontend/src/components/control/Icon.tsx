import type { CSSProperties } from "react";

const paths: Record<string, React.ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
  command: <><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9M8 5l8 4.5"/></>,
  route: <><circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M5 7v8a4 4 0 0 0 8 0V9a4 4 0 0 1 8 0v3M16 10l5 3 2-5"/></>,
  shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/></>,
  layers: <><path d="m12 3 10 5-10 5L2 8l10-5ZM2 12l10 5 10-5M2 16l10 5 10-5"/></>,
  chart: <><path d="M4 3v17h17M8 15l4-5 4 2 5-7"/><path d="M17 5h4v4"/></>,
  robot: <><rect x="4" y="7" width="16" height="13" rx="4"/><path d="M12 3v4M8 13h1m6 0h1M9 17h6M1 11v5m22-5v5"/><circle cx="12" cy="3" r="1"/></>,
  arrow: <><path d="M4 12h16m-6-6 6 6-6 6"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  play: <path d="m8 4 12 8-12 8V4Z"/>,
  stop: <rect x="5" y="5" width="14" height="14" rx="3"/>,
  pause: <><path d="M8 4v16M16 4v16"/></>,
  mic: <><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  cross: <path d="m6 6 12 12M6 18 18 6"/>,
  chevron: <path d="m9 5 7 7-7 7"/>,
  down: <path d="m6 9 6 6 6-6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/></>,
  bolt: <path d="m13 2-9 12h7l-1 8 10-12h-7l1-8Z"/>,
  alert: <><path d="m12 3 10 17H2L12 3Z"/><path d="M12 9v4m0 3v1"/></>,
  eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/></>,
  fullscreen: <path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5"/>,
  user: <><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></>,
  menu: <path d="M4 6h16M4 12h16M4 18h16"/>,
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/></>,
};

export function Icon({ name, size = 19, className, style }: { name: string; size?: number; className?: string; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" className={className} style={style} aria-hidden="true">{paths[name] || paths.grid}</svg>;
}

export function BrandMark() {
  return <svg viewBox="0 0 40 40" width="37" height="37" fill="none" aria-hidden="true"><rect width="40" height="40" rx="12" fill="currentColor"/><path d="m11 23 9-13 9 13h-7l-2 7-2-7h-7Z" stroke="#d7f5a2" strokeWidth="2" strokeLinejoin="round"/><path d="M15 20h10" stroke="#d7f5a2" strokeWidth="2"/></svg>;
}
