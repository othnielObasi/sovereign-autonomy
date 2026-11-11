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
      Planning: <strong>{health.planner_provider === 'muse' ? 'Meta Muse Spark' : health.planner_provider === 'fallback' ? 'built-in fallback planner' : health.planner_provider}</strong>
      {' · '}Camera vision: {health.vision_provider === 'sam' ? 'Meta SAM 3.1' : health.vision_provider || 'off'}{' · '}Voice stop: {health.voice_enabled ? 'on' : 'off'}.
      {' '}Each mission records which planner it actually used.
    </>}
  </p>;
}
