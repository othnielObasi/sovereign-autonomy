"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { EvidenceNav } from "@/components/EvidenceNav";
import {
  listRuns,
  getComplianceReport,
  getComplianceFrameworks,
  verifyAuditChain,
} from "@/lib/api";

type Framework = { id: string; name: string; description: string };

type AuditEntry = {
  timestamp: string;
  decision_id: string;
  action_type: string;
  approved: boolean;
  risk_score: number;
  violations: { policy_id: string; severity: string }[];
  hash: string;
  previous_hash: string;
};

type ComplianceMetrics = {
  total_decisions: number;
  approved: number;
  denied: number;
  approval_rate: number;
  avg_risk_score: number;
  max_risk_score: number;
  violations_by_policy: Record<string, number>;
  critical_violations: number;
};

type ComplianceReport = {
  report_id: string;
  generated_at: string;
  run_id: string;
  framework?: string;
  period_start: string;
  period_end: string;
  metrics: ComplianceMetrics;
  audit_entries: AuditEntry[];
  chain_valid: boolean;
};

type RunInfo = {
  id: string;
  mission_id: string;
  status: string;
  started_at: string;
  ended_at: string | null;
};

type VerifyResult = {
  run_id: string;
  chain_valid: boolean;
  total_entries: number;
  first_hash: string;
  last_hash: string;
  verified_at: string;
};

