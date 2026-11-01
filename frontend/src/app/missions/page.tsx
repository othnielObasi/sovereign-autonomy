"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  createMission, deleteMission, getWorld, listMissions, pauseMission, replayMission, resumeMission, startRun, updateMission,
} from "@/lib/api";
import type { Mission, MissionStatus } from "@/lib/types";
import { Button, Empty, Mono, Notice, Page, PageHeader, Panel, Pill, Tabs, Verdict, cx } from "@/components/ui";

const BAY_PATTERN = /\b([ABSR])-?(\d{1,2})\b/i;
function resolveBayGoal(text: string, bays: any[]): { x: number; y: number } | null {
  const m = text?.match(BAY_PATTERN);
  if (!m || !bays?.length) return null;
  const bay = bays.find((b: any) => b.id?.toUpperCase() === `${m[1].toUpperCase()}-${m[2].padStart(2, "0")}`);
  return bay && typeof bay.x === "number" ? { x: bay.x, y: bay.y } : null;
}

const PRESETS = [
  { title: "Deliver pallet to dock B-03", bay: "B-03" },
  { title: "Pick items from rack A-04", bay: "A-04" },
  { title: "Restock rack A-08", bay: "A-08" },
  { title: "Move goods to staging S-01", bay: "S-01" },
  { title: "Hazmat container to dock B-05", bay: "B-05" },
];

const STATUS_LABEL: Record<string, string> = { draft: "DRAFT", executing: "RUNNING", paused: "PAUSED", completed: "COMPLETED", deleted: "DELETED", failed: "FAILED" };

