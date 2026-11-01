"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/components/ui";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

// Five destinations. /demo (guided demo) is reached from the Overview page;
// /compliance and /audit live under Evidence.
const links = [
  { href: "/", label: "Overview", match: (p: string) => p === "/" || p.startsWith("/demo") },
  { href: "/missions", label: "Missions", match: (p: string) => p.startsWith("/missions") },
  { href: "/runs", label: "Runs", match: (p: string) => p.startsWith("/runs") },
  { href: "/policies", label: "Governance", match: (p: string) => p.startsWith("/policies") },
  { href: "/evidence", label: "Evidence", match: (p: string) => ["/evidence", "/compliance", "/audit"].some((x) => p.startsWith(x)) },
];

/** Live system status from /health: gate, planner and simulator. */
export function StatusPill() {
  const [h, setH] = useState<any>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const r = await fetch(`${API_BASE}/health`, { cache: "no-store" });
        const d = await r.json();
        if (live) { setH(d); setDown(!r.ok); }
      } catch { if (live) setDown(true); }
    };
    load();
    const id = setInterval(load, 20000);
    return () => { live = false; clearInterval(id); };
  }, []);
  const ok = !down && h?.status === "ok";
  const sim = h?.checks?.simulator === "ok";
  const planner = h?.planner_provider === "nemotron" ? "Nemotron" : h?.planner_provider || "…";
  return (
    <div className={cx("hidden lg:flex items-center gap-2 rounded-full border px-3 py-1 text-xs",
      ok ? "border-mc-ok/30 bg-mc-ok/10 text-mc-ok" : "border-mc-stop/30 bg-mc-stop/10 text-mc-stop")}
      title={h ? `API ${h.status} · database ${h.checks?.database} · simulator ${h.checks?.simulator}` : "Checking…"}>
      <span className={cx("w-1.5 h-1.5 rounded-full bg-current", ok && "animate-live-dot")} />
      {down ? "Gate offline" : !h ? "Connecting…" : <>Gate live · {planner}{sim ? "" : " · sim offline"}</>}
    </div>
  );
}

export function NavLinks() {
  const pathname = usePathname() || "/";
  const [open, setOpen] = useState(false);

  return (
    <>
      <div className="hidden md:flex items-center gap-0.5 ml-6">
        {links.map((l) => (
          <Link key={l.href} href={l.href}
            className={cx("px-3 py-1.5 rounded-md text-[13px] font-medium transition",
              l.match(pathname) ? "bg-mc-raise text-mc-ink shadow-[inset_0_-2px_0_#22d3ee]" : "text-mc-mute hover:text-mc-ink")}>
            {l.label}
          </Link>
        ))}
      </div>

      <button className="md:hidden ml-2 p-2 rounded-lg hover:bg-mc-raise text-mc-mute"
        onClick={() => setOpen(!open)} aria-label="Toggle navigation" aria-expanded={open}>
        <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          {open ? <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                : <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />}
        </svg>
      </button>

      {open && (
        <div className="absolute top-full left-0 right-0 bg-mc-panel border-b border-mc-line md:hidden z-50">
          <div className="px-4 py-2 space-y-1">
            {[...links, { href: "/twin", label: "Live warehouse", match: (p: string) => p.startsWith("/twin") }].map((l) => (
              <Link key={l.href} href={l.href} onClick={() => setOpen(false)}
                className={cx("block px-3 py-2 rounded-md text-sm font-medium",
                  l.match(pathname) ? "bg-mc-raise text-mc-ink" : "text-mc-mute hover:text-mc-ink")}>
                {l.label}
              </Link>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