export default function CompliancePage() {
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [frameworks, setFrameworks] = useState<Framework[]>([]);
  const [selectedRun, setSelectedRun] = useState<string>("");
  const [selectedFramework, setSelectedFramework] = useState("ISO_42001");
  const [report, setReport] = useState<ComplianceReport | null>(null);
  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showEntries, setShowEntries] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [r, f] = await Promise.all([listRuns(), getComplianceFrameworks()]);
        setRuns(r);
        setFrameworks(f.frameworks || []);
        if (r.length > 0) setSelectedRun(r[0].id);
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, []);

  async function handleGenerate() {
    if (!selectedRun) return;
    setLoading(true);
    setError(null);
    setReport(null);
    setVerify(null);
    try {
      const [rpt, ver] = await Promise.all([
        getComplianceReport(selectedRun, selectedFramework),
        verifyAuditChain(selectedRun),
      ]);
      setReport(rpt);
      setVerify(ver);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const fw = frameworks.find((f) => f.id === selectedFramework);

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6 sm:py-8">
      <PageHeader eyebrow="Evidence" title="Compliance reports"
        subtitle="A run's decisions mapped to ISO/IEC 42001, the EU AI Act and the NIST AI RMF, with hash-chain verification." />
      <EvidenceNav />

      {/* Controls */}
      <div className="bg-mc-panel/60 border border-mc-line rounded-xl p-5 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Run selector */}
          <div>
            <label className="block text-xs text-mc-mute mb-1 font-medium uppercase tracking-wider">
              Run
            </label>
            <select
              value={selectedRun}
              onChange={(e) => setSelectedRun(e.target.value)}
              className="w-full bg-mc-raise border border-mc-line2 rounded-lg px-3 py-2 text-sm focus:ring-cyan-500 focus:border-cyan-500"
            >
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.id} &mdash; {r.status}
                </option>
              ))}
            </select>
          </div>

          {/* Framework selector */}
          <div>
            <label className="block text-xs text-mc-mute mb-1 font-medium uppercase tracking-wider">
              Framework
            </label>
            <select
              value={selectedFramework}
              onChange={(e) => setSelectedFramework(e.target.value)}
              className="w-full bg-mc-raise border border-mc-line2 rounded-lg px-3 py-2 text-sm focus:ring-cyan-500 focus:border-cyan-500"
            >
              {frameworks.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
            {fw && <p className="text-xs text-mc-dim mt-1">{fw.description}</p>}
          </div>

          {/* Generate button */}
          <div className="flex items-end">
            <button
              onClick={handleGenerate}
              disabled={loading || !selectedRun}
              className="w-full bg-cyan-600 hover:bg-cyan-500 disabled:bg-mc-line2 text-white font-medium py-2 px-4 rounded-lg transition-colors"
            >
              {loading ? "Generating..." : "Generate Report"}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/20 border border-red-500/40 text-red-300 rounded-lg p-3 mb-6 text-sm">
          {error}
        </div>
      )}

      {/* Report */}
      {report && (
        <>
          {/* Chain Verification Banner */}
          {verify && (
            <div
              className={`rounded-xl p-4 mb-6 border ${
                verify.chain_valid
                  ? "bg-green-500/10 border-green-500/30"
                  : "bg-red-500/10 border-red-500/30"
              }`}
            >
              <div className="flex items-center gap-3">
                <div
                  className={`w-10 h-10 rounded-full flex items-center justify-center text-lg ${
                    verify.chain_valid ? "bg-green-500/20" : "bg-red-500/20"
                  }`}
                >
                  {verify.chain_valid ? "✓" : "✗"}
                </div>
                <div>
                  <div className="font-semibold">
                    {verify.chain_valid
                      ? "SHA-256 Hash Chain Verified"
                      : "Hash Chain Integrity Failure"}
                  </div>
                  <div className="text-xs text-mc-mute">
                    {verify.total_entries} entries &middot; Verified at{" "}
                    {new Date(verify.verified_at).toLocaleString()}
                  </div>
                </div>
                <div className="ml-auto text-right text-xs text-mc-dim font-mono hidden md:block">
                  <div>First: {verify.first_hash}</div>
                  <div>Last: {verify.last_hash}</div>
                </div>
              </div>
            </div>
          )}

          {/* Report Header */}
          <div className="bg-mc-panel/60 border border-mc-line rounded-xl p-5 mb-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-bold">
                  {fw?.name || selectedFramework} Compliance Report
                </h2>
                <p className="text-xs text-mc-mute font-mono mt-1">
                  Report ID: {report.report_id}
                </p>
              </div>
              <span className="text-xs text-mc-dim">
                Generated {new Date(report.generated_at).toLocaleString()}
              </span>
            </div>

            {/* Metrics Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard
                label="Total Decisions"
                value={report.metrics.total_decisions}
                sub="Actions evaluated"
              />
              <MetricCard
                label="Approved"
                value={report.metrics.approved}
                sub={`${(report.metrics.approval_rate * 100).toFixed(1)}% rate`}
                color="text-green-400"
              />
              <MetricCard
                label="Denied / Modified"
                value={report.metrics.denied}
                sub="Unsafe actions blocked"
                color="text-red-400"
              />
              <MetricCard
                label="Critical Violations"
                value={report.metrics.critical_violations}
                sub={`Max risk: ${report.metrics.max_risk_score.toFixed(2)}`}
                color={report.metrics.critical_violations > 0 ? "text-red-400" : "text-green-400"}
              />
            </div>
          </div>

          {/* Policy Violations Breakdown */}
          {Object.keys(report.metrics.violations_by_policy).length > 0 && (
            <div className="bg-mc-panel/60 border border-mc-line rounded-xl p-5 mb-6">
              <h3 className="text-sm font-semibold text-mc-ink/85 mb-3 uppercase tracking-wider">
                Policy Violations Breakdown
              </h3>
              <div className="space-y-2">
                {Object.entries(report.metrics.violations_by_policy).map(([pid, count]) => (
                  <div
                    key={pid}
                    className="flex items-center justify-between bg-mc-raise/50 px-4 py-2 rounded-lg"
                  >
                    <span className="text-sm font-mono text-yellow-300">{pid}</span>
                    <span className="text-sm text-mc-ink/85">
                      {count} violation{count !== 1 ? "s" : ""}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Audit Entries (collapsible) */}
          <div className="bg-mc-panel/60 border border-mc-line rounded-xl p-5">
            <button
              onClick={() => setShowEntries(!showEntries)}
              className="flex items-center justify-between w-full"
            >
              <h3 className="text-sm font-semibold text-mc-ink/85 uppercase tracking-wider">
                Audit Hash Chain ({report.audit_entries.length} entries)
              </h3>
              <span className="text-mc-mute text-sm">
                {showEntries ? "▲ Collapse" : "▼ Expand"}
              </span>
            </button>

            {showEntries && (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-mc-mute border-b border-mc-line">
                      <th className="pb-2 pr-3">#</th>
                      <th className="pb-2 pr-3">Timestamp</th>
                      <th className="pb-2 pr-3">Action</th>
                      <th className="pb-2 pr-3">Decision</th>
                      <th className="pb-2 pr-3">Risk</th>
                      <th className="pb-2 pr-3">Hash (SHA-256)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.audit_entries.slice(0, 50).map((entry, i) => (
                      <tr
                        key={entry.decision_id}
                        className="border-b border-mc-line/50 hover:bg-mc-raise/30"
                      >
                        <td className="py-1.5 pr-3 text-mc-dim">{i + 1}</td>
                        <td className="py-1.5 pr-3 text-mc-ink/85">
                          {new Date(entry.timestamp).toLocaleTimeString()}
                        </td>
                        <td className="py-1.5 pr-3 font-mono">{entry.action_type}</td>
                        <td className="py-1.5 pr-3">
                          <span
                            className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                              entry.approved
                                ? "bg-green-500/20 text-green-400"
                                : "bg-red-500/20 text-red-400"
                            }`}
                          >
                            {entry.approved ? "APPROVED" : "DENIED"}
                          </span>
                        </td>
                        <td className="py-1.5 pr-3">
                          <span
                            className={
                              entry.risk_score > 0.7
                                ? "text-red-400"
                                : entry.risk_score > 0.3
                                ? "text-yellow-400"
                                : "text-green-400"
                            }
                          >
                            {entry.risk_score.toFixed(2)}
                          </span>
                        </td>
                        <td className="py-1.5 font-mono text-mc-dim max-w-[180px] truncate">
                          {entry.hash.slice(0, 16)}...
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {report.audit_entries.length > 50 && (
                  <p className="text-xs text-mc-dim mt-2">
                    Showing first 50 of {report.audit_entries.length} entries
                  </p>
                )}
              </div>
            )}
          </div>
        </>
      )}

      {/* Empty state */}
      {!report && !loading && !error && (
        <div className="text-center py-16 text-mc-dim">
          <div className="text-4xl mb-3">📋</div>
          <p className="text-lg font-medium">Select a run and generate a compliance report</p>
          <p className="text-sm mt-1">
            Reports include SHA-256 hash chain verification, policy violation analysis,
            and framework alignment (ISO 42001, EU AI Act, NIST AI RMF).
          </p>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  color = "text-white",
}: {
  label: string;
  value: number;
  sub: string;
  color?: string;
}) {
  const bgMap: Record<string, string> = {
    "text-green-400": "bg-green-500/10 border-green-500/20",
    "text-red-400": "bg-red-500/10 border-red-500/20",
    "text-white": "bg-mc-raise/40 border-mc-line",
  };
  const bg = bgMap[color] || bgMap["text-white"];
  return (
    <div className={`rounded-xl p-5 border ${bg}`}>
      <div className="text-xs text-mc-mute uppercase tracking-wider font-medium">{label}</div>
      <div className={`text-4xl font-bold mt-2 ${color}`}>{value}</div>
      <div className="text-sm text-mc-dim mt-1">{sub}</div>
    </div>
  );
}
