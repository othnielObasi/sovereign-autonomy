"use client";

import { useEffect, useState } from "react";
import { getBulletins, getSiteIntelLookups, getSiteIntelStatus, postBulletin } from "@/lib/api";

type Flag = { flag: string; match: string };
type Result = { url: string; domain: string; title: string; trusted_source: boolean; verdict: string; flags: Flag[]; classes: string[]; excerpt: string };
type Lookup = {
  at: number; hazard_id: string | null; substance: string; query: string; mode: string;
  tavily: { latency_ms: number; credits: number | null; error: string | null };
  results: Result[];
  assessment: { classes_enforced: string[]; classes_advisory: string[]; evidence: Record<string, string[]>; radius: number; slow_radius: number; max_speed: number; basis: string };
};
type Zone = { id: string; label: string; radius: number; slow_radius: number; max_speed: number; basis: string; sources: string[]; live: boolean };
type Bulletin = { at: number; verdict: string; flags: Flag[]; excerpt: string; effect: string };

const FLAG_TEXT: Record<string, string> = {
  prompt_injection: "instructions aimed at the AI",
  relax_safety: "tries to relax a safety rule",
  robot_permission: "grants robots permission",
  proximity_claim: "claims robots may get close to people",
  hidden_content: "hidden text",
  encoded_payload: "encoded payload",
  script: "script",
};

const nice = (c: string) => c.replace("_", " ");

/**
 * Site intelligence: what Tavily found about a hazard, what the firewall let
 * through, the zone the gate now enforces, and the noticeboard injection demo.
 */