export default function MissionsPage() {
  const router = useRouter();
  const [missions, setMissions] = useState<Mission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilterState] = useState<"all" | MissionStatus>("all");
  const setFilter = (v: string) => setFilterState(v as any);
  const [bays, setBays] = useState<any[]>([]);
  // create
  const [title, setTitle] = useState(PRESETS[0].title);
  const [bayId, setBayId] = useState(PRESETS[0].bay);
  const [creating, setCreating] = useState(false);
  // edit
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editGoal, setEditGoal] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  async function reload() {
    try { setMissions(await listMissions()); } catch { setError("Failed to load missions"); } finally { setLoading(false); }
  }
  useEffect(() => { reload(); getWorld().then((w: any) => setBays(w?.bays || [])).catch(() => {}); }, []);

  const act = (fn: () => Promise<any>) => async () => {
    setError(null);
    try { await fn(); } catch (e: any) { setError(e.message || "That didn't work"); }
  };

  async function create(start: boolean) {
    setCreating(true); setError(null);
    try {
      const m = await createMission({ title, bay_id: bayId || undefined } as any);
      if (start) {
        const r = await startRun(m.id);
        router.push(`/runs/${r.run_id}`);
        return;
      }
      setMissions((prev) => [m, ...prev]);
    } catch (e: any) { setError(e.message); } finally { setCreating(false); }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: missions.length };
    missions.forEach((m) => { c[m.status] = (c[m.status] || 0) + 1; });
    return c;
  }, [missions]);
  const filtered = filter === "all" ? missions : missions.filter((m) => m.status === filter);
  const bayGroups = useMemo(() => {
    const g: Record<string, any[]> = {};
    bays.forEach((b) => { const k = b.type || "bay"; (g[k] = g[k] || []).push(b); });
    return g;
  }, [bays]);

  return (
    <Page wide>
      <PageHeader eyebrow="Missions" title="Missions"
        subtitle="A mission is a destination for the robot. Nemotron plans the route; the gate approves every move before it runs."
        actions={<Button href="/twin">Pick a bay on the warehouse →</Button>} />

      <div className="grid lg:grid-cols-3 gap-4">
        {/* Create */}
        <Panel title="New mission" className="lg:self-start">
          <div className="flex flex-wrap gap-1.5 mb-4">
            {PRESETS.map((p) => (
              <button key={p.bay} onClick={() => { setTitle(p.title); setBayId(p.bay); }}
                className={cx("rounded-md border px-2.5 py-1 text-xs", bayId === p.bay && title === p.title ? "border-mc-accent bg-mc-accent/10 text-mc-ink" : "border-mc-line2 text-mc-mute hover:text-mc-ink")}>
                {p.title}
              </button>
            ))}
          </div>
          <label className="block text-xs text-mc-dim mb-1" htmlFor="m-title">Instruction for the planner</label>
          <input id="m-title" value={title} onChange={(e) => { setTitle(e.target.value); const g = e.target.value.match(BAY_PATTERN); if (g) setBayId(`${g[1].toUpperCase()}-${g[2].padStart(2, "0")}`); }}
            className="w-full rounded-lg bg-mc-raise border border-mc-line2 px-3 py-2 text-sm focus:outline-none focus:border-mc-accent" />
          <label className="block text-xs text-mc-dim mt-3 mb-1" htmlFor="m-bay">Destination bay</label>
          <select id="m-bay" value={bayId} onChange={(e) => setBayId(e.target.value)}
            className="w-full rounded-lg bg-mc-raise border border-mc-line2 px-3 py-2 text-sm">
            {Object.entries(bayGroups).map(([type, list]) => (
              <optgroup key={type} label={type}>
                {list.map((b) => <option key={b.id} value={b.id}>{b.id} · ({b.x}, {b.y})</option>)}
              </optgroup>
            ))}
            {bays.length === 0 && <option value={bayId}>{bayId}</option>}
          </select>
          <div className="grid grid-cols-2 gap-2 mt-4">
            <Button onClick={() => create(false)} disabled={creating || !title.trim()}>Save draft</Button>
            <Button variant="primary" onClick={() => create(true)} disabled={creating || !title.trim()}>{creating ? "Starting…" : "Start governed run"}</Button>
          </div>
          <p className="mt-3 text-[11px] text-mc-dim leading-relaxed">On the public demo the robot is shared: if a mission is already running you&apos;ll be pointed to it.</p>
        </Panel>

        {/* List */}
        <div className="lg:col-span-2 space-y-3">
          <Tabs value={filter} onChange={setFilter} tabs={(["all", "draft", "executing", "paused", "completed"] as const).map((f) => ({
            id: f, label: f === "all" ? "All" : f === "executing" ? "Running" : f[0].toUpperCase() + f.slice(1), count: counts[f] || 0,
          }))} />
          {error && <Notice tone="stop">{error} <button onClick={() => setError(null)} className="underline ml-2">dismiss</button></Notice>}
          {loading ? <div className="text-sm text-mc-dim py-6">Loading missions…</div> : filtered.length === 0 ? (
            <Panel><Empty title={`No ${filter === "all" ? "" : filter} missions`}>Create one on the left, or pick a bay in the live warehouse.</Empty></Panel>
          ) : (
            <Panel padded={false}>
              <ul className="divide-y divide-mc-line">
                {filtered.map((m) => {
                  const editable = m.status === "draft" || m.status === "paused";
                  return (
                    <li key={m.id} className="px-4 py-3">
                      {editingId === m.id ? (
                        <div className="flex flex-wrap items-end gap-2">
                          <label className="flex-1 min-w-[200px] text-xs text-mc-dim">Instruction
                            <input value={editTitle} onChange={(e) => { setEditTitle(e.target.value); const g = resolveBayGoal(e.target.value, bays); if (g) setEditGoal(g); }}
                              className="mt-1 w-full rounded-lg bg-mc-raise border border-mc-line2 px-3 py-1.5 text-sm text-mc-ink" /></label>
                          <label className="w-20 text-xs text-mc-dim">X<input type="number" value={editGoal.x} onChange={(e) => setEditGoal({ ...editGoal, x: Number(e.target.value) })}
                            className="mt-1 w-full rounded-lg bg-mc-raise border border-mc-line2 px-2 py-1.5 text-sm text-mc-ink" /></label>
                          <label className="w-20 text-xs text-mc-dim">Y<input type="number" value={editGoal.y} onChange={(e) => setEditGoal({ ...editGoal, y: Number(e.target.value) })}
                            className="mt-1 w-full rounded-lg bg-mc-raise border border-mc-line2 px-2 py-1.5 text-sm text-mc-ink" /></label>
                          <Button variant="primary" onClick={act(async () => { const u = await updateMission(m.id, { title: editTitle, goal: editGoal }); setMissions((p) => p.map((x) => (x.id === m.id ? u : x))); setEditingId(null); })}>Save</Button>
                          <Button variant="ghost" onClick={() => setEditingId(null)}>Cancel</Button>
                        </div>
                      ) : (
                        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <Verdict value={STATUS_LABEL[m.status] || m.status} />
                              <span className="font-medium truncate">{m.title}</span>
                            </div>
                            <div className="mt-1 text-xs text-mc-dim flex flex-wrap gap-x-3">
                              <Mono className="text-mc-dim">{m.id}</Mono>
                              {m.goal && <span>goal ({m.goal.x}, {m.goal.y}){m.goal.zone ? ` · ${m.goal.zone}` : ""}</span>}
                              <span>{new Date(m.created_at).toLocaleString()}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5 flex-wrap">
                            {editable && <Button variant="ghost" className="px-2.5 py-1 text-xs" onClick={() => { setEditingId(m.id); setEditTitle(m.title); setEditGoal(resolveBayGoal(m.title, bays) || { x: m.goal?.x ?? 0, y: m.goal?.y ?? 0 }); }}>Edit</Button>}
                            {(m.status === "draft" || m.status === "paused") && <Button variant="primary" className="px-2.5 py-1 text-xs" onClick={act(async () => { const r = await startRun(m.id); router.push(`/runs/${r.run_id}`); })}>{m.status === "paused" ? "Re-run" : "Run"}</Button>}
                            {m.status === "executing" && <Button className="px-2.5 py-1 text-xs" onClick={act(async () => { const u = await pauseMission(m.id); setMissions((p) => p.map((x) => (x.id === m.id ? u : x))); })}>Pause</Button>}
                            {m.status === "paused" && <Button className="px-2.5 py-1 text-xs" onClick={act(async () => { const u = await resumeMission(m.id); setMissions((p) => p.map((x) => (x.id === m.id ? u : x))); })}>Resume</Button>}
                            {m.status === "completed" && <Button className="px-2.5 py-1 text-xs" onClick={act(async () => { const u = await replayMission(m.id); setMissions((p) => p.map((x) => (x.id === m.id ? u : x))); })}>Replay</Button>}
                            {(m.status === "draft" || m.status === "paused" || m.status === "completed") && (
                              <Button variant="ghost" className="px-2 py-1 text-xs text-mc-stop" onClick={act(async () => { if (!confirm("Delete this mission?")) return; await deleteMission(m.id); setMissions((p) => p.filter((x) => x.id !== m.id)); })}>Delete</Button>
                            )}
                          </div>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Panel>
          )}
          <div className="text-xs text-mc-dim">Looking for results? <Link href="/runs" className="text-mc-accent hover:underline">Every run</Link> keeps its full decision record.</div>
        </div>
      </div>
    </Page>
  );
}
