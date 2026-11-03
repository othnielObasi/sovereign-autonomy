# Landing and workspace presentation fixes

Implemented against the twelve findings in [the presentation audit](PRESENTATION_CAPABILITY_AUDIT.md). This changes presentation, discoverability and access to existing workflows. It does not add physical robot skills or integrate external ACE/Agentic Kernel packages.

## What changed

| Finding | Implemented correction |
| --- | --- |
| A01: approval presented as execution | Mission Control and run details share an evidence-based execution presentation: held/review, admission, refusal, acknowledgment, unknown outcome, observed movement, pause and historical outcome. Movement requires fresh telemetry with speed and a target matching the acknowledged action. A running run or approved policy alone cannot establish movement. |
| A02: progress lost after 80 events | Read-only `GET /runs/{id}/presentation` returns the latest stored plan, decision, authority and execution records plus the first actual admission. These facts are independent of the rolling activity window. |
| A03: wrong facility bounds | Policy cards read effective parameters from the same active rules as the gate, including site bounds, speed, confidence, proximity, clearance and review thresholds. Threshold-dependent trigger descriptions no longer repeat catalog defaults. |
| A04: invalid or overstated mission presets | Navigation examples derive from current simulator destinations. Creating or starting a preset requires a valid current destination. Default instructions describe navigation rather than sample transfer, picking or manipulation. |
| A05: conflicting model/voice claims | A shared runtime capability display distinguishes configured defaults from the source recorded for an individual run. Unconfigured voice controls are disabled. Recorded planner context and the latest fallback/empty hold replace stale model plans. |
| A06: authority page overflow | Dispatch identifiers wrap, grid children may shrink, and event rows wrap timestamps. Populated long-ID fixtures and current authority data fit a 390 px viewport. |
| A07: capability links reach wrong screens | All 22 public cards link to relevant workspace tools. A run picker preserves the intended inspection; links open the correct learning, site/vision, analysis, memory or chain tab. Facility/scenario, authority, graph, learning security, rules and recovery have explicit destinations. |
| A08: narrow landing narrative | The original cinematic visual identity remains. An outcome-led headline and mission lifecycle explain assigning, planning, coordinating, executing, adapting, retrieving experience and explaining outcomes. One repetitive permit explanation now describes cooperating platform components. |
| A09: missing architecture and graph story | Landing, guide and capability hub explain the project's agentic runtime, NetworkX routing, signed memory and optional Memgraph retrieval. Graph history is advisory, not movement permission. External ACE/kernel integrations are explicitly outside the implementation. |
| A10: governed rules inaccessible | Rules in force now includes proposal creation, replay evaluation, bounded benchmarks, separate approval, rejection, activation and rollback controls. Public workspaces are read-only; permissions and proposal state constrain controls. Backend role, separate-approver, benchmark and between-runs checks remain authoritative. No stages run automatically. |
| A11: learning, investigation and recovery scattered | A new capability hub organizes existing tools around operator problems. Operations and recovery provides service readiness, continuity instructions, signed-backup CLI commands, runbook, validation and observability access. Mission audit copy distinguishes mission edits from run execution evidence. |
| A12: old proof dominates / scope overstatement | New recorded Meta/Tavily proof supplements the original fallback story: 88 verified audit events and 25 verified signed receipts for a separate completed simulator run. Original 413-event/37-gap disclosures remain intact. Benchmark copy calls contacts simulated and states the false-block/time tradeoff. |

## Validation

- Production frontend build passed, including type checking and static generation.
- Full backend suite: **513 passed, 4 skipped**. The four new presentation tests cover old milestones beyond the rolling window, newest fallback holds, missing/read-only endpoints and effective policy parameters. Those tests also passed again after tightening admission-event matching.
- **15 execution presentation checks** cover approval without admission, refusals despite approval, unacknowledged/unknown outcomes, stale telemetry, mismatched targets, stopped motion, pauses, completed history and operator review.
- Existing public-page regression: **13 check groups passed**. This verifies the five archived mission moments against source evidence, disclosure retention, 22 capabilities, lifecycle/filter/search/keyboard interactions, assets, links, reduced motion and 390/768/1024/1440 px layouts.
- The isolated workspace browser test passed **28 checks**, covering current facility presets/bounds, consistent availability, actual short navigation startup, memory inspection, refusal presentation, saved graph provenance, scenario deep links, staged proposal creation/rejection, public read-only controls and eight mobile routes. See its final [machine-readable results](validation/2026-11-03-presentation-fixes/checks.json).
- [Screenshots and public regression results](validation/2026-11-03-presentation-fixes/) distinguish live local services from labelled browser fixtures. The long-ID and refusal cases use response fixtures; they do not claim a newly induced physical/simulator hazard response.
- Changed artifacts were checked against configured backend secret values; no matches were found. No paid model calls were required for this regression pass.

The test mission and rejected rule proposal belong to the key-free, isolated preview on **19310**, with backend **18081** and simulator **18091**. Port **19300** and its existing mission were not stopped, restarted or modified. Restarting the normal application to load these changes remains a deployment action; the separate preview shows the new interface immediately.

## Reproduce

From the repository root in PowerShell:

```powershell
$env:NEXT_DIST_DIR='.next-presentation-final'
$env:BACKEND_URL='http://127.0.0.1:18081'
npm --prefix frontend run build

$env:BROWSER_FRONTEND_PORT='19310'
$env:BROWSER_BACKEND_PORT='18081'
$env:BROWSER_SIM_PORT='18091'
$env:BROWSER_NEXT_DIST_DIR='.next-presentation-final'
$env:BROWSER_SITE_LAYOUT='pharma'
.\.venv\Scripts\python.exe -X utf8 scripts/browser_validation_stack.py
```

Wait for the launcher to report readiness. In another shell:

```powershell
node scripts/test_execution_presentation.cjs
node scripts/verify_presentation_fixes.cjs
$env:PUBLIC_BASE_URL='http://127.0.0.1:19310'
$env:BROWSER_EVIDENCE_DIR='docs/validation/2026-11-03-presentation-fixes/public-regression'
node tests/public-pages.browser.cjs
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -X utf8 -m pytest backend/tests -q
```

The workspace verifier refuses other ports. It creates a short test mission and a proposal which it rejects; it does not activate rules. Stop only this preview by creating `backend/data/browser-validation/ports-19310/stop`. Do not build into a distribution directory while its Next server is serving it.

## Practical limits

Configured services can still fail individual requests. Readiness is not a movement guarantee. Recovery restore remains an explicit offline CLI operation, not a browser button. The demonstration remains simulated navigation/STOP/WAIT, bounded shared-space coordination and single-site recovery; it does not establish manipulation, balance control, a general fleet scheduler, multisite failover or hardware safety certification.
