"use client";
import { useEffect, useState } from 'react';
import { getRunPresentation } from '@/lib/api';
import { executionPresentation } from '@/lib/runPresentation';

export function useRunPresentation(runId: string) {
  const [value, setValue] = useState<any>(null);
  const [current, setCurrent] = useState(false);
  useEffect(() => {
    let live = true, timer: ReturnType<typeof setTimeout>;
    setValue(null); setCurrent(false);
    async function poll() {
      try { const v = await getRunPresentation(runId); if (live) { setValue(v); setCurrent(true); } }
      catch { if (live) setCurrent(false); }
      finally { if (live) timer = setTimeout(poll, 1800); }
    }
    if (runId) void poll();
    return () => { live = false; clearTimeout(timer); };
  }, [runId]);
  return { value, current };
}

export function RunProgress({ runId, telemetry, fresh, status }: { runId: string; telemetry: any; fresh: boolean; status: string }) {
  const { value, current } = useRunPresentation(runId);
  return <RunProgressView value={value} current={current && value?.run_id === runId} telemetry={telemetry} fresh={fresh} status={status} />;
}
export function RunProgressView({ value, current, telemetry, fresh, status }: { value: any; current: boolean; telemetry: any; fresh: boolean; status: string }) {
  const display = executionPresentation(current ? value : null, telemetry, fresh && current, status);
  return <section className="rounded-lg border border-mc-line bg-mc-panel p-3 my-3" aria-label="Recorded execution progress" role="status">
    <strong className={display.tone === 'stop' ? 'text-red-700' : 'text-mc-ink'}>{display.label}</strong>
    <p className="text-sm text-mc-mute mt-1">{display.detail}</p>
    <div className="text-xs text-mc-mute mt-2">Plan: {current && value?.plan ? `${value.plan.payload.plan?.model_used || value.plan.payload.source || 'recorded'}` : current ? 'Not yet recorded' : 'Checking'} · First Admission: {current && value?.first_admission ? 'Recorded' : current ? 'Not yet recorded' : 'Checking'}</div>
  </section>;
}
