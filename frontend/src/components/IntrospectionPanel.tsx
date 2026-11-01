"use client";

import React, { useEffect, useState } from "react";
import { getRunIntrospection, extractLessons, getAgentMemory, searchAgentMemory, getAgentMemoryStats } from "@/lib/api";

export function IntrospectionPanel({ runId }: { runId: string }) {
  const [data, setData] = useState<any>(null);
  const [memory, setMemory] = useState<any[]>([]);
  const [lessons, setLessons] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [lessonLoading, setLessonLoading] = useState(false);
  const [tab, setTab] = useState<"denials" | "replans" | "memory">("denials");
  const [memoryStats, setMemoryStats] = useState<any>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [intro, mem] = await Promise.all([
          getRunIntrospection(runId),
          getAgentMemory("learning").catch(() => []),
        ]);
        if (!cancelled) {
          setData(intro);
          setMemory(mem || []);
        }
        // Fetch memory stats in background
        try { if (!cancelled) setMemoryStats(await getAgentMemoryStats()); } catch (_) {}
      } catch (_) {}
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [runId]);

  async function onExtractLessons() {
    setLessonLoading(true);
    try {
      const result = await extractLessons(runId);
      setLessons(result.lessons || []);
      // Refresh memory
      const mem = await getAgentMemory("learning").catch(() => []);
      setMemory(mem || []);
    } catch (_) {}
    setLessonLoading(false);
  }

  if (loading) return <div className="text-xs text-mc-dim text-center py-3">Loading introspection…</div>;
  if (!data) return <div className="text-xs text-mc-dim text-center py-2">No introspection data</div>;

  return (
    <div className="space-y-3">
      {/* Summary badges */}
      <div className="flex flex-wrap gap-2">
        <span className="text-[10px] px-2 py-1 rounded-full bg-blue-500/15 text-blue-300 border border-blue-500/30">
          {data.total_decisions} decisions
        </span>
        <span className={`text-[10px] px-2 py-1 rounded-full border ${
          data.denial_count > 0 ? "bg-red-500/15 text-red-300 border-red-500/30" : "bg-green-500/15 text-green-300 border-green-500/30"
        }`}>
          {data.denial_count} denials
        </span>
        <span className={`text-[10px] px-2 py-1 rounded-full border ${
          data.total_replans > 0 ? "bg-amber-500/15 text-amber-300 border-amber-500/30" : "bg-mc-raise text-mc-mute border-mc-line2"
        }`}>
          {data.total_replans} replans
        </span>
        <span className="text-[10px] px-2 py-1 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/30">
          {data.memory_stats?.total_entries || 0} memories
        </span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1">
        {(["denials", "replans", "memory"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`text-[10px] font-medium px-2.5 py-1 rounded-lg transition ${
              tab === t ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30" : "text-mc-dim hover:text-mc-mute"
            }`}>
            {t === "denials" ? "Denial History" : t === "replans" ? "Replans" : "Agent Memory"}
          </button>
        ))}
      </div>

      {tab === "denials" && (
        <div className="max-h-48 overflow-y-auto space-y-1">
          {data.denial_history?.length === 0 ? (
            <div className="text-xs text-mc-dim text-center py-2">No denials recorded</div>
          ) : (
            data.denial_history?.map((d: any, i: number) => (
              <div key={i} className="flex items-start gap-2 text-[10px] bg-red-500/5 border border-red-500/10 rounded px-2 py-1.5">
                <span className="text-red-400 font-bold shrink-0">{d.decision}</span>
                <div className="flex-1">
                  <span className="text-mc-mute font-mono">{d.policy_hits?.join(", ")}</span>
                  {d.reasons?.[0] && <div className="text-mc-dim mt-0.5 truncate">{d.reasons[0]}</div>}
                </div>
                <span className="text-mc-dim font-mono shrink-0">{d.risk_score?.toFixed(2)}</span>
              </div>
            ))
          )}
        </div>
      )}

      {tab === "replans" && (
        <div className="max-h-48 overflow-y-auto space-y-1">
          {data.replans?.length === 0 ? (
            <div className="text-xs text-mc-dim text-center py-2">No replans triggered</div>
          ) : (
            data.replans?.map((r: any, i: number) => (
              <div key={i} className="text-[10px] bg-amber-500/5 border border-amber-500/10 rounded px-2 py-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-amber-400 font-bold">REPLAN</span>
                  <span className="text-mc-dim">{r.payload?.reason}</span>
                </div>
                {r.payload?.blocked_waypoint && (
                  <div className="text-mc-dim mt-0.5">
                    Blocked at ({r.payload.blocked_waypoint.x}, {r.payload.blocked_waypoint.y})
                    → {r.payload.new_plan_waypoints || "?"} new waypoints
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {tab === "memory" && (
        <div className="space-y-2">
          {/* Memory Stats */}
          {memoryStats && (
            <div className="flex flex-wrap gap-2 text-[10px]">
              {memoryStats.total_entries != null && (
                <span className="px-2 py-0.5 rounded bg-mc-raise text-mc-ink/85">{memoryStats.total_entries} entries</span>
              )}
              {memoryStats.categories && Object.entries(memoryStats.categories).map(([cat, count]) => (
                <span key={cat} className="px-2 py-0.5 rounded bg-mc-raise/50 text-mc-mute">{cat}: {String(count)}</span>
              ))}
            </div>
          )}

          {/* Memory Search */}
          <div className="flex gap-1">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={async (e) => {
                if (e.key === "Enter" && searchQuery.trim()) {
                  setSearchLoading(true);
                  try { setSearchResults(await searchAgentMemory(searchQuery)); } catch (_) { setSearchResults([]); }
                  setSearchLoading(false);
                }
              }}
              placeholder="Search agent memory..."
              className="flex-1 bg-mc-bg/60 border border-mc-line2 rounded px-2 py-1 text-[10px] text-white focus:outline-none focus:border-cyan-500 placeholder:text-mc-dim"
            />
            <button
              onClick={async () => {
                if (!searchQuery.trim()) return;
                setSearchLoading(true);
                try { setSearchResults(await searchAgentMemory(searchQuery)); } catch (_) { setSearchResults([]); }
                setSearchLoading(false);
              }}
              disabled={searchLoading || !searchQuery.trim()}
              className="text-[10px] px-2 py-1 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 hover:bg-cyan-500/30 disabled:opacity-50"
            >
              {searchLoading ? "..." : "🔍"}
            </button>
          </div>

          {searchResults !== null && (
            <div className="space-y-1">
              <div className="text-[10px] text-mc-dim">{searchResults.length} result{searchResults.length !== 1 ? "s" : ""}</div>
              {searchResults.map((r: any, i: number) => (
                <div key={i} className="text-[10px] bg-cyan-500/10 border border-cyan-500/20 rounded px-2 py-1">
                  <span className="text-cyan-400 font-semibold">{r.category || "memory"}</span>
                  <span className="text-mc-mute mx-1">•</span>
                  <span className="text-mc-ink/85">{r.content?.lesson || r.content || JSON.stringify(r).slice(0, 80)}</span>
                  {r.similarity != null && <span className="text-[9px] text-mc-dim ml-1">({(r.similarity * 100).toFixed(0)}%)</span>}
                </div>
              ))}
            </div>
          )}

          {/* Extract lessons button */}
          <button onClick={onExtractLessons} disabled={lessonLoading}
            className="w-full text-[10px] font-semibold px-3 py-1.5 rounded-lg border border-purple-500/30 bg-purple-500/10 text-purple-300 hover:bg-purple-500/20 transition disabled:opacity-50">
            {lessonLoading ? "Extracting…" : "🧠 Extract Lessons from This Run"}
          </button>

          {lessons.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] text-purple-400 font-semibold uppercase tracking-wider">New Lessons</div>
              {lessons.map((l, i) => (
                <div key={i} className="text-[10px] bg-purple-500/10 border border-purple-500/20 rounded px-2 py-1 text-purple-200">{l}</div>
              ))}
            </div>
          )}

          <div className="max-h-40 overflow-y-auto space-y-1">
            {memory.length === 0 ? (
              <div className="text-xs text-mc-dim text-center py-2">No learned memories yet</div>
            ) : (
              memory.map((m: any, i: number) => (
                <div key={i} className="text-[10px] bg-mc-raise/50 border border-mc-line2 rounded px-2 py-1">
                  <span className="text-cyan-400 font-semibold">{m.category}</span>
                  <span className="text-mc-mute mx-1">•</span>
                  <span className="text-mc-ink/85">{m.content?.lesson || JSON.stringify(m.content).slice(0, 80)}</span>
                </div>
              ))
            )}
          </div>

          {/* Memory context for LLM */}
          {data.memory_context && data.memory_context !== "No persistent memory entries." && (
            <details className="text-[10px]">
              <summary className="text-mc-dim cursor-pointer hover:text-mc-mute">LLM Memory Context</summary>
              <pre className="text-mc-mute bg-mc-bg/60 p-2 rounded mt-1 overflow-x-auto max-h-32 overflow-y-auto font-mono whitespace-pre-wrap">
                {data.memory_context}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
