"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createMission, startRun } from "@/lib/api";

export type Destination = { x: number; y: number; label: string; bayId?: string };

export function MissionControls({ world, destination, onDestination, picking, onPicking, onClose }: {
  world: any; destination: Destination | null; onDestination: (d: Destination | null) => void;
  picking: boolean; onPicking: (value: boolean) => void; onClose: () => void;
}) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [draft, setDraft] = useState<{ id: string; title: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const bays = world?.bays ?? [];

  async function save() {
    if (!destination || pending.current) return;
    pending.current = true; setBusy(true); setError(null);
    try {
      const mission = await createMission({ title: title.trim() || `Move to ${destination.label}`, goal: { x: destination.x, y: destination.y }, ...(destination.bayId ? { bay_id: destination.bayId } : {}) });
      setDraft(mission); setSaved(true); onPicking(false);
    } catch (e: any) { setError(e.message || "Could not create mission"); }
    finally { pending.current = false; setBusy(false); }
  }

  async function start() {
    if (!draft || pending.current) return;
    pending.current = true; setBusy(true); setError(null);
    try {
      const result = await startRun(draft.id);
      router.push(`/runs/${result.run_id}`);
    } catch (e: any) { setError(e.message || "Could not start run. Your draft is saved."); }
    finally { pending.current = false; setBusy(false); }
  }

  return <aside aria-label="Mission controls" className="w-full sm:w-72 shrink-0 border-white/10 border-t sm:border-t-0 sm:border-l bg-slate-950 p-4 text-sm text-slate-200 overflow-y-auto max-h-[45vh] sm:max-h-none">
    <button aria-label="Close mission controls" className="float-right text-slate-400" onClick={onClose}>×</button>
    <h2 className="font-bold text-white">Plan a mission</h2>
    <p className="mt-1 text-xs text-slate-400">Choose a destination, save a draft, then start a governed run.</p>
    {saved && draft ? <div className="mt-4 space-y-3">
      <p role="status" className="text-emerald-300">Draft saved: {draft.title}</p>
      <p className="text-xs text-slate-400">The planner builds the route when the run starts. Every move is checked by the safety gate.</p>
      <button disabled={busy} onClick={start} className="w-full rounded-lg bg-cyan-400 px-3 py-2 font-semibold text-slate-950 disabled:opacity-50">{busy ? "Starting…" : "Start governed run"}</button>
      <Link href="/missions" className="block text-xs text-cyan-300 underline">View saved missions</Link>
      <button disabled={busy} className="text-xs underline" onClick={() => { setSaved(false); setDraft(null); setError(null); }}>Plan another mission</button>
    </div> : <div className="mt-4 space-y-3">
      <label className="block text-xs">Destination bay<select aria-label="Destination bay" value={destination?.bayId ?? ""} disabled={busy} onChange={(e) => {
        const bay = bays.find((b: any) => b.id === e.target.value);
        onDestination(bay ? { x: bay.x, y: bay.y, label: bay.id, bayId: bay.id } : null); onPicking(false); setError(null);
      }} className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-900 p-2"><option value="">Choose a bay or pick the floor</option>{bays.map((b: any) => <option key={b.id} value={b.id}>{b.id} · {b.type.replaceAll("_", " ")}</option>)}</select></label>
      <button aria-pressed={picking} disabled={busy || !world} onClick={() => onPicking(!picking)} className={`w-full rounded-lg border px-3 py-2 text-xs ${picking ? "border-cyan-400 text-cyan-200" : "border-slate-700"}`}>{picking ? "Cancel floor selection" : "Pick destination on floor"}</button>
      {picking && <p role="status" className="text-xs text-cyan-200">Click an open floor area in Overview. Drag to orbit; scroll to zoom.</p>}
      {destination && <div className="rounded-lg border border-cyan-900 bg-cyan-950/40 p-3 text-xs"><strong className="text-cyan-200">{destination.label}</strong><p className="mt-1">X {destination.x.toFixed(2)} m · Y {destination.y.toFixed(2)} m</p><p className="mt-1 text-slate-400">Destination marker only. Route planning happens at run start.</p></div>}
      <label className="block text-xs">Mission instruction<input aria-label="Mission instruction" maxLength={200} disabled={busy} placeholder="Optional instruction" value={title} onChange={(e) => setTitle(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 p-2" /></label>
      <button disabled={!destination || busy} onClick={save} className="w-full rounded-lg bg-cyan-400 px-3 py-2 font-semibold text-slate-950 disabled:opacity-40">{busy ? "Saving…" : "Save mission draft"}</button>
    </div>}
    {error && <p role="alert" className="mt-3 text-xs text-red-300">{error}</p>}
  </aside>;
}
