"use client";
import { createContext, useContext, useEffect, useState } from 'react';
import { getHealth } from '@/lib/api';
const Context = createContext<any>(null);
export const useRuntimeCapabilities = () => useContext(Context);
export function RuntimeCapabilitiesProvider({ children }: { children: React.ReactNode }) {
  const [value, setValue] = useState<any>(null);
  useEffect(() => {
    let active = true;
    const load = () => getHealth().then(v => { if (active) setValue(v); }).catch(() => { if (active) setValue(null); });
    void load(); const id = setInterval(load, 8000);
    return () => { active = false; clearInterval(id); };
  }, []);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function RuntimeCapabilities() {
  const health = useRuntimeCapabilities();
  return <p className="text-sm text-mc-mute rounded-lg border border-mc-line p-3 my-3" role="status">
    {!health ? 'Checking runtime capabilities…' : <>
      Planner default: <strong>{health.planner_provider === 'fallback' ? 'deterministic fallback' : health.planner_provider}</strong>
      {' · '}Vision: {health.vision_provider || 'not configured'}{' · '}Voice: {health.voice_enabled ? 'configured' : 'not configured'}.
      {' '}Each run records the planner actually used. Configured services still require successful requests.
    </>}
  </p>;
}
