"use client";
import { useEffect, useState } from 'react';
import { getHealth, getAuthorityStatus, getLlmUsage } from '@/lib/api';
import { Page, PageHeader, Panel, KV, Button, Notice } from '@/components/ui';
import { RuntimeCapabilities } from '@/components/RuntimeCapabilities';
export default function OperationsPage() {
  const [health, setHealth] = useState<any>(null), [authority, setAuthority] = useState<any>(null), [usage, setUsage] = useState<any>(null);
  const [checked, setChecked] = useState(false);
  const availability = checked ? 'Unavailable' : 'Checking';
  useEffect(() => { let live = true; const load = async () => {
    const results = await Promise.allSettled([getHealth(), getAuthorityStatus(), getLlmUsage()]);
    if (!live) return;
    setHealth(results[0].status === 'fulfilled' ? results[0].value : null);
    setAuthority(results[1].status === 'fulfilled' ? results[1].value : null);
    setUsage(results[2].status === 'fulfilled' ? results[2].value : null); setChecked(true);
  }; void load(); const id = setInterval(load, 8000); return () => { live = false; clearInterval(id); }; }, []);
  return <Page><PageHeader title="Operations & recovery" subtitle="Check service readiness, understand continuity and find specialist operations. No recovery or restore runs automatically." />
    <RuntimeCapabilities />
    <div className="grid md:grid-cols-2 gap-4"><Panel title="Dependency readiness">
      <KV k="Database" v={health?.checks?.database || availability} /><KV k="Simulator" v={health?.checks?.simulator || availability} />
      <KV k="Permit enforcement" v={!authority ? availability : authority.enabled ? 'Configured' : 'Not configured'} />
      <KV k="Authority journal" v={!authority ? availability : authority.journal_intact ? 'Intact' : 'Investigate'} />
      <KV k="Active stop scopes" v={authority?.kill_locks?.length ?? availability} />
      <KV k="Recorded model calls" v={usage?.summary?.total_calls ?? availability} />
      <p className="text-xs text-mc-mute mt-3">Readiness does not establish safe movement. Each action still needs current checks and controller admission.</p>
    </Panel>
    <Panel title="Interrupted mission continuity" id="recovery" className="scroll-mt-24">
      <ol className="list-decimal pl-5 text-sm text-mc-mute space-y-2"><li>Restarted runs remain paused.</li><li>Inspect the mission, stop locks and recorded outcome.</li><li>Resume reconciles uncertain dispatches with the controller; it does not blindly replay them.</li><li>If evidence cannot settle the outcome, hold and investigate. Resume is explicit.</li></ol>
      <div className="mt-3"><Button href="/runs?inspect=chain">Choose a run to inspect</Button></div>
    </Panel>
    <Panel title="Signed backups — operator CLI">
      <p className="text-sm text-mc-mute mb-3">Run from the configured backend environment. Backups include authority and learning checkpoints. Verification must pass before restore. Keep signing keys and secrets separately.</p>
      <pre className="text-xs bg-mc-raise p-3 rounded overflow-x-auto">{'python -m app.ops.backup create --out backups/\npython -m app.ops.backup verify backups/<stamp>'}</pre>
      <Notice tone="warn">Restore is a documented offline operation requiring the backend to be stopped. This workspace does not trigger it.</Notice>
      <a className="text-sm text-mc-accent underline" href="https://github.com/othnielObasi/sovereign-autonomy/blob/main/docs/RUNBOOK.md">Open the recovery runbook ↗</a>
    </Panel>
    <Panel title="Specialist testing & observability">
      <p className="text-sm text-mc-mute">The scenario lab and security drills have workspace controls. Adversarial/holdout validation, Prometheus metrics and external tracing have service/configuration workflows.</p>
      <ul className="text-sm text-mc-accent underline space-y-2 mt-3"><li><a href="/api/adversarial/validate">Run adversarial and holdout validation (JSON)</a></li><li><a href="/api/metrics">Prometheus metrics</a></li><li><a href="/api/docs">API reference (when enabled)</a></li><li><a href="https://github.com/othnielObasi/sovereign-autonomy/blob/main/docs/TRACEABILITY.md">Implementation and validation scope</a></li></ul>
      <p className="text-xs text-mc-mute mt-3">External tracing requires configuration. Single-site recovery is implemented; multi-site failover is outside scope.</p>
    </Panel></div>
  </Page>;
}