export function SiteIntelPanel() {
  const [status, setStatus] = useState<any>(null);
  const [lookups, setLookups] = useState<Lookup[]>([]);
  const [bulletins, setBulletins] = useState<Bulletin[]>([]);
  const [draft, setDraft] = useState<string>("");
  const [posting, setPosting] = useState(false);
  const [open, setOpen] = useState<number | null>(0);

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const [s, l, b] = await Promise.all([getSiteIntelStatus(), getSiteIntelLookups(3), getBulletins(3)]);
        if (!live) return;
        setStatus(s);
        setLookups(l.lookups || []);
        setBulletins(b.bulletins || []);
        setDraft((d) => d || b.demo_text || "");
      } catch (_) {}
    };
    load();
    const id = setInterval(load, 2500);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, []);

  const zones: Zone[] = status?.active_constraints || [];
  const liveMode = !!status?.tavily_live;

  async function post() {
    setPosting(true);
    try {
      const rec = await postBulletin(draft);
      setBulletins((b) => [rec, ...b].slice(0, 3));
    } catch (_) {}
    setPosting(false);
  }

  return (
    <div className="bg-mc-panel/60 rounded-xl border border-mc-line p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-mc-ink tracking-wide uppercase">Site intelligence</h3>
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${liveMode ? "text-emerald-300 border-emerald-500/40 bg-emerald-500/10" : "text-amber-300 border-amber-500/40 bg-amber-500/10"}`}>
          {liveMode ? "Tavily live" : "Offline samples"}
        </span>
      </div>
      <p className="text-[11px] text-mc-mute mb-3 leading-relaxed">
        Hazard guidance is looked up with Tavily from authoritative safety publishers, screened as untrusted, and can only make the rules stricter. The gate never reads outside text.
      </p>

      {/* zones in force */}
      <div className="space-y-2 mb-3">
        {zones.length === 0 ? (
          <div className="text-xs text-mc-dim">No hazard zones in force.</div>
        ) : (
          zones.map((z) => (
            <div key={z.id} className="rounded-lg border border-red-500/40 bg-red-500/10 p-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-bold text-red-200">No entry · {z.label}</span>
                <span className="text-[10px] text-red-200/80 font-mono">{z.radius.toFixed(1)} m · ≤{z.max_speed.toFixed(1)} m/s within {z.slow_radius.toFixed(1)} m</span>
              </div>
              <div className="text-[11px] text-mc-ink/85 mt-1">{z.basis}</div>
              {z.sources?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {z.sources.map((d) => (
                    <span key={d} className="text-[10px] px-1.5 py-0.5 rounded bg-mc-bg/70 text-emerald-300 border border-emerald-500/30">✓ {d}</span>
                  ))}
                  {!z.live && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30">sample data</span>}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* lookups */}
      {lookups.map((lk, i) => (
        <div key={lk.at} className="rounded-lg border border-mc-line bg-mc-bg/40 mb-2">
          <button onClick={() => setOpen(open === i ? null : i)} className="w-full flex items-center justify-between px-2.5 py-2 text-left">
            <span className="text-xs text-mc-ink">
              <span className="font-semibold">Lookup:</span> {lk.substance}
              <span className="text-mc-dim"> · {lk.results.length} sources · {lk.results.filter((r) => r.verdict === "quarantined").length} quarantined</span>
            </span>
            <span className="text-mc-dim text-xs">{open === i ? "▾" : "▸"}</span>
          </button>
          {open === i && (
            <div className="px-2.5 pb-2.5 space-y-1.5">
              <div className="text-[10px] font-mono text-mc-dim break-words">
                {lk.mode === "live" ? `Tavily · ${Math.round(lk.tavily.latency_ms)} ms${lk.tavily.credits != null ? ` · ${lk.tavily.credits} credits` : ""}` : lk.mode === "offline_sample" ? "Offline sample text (no TAVILY_API_KEY)" : `Live search failed (${lk.tavily.error}); offline samples used`}
                {" · "}“{lk.query}”
              </div>
              <div className="flex flex-wrap gap-1">
                {lk.assessment.classes_enforced.map((c) => (
                  <span key={c} className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-200 border border-red-500/30">{nice(c)} · {lk.assessment.evidence[c]?.length} sources · enforced</span>
                ))}
                {lk.assessment.classes_advisory.map((c) => (
                  <span key={c} className="text-[10px] px-1.5 py-0.5 rounded bg-mc-raise/60 text-mc-ink/85 border border-mc-line2">{nice(c)} · 1 source · advice only</span>
                ))}
              </div>
              {lk.results.map((r) => (
                <div key={r.url} className={`rounded border px-2 py-1.5 ${r.verdict === "quarantined" ? "border-red-500/40 bg-red-500/5" : "border-mc-line"}`}>
                  <div className="flex items-center justify-between gap-2">
                    <a href={r.url} target="_blank" rel="noreferrer" className="text-[11px] text-cyan-300 hover:underline truncate">{r.domain}</a>
                    <span className={`text-[10px] font-semibold ${r.verdict === "quarantined" ? "text-red-300" : "text-emerald-300"}`}>{r.verdict}</span>
                  </div>
                  {r.verdict === "quarantined" ? (
                    <div className="text-[10px] text-red-200/90">{r.flags.map((f) => FLAG_TEXT[f.flag] ?? f.flag).join(" · ")}</div>
                  ) : (
                    <div className="text-[10px] text-mc-mute line-clamp-2">{r.excerpt}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      {/* noticeboard injection demo */}
      <div className="mt-3 border-t border-mc-line pt-3">
        <div className="text-xs font-semibold text-mc-ink mb-1.5">Noticeboard bulletin</div>
        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} className="w-full text-[11px] bg-mc-bg/70 border border-mc-line rounded-md p-2 text-mc-ink focus:outline-none focus:border-cyan-500" />
        <button onClick={post} disabled={posting || !draft.trim()} className="mt-1.5 text-xs font-semibold px-3 py-1.5 rounded-md bg-mc-raise hover:bg-mc-line2 text-mc-ink disabled:opacity-40">
          {posting ? "Screening…" : "Post bulletin"}
        </button>
        {bulletins[0] && (
          <div className={`mt-2 rounded-lg border p-2.5 ${bulletins[0].verdict === "quarantined" ? "border-red-500/40 bg-red-500/10" : "border-emerald-500/30 bg-emerald-500/5"}`}>
            <div className={`text-xs font-bold ${bulletins[0].verdict === "quarantined" ? "text-red-200" : "text-emerald-200"}`}>
              {bulletins[0].verdict === "quarantined" ? "Quarantined" : "Accepted as advice only"}
            </div>
            {bulletins[0].flags.length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {bulletins[0].flags.map((f, i) => (
                  <li key={i} className="text-[10px] text-red-100/90">
                    {FLAG_TEXT[f.flag] ?? f.flag}: <span className="font-mono">“{f.match}”</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="text-[11px] text-mc-ink/85 mt-1">{bulletins[0].effect}</div>
          </div>
        )}
      </div>
    </div>
  );
}
