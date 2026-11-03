"use client";

import React, { useCallback, useEffect, useState } from "react";
import { getAuthorityEvidence, getRouteLearning, runDrills } from "@/lib/api";
import { AuthorityPanel } from "@/components/AuthorityPanel";
import { LearningEvidence } from "@/components/LearningEvidence";
import { OperationalGraphPanel } from "@/components/OperationalGraphPanel";
import { RuntimeCapabilities } from '@/components/RuntimeCapabilities';
import { Button, Empty, KV, Mono, Notice, Page, PageHeader, Panel, Pill, Stat } from "@/components/ui";

type Drill = { drill: string; passed: boolean; detail: string; skipped?: boolean; checks?: { check: string; passed: boolean }[] };

const DRILL_LABEL: Record<string, string> = {
  bypass: "Command sent straight to the robot, no permit",
  tamper: "Valid permit reused for a different target",
  replay: "Used permit sent again",
  forged: "Permit signed with the wrong key",
  poison: "Forged record planted in learning memory",
  poisoning: "Corroboration, flooding, rogue-source quarantine and deletion detection (isolated memory)",
  injection: "Instructions hidden in outside site information",
  canary: "Planner given an instruction hidden in untrusted data",
  kill: "Robot kill switch: revoke, verify stop, refuse moves",
};

export default function AuthorityPage() {
  const [events, setEvents] = useState<any[]>([]);
  const [learning, setLearning] = useState<any>(null);
  const [drills, setDrills] = useState<{ passed: number; ran: number; all_passed: boolean; results: Drill[]; duration_ms: number } | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setEvents((await getAuthorityEvidence(60)).events.slice().reverse()); } catch { /* offline */ }
    try { setLearning(await getRouteLearning()); } catch { /* offline */ }
  }, []);
  useEffect(() => {
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);

  const go = async () => {
    setRunning(true); setErr(null);
    try { setDrills(await runDrills()); } catch (e: any) { setErr(e.message); }
    setRunning(false);
    load();
  };

  return (
    <Page>
      <PageHeader eyebrow="Built during the hackathon" title="Execution authority"
        subtitle="Inspect execution permissions, verified experience and connected mission evidence. Every move requires current controller admission, whether a model or fallback planner proposed it." />
      <RuntimeCapabilities />

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 space-y-4 min-w-0">
          <AuthorityPanel />
          <Panel id="route-learning" title="Learned routing" subtitle="NetworkX over the warehouse floor; only signed experience counts">
            {!learning ? <Empty title="Loading…" /> : (
              <>
                <KV k="Router" v={learning.last_route?.router || "—"} mono />
                <KV k="Cells with learned delay" v={learning.learned_cells} mono />
                <KV k="Quarantined records" v={learning.quarantined} mono />
                {learning.last_route?.learned_delay_s != null && <KV k="Expected delay on last route" v={`${learning.last_route.learned_delay_s} s`} mono />}
              </>
            )}
          </Panel>
        </div>

        <div className="lg:col-span-2 space-y-4 min-w-0">
          <OperationalGraphPanel />
          <LearningEvidence decisions={learning?.decisions} changes={learning?.lifecycle?.events} context={learning?.experience_context} security={learning} />
          <Panel id="security-drills" title="Security drills" subtitle="Real attacks against the live simulator, each with a pass/fail result"
            actions={<Button variant="primary" disabled={running} onClick={go}>{running ? "Running…" : "Run all drills"}</Button>}>
            {err && <Notice tone="stop">{err}</Notice>}
            {!drills ? <Empty title="No drills run yet">Runs only while no mission is active. The probe move targets the robot&apos;s own position, and everything is cleaned up afterwards.</Empty> : (
              <>
                <div className="grid grid-cols-3 gap-2 mb-3">
                  <Stat label="Passed" value={`${drills.passed}/${drills.ran}`} tone={drills.all_passed ? "ok" : "stop"} />
                  <Stat label="Result" value={drills.all_passed ? "All blocked" : "Check"} tone={drills.all_passed ? "ok" : "stop"} />
                  <Stat label="Took" value={`${(drills.duration_ms / 1000).toFixed(1)} s`} />
                </div>
                <div className="space-y-1.5">
                  {drills.results.map((d) => (
                    <div key={d.drill} className="flex items-start gap-3 rounded-lg border border-mc-line px-3 py-2">
                      <Pill tone={d.skipped ? "neutral" : d.passed ? "ok" : "stop"} dot>{d.skipped ? "SKIPPED" : d.passed ? "PASS" : "FAIL"}</Pill>
                      <div className="min-w-0">
                        <div className="text-sm text-mc-ink">{DRILL_LABEL[d.drill] || d.drill}</div>
                        <div className="text-xs text-mc-mute">{d.detail}</div>
                        {d.checks && <ul className="mt-2 space-y-1 text-xs">{d.checks.map(c => <li key={c.check} className={c.passed ? "text-emerald-300" : "text-red-300"}>{c.passed ? "PASS" : "FAIL"} · {c.check.replaceAll("_", " ")}</li>)}</ul>}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Panel>

          <Panel title="Dispatch and kill-switch events" subtitle="Most recent first">
            {events.length === 0 ? <Empty title="No events yet">Start a mission to see each permit used.</Empty> : (
              <div className="max-h-[420px] overflow-y-auto mc-scroll divide-y divide-mc-line/60">
                {events.map((e, i) => (
                  <div key={i} className="flex flex-wrap items-start justify-between gap-2 py-2 text-xs min-w-0">
                    <div className="flex flex-wrap items-center gap-2 min-w-0 flex-1 basis-48">
                      <Pill tone={e.kind.includes("kill") ? "stop" : e.kind.includes("unknown") ? "warn" : e.kind.includes("drill") ? "info" : "ok"}>{e.kind.replace(/_/g, " ")}</Pill>
                      <span className="font-mono text-xs text-mc-ink break-all min-w-0">{e.action_id || e.scope || ""}</span>
                    </div>
                    <span className="text-mc-dim tabular shrink-0">{new Date(e.timestamp * 1000).toLocaleTimeString()}</span>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </Page>
  );
}
