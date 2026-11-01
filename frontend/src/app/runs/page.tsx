"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { listMissions, listRuns } from "@/lib/api";
import { Button, Empty, Mono, Notice, Page, PageHeader, Panel, Tabs, Verdict } from "@/components/ui";

type RunInfo = { id: string; mission_id: string; status: string; started_at: string; ended_at: string | null };

function duration(r: RunInfo): string {
  if (!r.started_at) return "—";
  const secs = Math.max(0, Math.floor(((r.ended_at ? new Date(r.ended_at).getTime() : Date.now()) - new Date(r.started_at).getTime()) / 1000));
  return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

export default function RunsPage() {
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilterState] = useState("all");

  useEffect(() => {
    const load = () => listRuns().then((d: any) => setRuns(Array.isArray(d) ? d : d.runs || [])).catch((e) => setError(e.message)).finally(() => setLoading(false));
    load();
    listMissions().then((ms: any[]) => setTitles(Object.fromEntries(ms.map((m) => [m.id, m.title])))).catch(() => {});
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, []);

  const sorted = useMemo(() => [...runs].sort((a, b) => (b.started_at || "").localeCompare(a.started_at || "")), [runs]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: runs.length };
    runs.forEach((r) => { c[r.status] = (c[r.status] || 0) + 1; });
    return c;
  }, [runs]);
  const shown = filter === "all" ? sorted : sorted.filter((r) => r.status === filter);
  const active = runs.find((r) => ["running", "planning"].includes(r.status));

  return (
    <Page wide>
      <PageHeader eyebrow="Runs" title="Runs"
        subtitle="Every run keeps its full record: the plan, every gate decision with a signed receipt, vision checks and the hash-chained audit trail."
        actions={active ? <Button variant="primary" href={`/runs/${active.id}`}>Watch the running mission</Button> : <Button variant="primary" href="/twin">Start a mission</Button>} />

      <Tabs className="mb-4" value={filter} onChange={setFilterState}
        tabs={["all", "running", "completed", "stopped", "failed"].map((f) => ({ id: f, label: f[0].toUpperCase() + f.slice(1), count: counts[f] || 0 }))} />

      {error && <div className="mb-3"><Notice tone="stop">{error}</Notice></div>}

      {loading ? <div className="text-sm text-mc-dim py-6">Loading runs…</div> : shown.length === 0 ? (
        <Panel><Empty title="No runs here yet">Start a mission from the live warehouse.</Empty></Panel>
      ) : (
        <Panel padded={false}>
          <div className="overflow-x-auto mc-scroll">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] uppercase tracking-wider text-mc-dim border-b border-mc-line">
                  <th className="text-left font-semibold px-4 py-2.5">Status</th>
                  <th className="text-left font-semibold px-2">Run</th>
                  <th className="text-left font-semibold px-2">Mission</th>
                  <th className="text-left font-semibold px-2">Started</th>
                  <th className="text-right font-semibold px-2">Duration</th>
                  <th className="px-4" />
                </tr>
              </thead>
              <tbody className="divide-y divide-mc-line">
                {shown.map((r) => (
                  <tr key={r.id} className="hover:bg-mc-raise/50">
                    <td className="px-4 py-2.5"><Verdict value={r.status} /></td>
                    <td className="px-2"><Link href={`/runs/${r.id}`} className="hover:underline"><Mono>{r.id}</Mono></Link></td>
                    <td className="px-2 text-mc-mute max-w-[320px] truncate">{titles[r.mission_id] || <Mono className="text-mc-dim">{r.mission_id}</Mono>}</td>
                    <td className="px-2 text-mc-dim text-xs tabular whitespace-nowrap">{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                    <td className="px-2 text-right tabular">{duration(r)}</td>
                    <td className="px-4 text-right"><Link href={`/runs/${r.id}`} className="text-xs text-mc-accent hover:underline whitespace-nowrap">Open →</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </Page>
  );
}
