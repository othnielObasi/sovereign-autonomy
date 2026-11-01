"use client";

/**
 * Mission-control UI primitives. One accent colour (cyan); green / amber / red
 * are reserved for gate verdicts so a decision always reads at a glance.
 */
import React, { useState } from "react";
import Link from "next/link";

export function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

/* ── Layout ─────────────────────────────────────────────────────────────── */

export function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return <div className={cx("mx-auto px-4 sm:px-6 py-6 sm:py-8", wide ? "max-w-[1600px]" : "max-w-7xl")}>{children}</div>;
}

export function PageHeader({ eyebrow, title, subtitle, actions }: {
  eyebrow?: string; title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-6">
      <div className="min-w-0">
        {eyebrow && <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-mc-accent mb-1.5">{eyebrow}</div>}
        <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight text-mc-ink">{title}</h1>
        {subtitle && <p className="mt-1.5 text-sm text-mc-mute max-w-3xl leading-relaxed">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 shrink-0">{actions}</div>}
    </header>
  );
}

export function Panel({ title, subtitle, actions, children, className, padded = true, id }: {
  title?: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode;
  children?: React.ReactNode; className?: string; padded?: boolean; id?: string;
}) {
  return (
    <section id={id} className={cx("rounded-xl border border-mc-line bg-mc-panel", className)}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 px-4 pt-3.5 pb-2.5 border-b border-mc-line/70">
          <div className="min-w-0">
            {title && <h2 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-mc-ink">{title}</h2>}
            {subtitle && <p className="text-xs text-mc-dim mt-0.5">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>
      )}
      <div className={padded ? "p-4" : ""}>{children}</div>
    </section>
  );
}

/* ── Data display ───────────────────────────────────────────────────────── */

export type Tone = "neutral" | "accent" | "ok" | "warn" | "stop" | "info" | "nv";

const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-mc-ink", accent: "text-mc-accent", ok: "text-mc-ok", warn: "text-mc-warn",
  stop: "text-mc-stop", info: "text-mc-info", nv: "text-mc-nv",
};
const TONE_PILL: Record<Tone, string> = {
  neutral: "text-mc-mute border-mc-line2 bg-mc-raise",
  accent: "text-mc-accent border-mc-accent/30 bg-mc-accent/10",
  ok: "text-mc-ok border-mc-ok/30 bg-mc-ok/10",
  warn: "text-mc-warn border-mc-warn/30 bg-mc-warn/10",
  stop: "text-mc-stop border-mc-stop/30 bg-mc-stop/10",
  info: "text-mc-info border-mc-info/30 bg-mc-info/10",
  nv: "text-mc-nv border-mc-nv/30 bg-mc-nv/10",
};

export function Pill({ tone = "neutral", children, dot = false, className }: {
  tone?: Tone; children: React.ReactNode; dot?: boolean; className?: string;
}) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-semibold whitespace-nowrap", TONE_PILL[tone], className)}>
      {dot && <span className="w-1.5 h-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

/** Gate verdict → tone. The only place verdict colours are decided. */
export function verdictTone(v?: string | null): Tone {
  const s = String(v || "").toUpperCase();
  if (["APPROVED", "SAFE", "COMPLETED", "OK", "AGREE", "PASS", "PASSED", "VALID"].includes(s)) return "ok";
  if (["SLOW", "NEEDS_REVIEW", "REPLAN", "PAUSED", "HOLDING", "UNCONFIRMED_SIGHTING", "PLANNING", "WARN", "DRIFT"].includes(s)) return "warn";
  if (["DENIED", "STOP", "FAILED", "MISSED_HAZARD", "BLOCKED", "INVALID", "FAILED_SAFETY"].includes(s)) return "stop";
  if (["RUNNING", "EXECUTING"].includes(s)) return "accent";
  return "neutral";
}

export function Verdict({ value, className }: { value?: string | null; className?: string }) {
  return <Pill tone={verdictTone(value)} dot className={className}>{String(value || "—").replace(/_/g, " ")}</Pill>;
}

export function Stat({ label, value, hint, tone = "neutral", className }: {
  label: React.ReactNode; value: React.ReactNode; hint?: React.ReactNode; tone?: Tone; className?: string;
}) {
  return (
    <div className={cx("rounded-xl border border-mc-line bg-mc-panel px-4 py-3.5", className)}>
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-mc-dim">{label}</div>
      <div className={cx("mt-1 text-2xl font-semibold tabular", TONE_TEXT[tone])}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-mc-mute leading-snug">{hint}</div>}
    </div>
  );
}

export function KV({ k, v, mono = false }: { k: React.ReactNode; v: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 border-b border-mc-line/60 last:border-0">
      <span className="text-xs text-mc-dim">{k}</span>
      <span className={cx("text-xs text-mc-ink text-right min-w-0 truncate", mono && "font-mono")}>{v}</span>
    </div>
  );
}

export function Mono({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cx("font-mono text-[12px] text-mc-accent", className)}>{children}</span>;
}

export function Empty({ title, children }: { title: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="text-center py-10 px-4">
      <div className="text-sm font-medium text-mc-mute">{title}</div>
      {children && <div className="mt-1.5 text-xs text-mc-dim max-w-md mx-auto leading-relaxed">{children}</div>}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: Tone; children: React.ReactNode }) {
  return <div className={cx("rounded-lg border px-3 py-2 text-xs leading-relaxed", TONE_PILL[tone])}>{children}</div>;
}

/* ── Controls ───────────────────────────────────────────────────────────── */

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";
const BTN: Record<BtnVariant, string> = {
  primary: "bg-mc-accent text-mc-bg hover:bg-cyan-300 font-semibold",
  secondary: "border border-mc-line2 bg-mc-raise text-mc-ink hover:border-mc-accent/50",
  ghost: "text-mc-mute hover:text-mc-ink hover:bg-mc-raise",
  danger: "bg-mc-stop text-white hover:bg-red-400 font-semibold",
};

export function Button({ variant = "secondary", href, className, children, ...rest }: {
  variant?: BtnVariant; href?: string; className?: string; children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls = cx("inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm transition disabled:opacity-50 disabled:cursor-not-allowed", BTN[variant], className);
  if (href) return <Link href={href} className={cls}>{children}</Link>;
  return <button className={cls} {...rest}>{children}</button>;
}

export function Tabs<T extends string>({ tabs, value, onChange, className, variant = "underline" }: {
  tabs: Array<{ id: T; label: React.ReactNode; count?: number }>; value: T; onChange: (id: T) => void; className?: string;
  variant?: "underline" | "segmented";
}) {
  if (variant === "segmented") {
    return (
      <div role="tablist" className={cx("inline-flex items-center gap-0.5 rounded-lg border border-mc-line bg-mc-panel p-0.5", className)}>
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
            className={cx("px-3 py-1.5 rounded-md text-[13px] font-medium whitespace-nowrap",
              value === t.id ? "bg-mc-raise text-mc-ink" : "text-mc-dim hover:text-mc-mute")}>
            {t.label}
          </button>
        ))}
      </div>
    );
  }
  return (
    <div role="tablist" className={cx("flex items-center gap-1 overflow-x-auto mc-scroll border-b border-mc-line", className)}>
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("px-3 py-2 text-[13px] font-medium whitespace-nowrap border-b-2 -mb-px transition",
            value === t.id ? "border-mc-accent text-mc-ink" : "border-transparent text-mc-dim hover:text-mc-mute")}>
          {t.label}
          {t.count != null && <span className="ml-1.5 text-[11px] text-mc-dim tabular">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function useTabs<T extends string>(initial: T) {
  return useState<T>(initial);
}

/** Small horizontal bar for comparisons (benchmarks etc.). */
export function Bar({ value, max, tone = "accent" }: { value: number; max: number; tone?: Tone }) {
  const pct = max > 0 ? Math.max(2, Math.min(100, (value / max) * 100)) : 0;
  const bg: Record<Tone, string> = { neutral: "bg-mc-mute", accent: "bg-mc-accent", ok: "bg-mc-ok", warn: "bg-mc-warn", stop: "bg-mc-stop", info: "bg-mc-info", nv: "bg-mc-nv" };
  return (
    <div className="h-2 rounded-full bg-mc-raise overflow-hidden">
      <div className={cx("h-full rounded-full", bg[tone])} style={{ width: value === 0 ? "0%" : `${pct}%` }} />
    </div>
  );
}
