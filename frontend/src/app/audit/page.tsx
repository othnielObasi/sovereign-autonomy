"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { EvidenceNav } from "@/components/EvidenceNav";
import { getAllAudit, getMissionAudit } from "@/lib/api";
import type { MissionAuditEntry } from "@/lib/types";

const ACTION_BADGE: Record<string, { label: string; cls: string; icon: string }> = {
  CREATED:       { label: "Created",        cls: "bg-green-600 text-white",     icon: "➕" },
  UPDATED:       { label: "Updated",        cls: "bg-blue-600 text-white",      icon: "✏️" },
  STATUS_CHANGE: { label: "Status Change",  cls: "bg-yellow-600 text-white",    icon: "🔄" },
  DELETED:       { label: "Deleted",        cls: "bg-red-600 text-white",       icon: "🗑️" },
  REPLAYED:      { label: "Replayed",       cls: "bg-purple-600 text-white",    icon: "♻️" },
};

export default function AuditTrailPage() {
  const [entries, setEntries] = useState<MissionAuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterMission, setFilterMission] = useState<string>("");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  async function loadAudit() {
    setLoading(true);
    setError(null);
    try {
      if (filterMission.trim()) {
        setEntries(await getMissionAudit(filterMission.trim()));
      } else {
        setEntries(await getAllAudit(200));
      }
    } catch (e: any) {
      setError(e.message || "Failed to load audit trail");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadAudit(); }, []);

  function handleFilterSubmit(e: React.FormEvent) {
    e.preventDefault();
    loadAudit();
  }

  // Unique mission IDs for quick stats
  const uniqueMissions = new Set(entries.map((e) => e.mission_id));

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6 sm:py-8">
      <PageHeader eyebrow="Evidence" title="Audit trail"
        subtitle={`${entries.length} entries across ${uniqueMissions.size} mission${uniqueMissions.size !== 1 ? "s" : ""}. Mission changes, recorded and append-only.`} />
      <EvidenceNav />

      {/* Filter */}
      <form onSubmit={handleFilterSubmit} className="flex gap-3 mb-6">
        <input
          className="flex-1 bg-mc-panel border border-mc-line rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-cyan-500 placeholder-slate-500"
          placeholder="Filter by mission ID (e.g. mis_abc123)... leave empty for all"
          value={filterMission}
          onChange={(e) => setFilterMission(e.target.value)}
        />
        <button
          type="submit"
          className="bg-cyan-500 hover:bg-cyan-600 text-white text-sm font-semibold px-5 py-2 rounded-lg transition"
        >
          Filter
        </button>
        {filterMission && (
          <button
            type="button"
            onClick={() => { setFilterMission(""); setTimeout(loadAudit, 0); }}
            className="bg-mc-raise hover:bg-mc-line2 text-mc-ink/85 text-sm px-4 py-2 rounded-lg transition"
          >
            Clear
          </button>
        )}
      </form>

      {error && (
        <div className="bg-red-500/20 border border-red-500/50 rounded-xl p-4 mb-6 text-sm text-red-400">
          {error}
          <button onClick={() => setError(null)} className="ml-3 underline text-xs">dismiss</button>
        </div>
      )}

      {loading ? (
        <div className="text-center py-12 text-mc-mute">Loading audit trail...</div>
      ) : entries.length === 0 ? (
        <div className="text-center py-12 text-mc-mute">
          <div className="text-4xl mb-2">📋</div>
          <div>No audit entries found.</div>
        </div>
      ) : (
        <div className="relative">
          {/* Timeline line */}
          <div className="absolute left-5 top-0 bottom-0 w-0.5 bg-mc-raise" />

          <div className="space-y-4">
            {entries.map((entry) => {
              const badge = ACTION_BADGE[entry.action] || ACTION_BADGE.UPDATED;
              const isExpanded = expandedId === entry.id;
              const hasChanges =
                (entry.old_values && Object.keys(entry.old_values).length > 0) ||
                (entry.new_values && Object.keys(entry.new_values).length > 0);

              return (
                <div key={entry.id} className="relative pl-12">
                  {/* Timeline dot */}
                  <div className="absolute left-3.5 top-4 w-3 h-3 rounded-full bg-mc-line2 border-2 border-mc-line z-10" />

                  <div
                    className={`bg-mc-panel border rounded-xl p-4 transition cursor-pointer hover:border-mc-line2 ${
                      isExpanded ? "border-cyan-600" : "border-mc-line"
                    }`}
                    onClick={() => setExpandedId(isExpanded ? null : entry.id)}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className="text-sm">{badge.icon}</span>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${badge.cls}`}>
                            {badge.label}
                          </span>
                          <span className="font-mono text-xs text-mc-dim truncate">
                            {entry.mission_id}
                          </span>
                        </div>
                        {entry.details && (
                          <p className="text-sm text-mc-ink/85 mt-1">{entry.details}</p>
                        )}
                      </div>

                      <div className="text-right flex-shrink-0">
                        <div className="text-xs text-mc-mute">
                          {new Date(entry.ts).toLocaleString()}
                        </div>
                        <div className="text-[10px] text-mc-dim mt-0.5">
                          by {entry.actor}
                        </div>
                      </div>
                    </div>

                    {/* Expanded diff view */}
                    {isExpanded && hasChanges && (
                      <div className="mt-3 pt-3 border-t border-mc-line">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {entry.old_values && Object.keys(entry.old_values).length > 0 && (
                            <div>
                              <div className="text-[10px] font-bold text-red-400 uppercase tracking-wider mb-1">
                                Before
                              </div>
                              <pre className="bg-mc-bg rounded-lg p-3 text-xs text-red-300 overflow-x-auto">
                                {JSON.stringify(entry.old_values, null, 2)}
                              </pre>
                            </div>
                          )}
                          {entry.new_values && Object.keys(entry.new_values).length > 0 && (
                            <div>
                              <div className="text-[10px] font-bold text-green-400 uppercase tracking-wider mb-1">
                                After
                              </div>
                              <pre className="bg-mc-bg rounded-lg p-3 text-xs text-green-300 overflow-x-auto">
                                {JSON.stringify(entry.new_values, null, 2)}
                              </pre>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {isExpanded && !hasChanges && (
                      <div className="mt-3 pt-3 border-t border-mc-line text-xs text-mc-dim">
                        No value changes recorded for this entry.
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
