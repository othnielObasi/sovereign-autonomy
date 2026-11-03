# Landing page and workspace: capability and pain-point audit

Audited 3 November 2026 against the current repository and the isolated local
preview at `http://127.0.0.1:19300`. This is an audit of communication,
discoverability, scope and operational feedback, not a new certification of every
backend capability. No product behavior or public-page copy was changed.

## Main finding

The project implements a broader autonomy platform than its main presentation
communicates. All 22 original capability areas have cards in the public guide,
and the landing page introduces five groups. The workspace has substantial
mission, intervention, learning, graph and evidence functionality. However,
the dominant story remains **plans → safety checks → movement permits**.

Operators and evaluators must piece together planning, coordination, adaptation,
memory, recovery and investigation across separate screens. Some feature links
do not reach the relevant feature, and a few status messages confuse policy
approval with admitted execution. This creates both an underselling problem and
an operational understanding problem.

Recommended product statement:

> Sovereign Autonomy turns instructions into controlled, adaptive robot missions,
> bringing planning, coordination, operational memory and human oversight into
> one workspace. The current implementation demonstrates navigation in simulation.

## Scope and evidence

- Reviewed the [capability inventory](CAPABILITY_AUDIT.md), implementation,
  traceability, public HTML, workspace routes and component/API wiring.
- Navigated 11 rendered pages: `/`, `/how-it-works`, `/mission-control`,
  `/missions`, `/runs`, `/authority`, `/policies`, `/evidence`, `/audit`,
  `/compliance`, and the latest run detail page.
- Saved visible versus collapsed text, headings, links and controls, plus page
  screenshots and read-only runtime metadata in
  [the audit evidence](validation/2026-11-03-presentation-audit/).
- Desktop: no page JavaScript errors and no document overflow on those 11 views.
  At 390 px, landing and Mission Control fit; populated authority event rows
  caused horizontal overflow on `/authority`.
- The audited preview intentionally has model/vision/voice integrations disabled
  and uses fallback planning. Memgraph is connected; Tavily reports offline.
  This does not establish the configuration of another deployment or the normal
  backend env file.
- An existing run, `run_c1abee3b765b`, was active during inspection. It was not
  created, paused, stopped, resumed or modified by this audit. The only non-GET
  browser request recorded was the development authentication-token request.
  No credentials or token response bodies are retained.

Runtime observations are snapshots, not synchronized samples of every screen.
The contradictory execution finding is also supported by the component logic
and recorded refusal responses, rather than relying on a visual timing race.

## Findings, highest priority first

### A01 — P1: policy approval is presented as successful execution

**Pain point:** an operator needs to know whether the robot is moving, held,
refused, awaiting review or making no progress.

Mission Control displayed **Route execution in progress**, while its decision
trail contained repeated `permit_refused / trajectory_obstacle_clearance`.
The run detail page displayed **The robot is following the approved plan** and
**Execution: Within Bounds**. Runtime evidence records `EXECUTION.result.ok=false`,
`rejected=true`, `execution_unverified` and stagnation for this active run.

This is a presentation defect; the observation shows the authority refusing the
move, not a bypass of the execution controls. The UI derives the execution badge
from the policy state and the autonomous banner from run status. It does not
reconcile those labels with the latest authority/controller outcome.

**Fix:** use distinct states for proposal, policy verdict, permit/admission,
controller acknowledgment and observed progress. Show a refusal reason and the
next permitted operator action. Do not infer movement from `running` or
`APPROVED` alone. Keep stop controls immediately available.

Sources: `frontend/src/app/runs/[runId]/page.tsx` around lines 575–598, 706–717
and 855–870; `frontend/src/app/mission-control/page.tsx` around line 159;
`runtime.json` and the run-page snapshot in the evidence directory.

### A02 — P1: the rolling event window makes prior progress disappear

**Pain point:** operators need a stable account of what has already happened.

Mission Control fetches only the latest 80 events. Its Plan and Permit summary
then uses `events.some(...)` to show either **Route prepared** / **Controller
admission recorded**, or **Waiting for a mission** / **No move admitted yet**.
The latter messages were visible during an existing running mission with a
recorded plan and earlier admitted moves. Older evidence had left that window.

**Fix:** obtain stable run-level milestones separately from recent activity.
If only a window is available, say **Not in the recent event window**, not that
the event never happened. Include the relevant run and source event IDs.

Sources: `frontend/src/app/mission-control/page.tsx` around lines 90 and 161.

### A03 — P1: the policy display shows different bounds from the facility

**Pain point:** an operator must understand the actual operating boundary.

The pharma world reports x=0–36, y=0–26. `/policies` and its rendered policy card
display x=0–40, y=0–25 from the static catalog. This audit does not establish an
incorrect backend geofence evaluation; it establishes an incorrect or insufficiently
labeled policy display relative to the current facility.

**Fix:** distinguish descriptive catalog defaults from effective, site-specific
rules. Show the active site/map identity and authoritative current values.

Sources: `backend/app/api/routes_governance.py:list_policies`,
`frontend/src/app/policies/page.tsx`, `runtime.json`.

### A04 — P1: mission examples imply physical actions that are not implemented

**Pain point:** users must know what they can actually ask the system to do.

`/missions` offers **Pick items from rack A-04**, **Restock rack A-08** and
**Deliver pallet to dock B-03**. These are old warehouse examples; the current
facility exposes C-01/Q-01/R-01/F-01/P-01/G-01 destinations. The platform currently
supports MOVE_TO, STOP and WAIT, without loading, picking or restocking actuators.
Mission Control also defaults to **Transfer a sample...**, which needs a clear
navigation-only interpretation.

**Fix:** derive navigation examples from the current facility and use language
such as **Navigate the carrier to Quality lab**. Clearly separate a navigation
objective from hypothetical material-handling operations. Preserve instructions,
assignment, draft and execution functions.

Sources: `frontend/src/app/missions/page.tsx` around lines 20–25 and 100–110;
`frontend/src/app/mission-control/page.tsx` around lines 127 and 159;
[current action scope](CAPABILITY_AUDIT.md).

### A05 — P1: configuration and model provenance are inconsistent between screens

**Pain point:** users must distinguish AI-backed operation, fallback behavior and
unavailable capabilities.

Mission Control correctly says **Deterministic planner** and **Vision not
configured** in this preview. Other pages assert **Muse Spark plans the route**
or **Meta's models plan and perceive** without that qualification. The shared
AuthorityPanel offers an enabled Voice stop button while health reports
`voice_enabled=false`; Mission Control correctly disables its voice control.

**Fix:** use shared capability-availability/provenance state. Distinguish
implemented, configured, active for this run and last successfully checked.
Disable unavailable actions with a reason. Preserve access to ordinary stop.

Sources: `frontend/src/app/missions/page.tsx:95`,
`frontend/src/app/authority/page.tsx:50`,
`frontend/src/components/AuthorityPanel.tsx`, `runtime.json`.

### A06 — P1: populated authority events break phone layout

**Pain point:** operators need readable controls and evidence on mobile.

At a 390 px viewport, `/authority` reached approximately 647 px document width
with the current action IDs and timestamps. The dispatch/kill-event rows are
the overflowing elements. The graph itself has a responsive layout; earlier
graph tests with less populated event history did not expose this page-level case.

**Fix:** allow the event row and its grid ancestors to shrink/wrap, and contain
long identifiers. Test with populated dispatch history, not only empty or small
fixtures. Preserve full IDs through an accessible inspection affordance.

Sources: `frontend/src/app/authority/page.tsx` around line 97;
`mobile.json` and `authority-mobile.png` in the evidence directory.

### A07 — P1: capability links often stop before the relevant feature

**Pain point:** a visitor who understands a capability should be able to find it.

- **Site intelligence → `/authority`**: the actual Tavily/bulletin interface is
  the run page's **Site & vision** tab, not the authority page.
- **Persistent learning → `/evidence`**: this opens safety benchmarks, not the
  relevant route memory, planner lessons or memory search.
- **Agentic planning → `/mission-control`**: no direct route to tool-call evidence
  or the run's manual reasoning workflow is identified.
- **Optimization / Analysis / Task fidelity → `/runs`**: the list provides no
  explanation of which run tab/panel to open next.
- **Recovery → `/runs`**: a list is not a recovery or checkpoint explanation.

These URLs generally return pages successfully; that is weaker than reaching
the advertised workflow. Perception and Fleet coordination currently fall back
to the generic Mission Control destination in the guide mapping.

**Fix:** capability-to-feature deep links, contextual empty states and a visible
next step when a run must first be selected. Retain specialist screens.

Sources: public guide `WORKSPACES` mapping; run detail tabs; `RunLearningPanel`,
`IntrospectionPanel`, `SiteIntelPanel` and `OperationalGraphPanel`.

### A08 — P2: the landing story gives permissions more space than the full mission

**Pain point:** visitors need to understand what they can accomplish and why it
is difficult today.

The hero's supporting paragraph already mentions planning, fleet coordination
and learning. Five capability groups are present. Those are strengths.
However, the generic **Intelligence that acts. Autonomy you can trust.** headline,
the five-moment stop/replan story, and two successive permit explanations
(**A plan proposes...** and **The AI proposes...**) emphasize one part of the system.
There is no equally concrete account of mission continuity, relevant memory
retrieval, coordination constraints or operational investigation.

**Fix:** preserve the restored visual identity, but lead with an operator outcome
and explicit pain points. Use one connected mission journey:
**Assign → Plan → Coordinate → Execute → Adapt → Retrieve experience → Explain**.
Give the independent authority one strong explanatory section and connect it to
that wider journey. Keep simulation and implementation limits visible.

Sources: `frontend/public/landing/index.html`; landing snapshot in `inventory.json`.

### A09 — P2: the architecture and Memgraph's role are missing from the public story

**Pain point:** technical evaluators need to understand how intelligence,
execution state, memory and evidence cooperate.

The guide has all 22 original cards and a nine-stage journey, but it does not
explain the newly integrated knowledge graph or distinguish route calculation,
signed experience storage, graph retrieval and the execution runtime. The new
graph is useful and inspectable under Trust & security, yet absent from the
public capability explanation and navigation language.

**Fix:** show one architecture-to-outcome map: agentic planning, the project's
own autonomy runtime, NetworkX routes, verified operational memory, optional
Memgraph relationships, governance and operator oversight. Place Memgraph under
learning/analysis/evidence instead of mechanically inventing a 23rd top-level
capability. Brand names belong in a technical layer; plain-language benefits
should explain the first view. Do not claim external ACE or Agentic Kernel
integration: the current project implements its own mechanisms.

Sources: public guide, `backend/app/autonomy/`, `agentic_planner.py`,
`muse_planner.py`, [Memgraph implementation](MEMGRAPH.md).

### A10 — P2: rule lifecycle is implemented in the backend but not offered as a full UI workflow

**Pain point:** reviewers need controlled ways to propose, evaluate, approve,
activate and roll back operating rules.

The guide describes that workflow. The Rules in force tab displays parameters,
history and a process explanation, with an unconditional **Read-only on the
public demo** notice. It does not expose the complete mutation workflow, even
though the audited preview is not configured as a public demo. This is a UI
coverage gap; it is not evidence that the backend lifecycle is absent, nor proof
of a regression introduced by the redesign.

**Fix:** explicitly label API-only or public-read-only paths. For an authorized
operator deployment, expose the actual staged workflow with role checks and
evidence, or provide clear documented access to it. Do not invent approval steps
or activate rules during a presentation audit.

Sources: `frontend/src/app/policies/page.tsx:95–167`, `routes_policy_proposals.py`.

### A11 — P2: learning, analysis and recovery require too much prior knowledge

**Pain point:** users need to answer “Why are missions failing?”, “What was
learned?”, “What history informed this plan?” and “How do we continue safely?”

Relevant information is split among Shared learning, Trust & security, Learning
& task, Analysis, Agent introspection → Memory, policies' Learning & task focus,
and Evidence → Run quality. Some panels are collapsed or in a scrollable sidebar.
Recovery is largely an inferred resume behavior or an operations CLI/runbook
workflow. Backup/restore, tracing and operational preparation have no clear
workspace entry point.

**Fix:** add problem-oriented entry points while retaining existing controls:
**Mission progress**, **Why held?**, **Experience used**, **Investigate a run**,
**Recovery readiness**. Connect one selected mission across these views. Expose
CLI/runbook-only operations as such; do not turn every backend function into an
unreviewed button. Distinguish mission-change audit history from execution audit.

Sources: `AppShell.tsx`, `MissionInspection.tsx`, `RunLearningPanel.tsx`,
`IntrospectionPanel.tsx`, run detail tabs, `EvidenceNav.tsx`, `docs/RUNBOOK.md`.

### A12 — P2: the strongest current evidence is not the primary public demonstration

**Pain point:** evaluators need proof of AI planning, adaptation and reliable
execution, not only feature assertions.

The public five-moment story uses an honestly labeled fallback-planner run and
discloses its historical chain-order gaps. It should retain those disclosures.
More recent evidence includes a completed camera-informed Muse mission with
88 verified original events and 25 verified signatures, live Tavily validation,
and the Memgraph graph. Those are not connected into the main public story.
The public 489-test statistic is dated and qualified, so it is historical rather
than a false claim; raw test totals still do little to explain operator value.

**Fix:** supplement the archived story with a clearly dated verified mission and
links to planning provenance, adaptation, memory retrieval and evidence. Explain
what each result establishes. Do not silently relabel the old recording or apply
new counts to it. Demonstrate offered versus actually applicable experience.

The benchmark view also shows a real tradeoff: in its recorded rule-based suite,
learning reduces wrongly blocked safe moves from 16% to 3.9%, while mean time
to goal rises from 71.1 s to 87.7 s. Avoid translating “learning” or “optimization”
into an unconditional claim of faster missions. Call contacts in those results
simulated body contacts, not physical-world results.

Sources: public story and validation section, `frontend/src/app/evidence/page.tsx`,
[fresh live validation](validation/2026-11-03-live-integrations/),
[graph validation](validation/2026-11-03-knowledge-graph/).

## Full capability-to-pain-point coverage

“Explained” below means public communication, not a new runtime verification.
Workspace assessment describes discoverability and accessible workflows.

| Capability | Pain point / user question | Public presentation | Workspace coverage and gap |
| --- | --- | --- | --- |
| Mission management | How do I assign, supervise and repeat a mission? | Explained in hero/group/guide | Mission desk, drafts, assignment and history are accessible; examples need current navigation scope (A04). |
| Routing | How does the robot find a permitted path? | Guide explains aisle/hazard routing | Facility views and detailed route inspection exist; NetworkX role is chiefly under Trust & security (A09). |
| AI planning | How does an instruction become a plan? | Conditional guide card; public recording uses fallback | Mission instructions and model provenance exist, but availability language is inconsistent (A05/A12). |
| Agentic planning | Can planning query state and respond to feedback? | Explicit guide card | Tool/reasoning views exist in run detail, but guide lands on generic Mission Control (A07/A09). |
| Perception | What does the system observe, and how reliable is it? | Conditional guide card | Run Site & vision/camera; main workspace shows unavailable vision correctly. No direct guided path (A05/A07). |
| Task fidelity | Does the plan still serve my original goal? | Explicit guide card | Run Learning & task / policy drift demo; link stops at run list (A07/A11). |
| Safety governance | What restrictions apply to this proposal? | Strongly explained | Policies and decision panels prominent; displayed geofence differs from active facility (A03). |
| Execution authority | Was this exact action admitted? | Strongly explained twice | Authority, permits and controller evidence present; progress labels conflate stages (A01/A02). |
| Human oversight | What can I review, replace or stop? | Guide explains scoped review | Replan-and-hold and eligible review controls are operationally represented. Better “why held/next step” context needed (A01/A11). |
| Emergency control | Can I stop independently and know it stopped? | Guide and authority sections | Fleet/robot stops prominent; voice availability differs by component (A05). |
| Fleet coordination | How do separate robots share space? | Group/guide; limitations stated | Fleet assignment/status present. Reservations/conflict reasons and lack of a general scheduler need a clearer operator explanation (A09/A11). |
| Environment adaptation | What happens when the route's assumptions change? | Public stop/replan story and guide scenarios | Scenario lab, holds, replans and lifecycle evidence exist; top-level status can hide the current block (A01). |
| Persistent learning | What experience will help another compatible mission? | Hero strip, group and guide | Shared learning, lessons, introspection/search and graph exist but are fragmented; public link opens benchmarks (A07/A11). |
| Learning security | Can stale, edited or poisoned experience influence plans? | Guide explains origin/context/freshness checks | Context filtering, quarantine/checkpoints and drills visible in specialist views. Fixture metrics need their provenance retained when summarized (A11/A12). |
| Rule management | How can rules change with evaluation and approval? | Complete workflow described | Backend workflow exists; current UI principally read-only parameters/history (A10). |
| Optimization | What can improve, and what tradeoffs remain? | Guide says bounded recommendations | Run Analysis and tuning advice exist but are deeply placed. Avoid universal efficiency claims (A11/A12). |
| Robustness testing | What happens under attacks or difficult cases? | Validation section and guide | Scenario lab and security drills accessible. Adversarial/holdout service scope is broader than that visible drill list; label specialist/API paths. |
| Site intelligence | Can external guidance help without issuing instructions? | Guide mentions screened guidance | Actual interface is Run → Site & vision; guide points elsewhere. Live/offline status should remain explicit (A05/A07). |
| Evidence | Can I verify what was proposed, allowed and admitted? | Recorded events and integrity limits disclosed | Receipts, audit, reports and graph exist. Preserve approval/admission/outcome distinctions and explain different audits (A01/A11/A12). |
| Analysis | Why did the mission fail, diverge or repeat a problem? | Guide card, little landing proof | Analysis/introspection/run-quality views exist; discovery and mission context are fragmented (A07/A11). |
| Recovery | Can an interrupted mission continue without repeating uncertain work? | Hero strip and guide | Pause/resume plus backend reconciliation/CLI backup workflows; no clear recovery readiness or checkpoint walkthrough (A07/A11). |
| Operations and twin | Can I see the facility and assess system health? | Facility story, environment selector, guide | Strong shared 2D/3D facility, fleet and connection feedback. Availability, operational runbooks and populated mobile layouts need work (A05/A06/A11). |

Cross-cutting addition: Memgraph now has an actual interactive plot and a
source-evidence inspector. It supports learning/analysis/evidence communication;
it does not replace the policy gate, signed store or NetworkX route engine.

## What should be preserved

- Restored cinematic landing identity and real facility geometry.
- Five capability groups and the searchable 22-area guide with scope boundaries.
- Clearly labeled illustration versus recorded simulator evidence.
- Disclosure of historical integrity gaps and navigation-only humanoid scope.
- Operator stop controls, route replacement, scoped review and explicit resume.
- Actual graph nodes, source-linked inspection and the retained evidence table.
- Existing specialist capabilities, including run analytics and API/CLI workflows.

## Recommended implementation order and acceptance

1. **Correct operational truth first (A01–A06).** Feed an approved-but-refused
   action fixture to both views: neither may claim the robot is executing.
   A long-running mission must retain its plan/admission milestones. Displayed
   bounds must match the current world. Disabled voice/model paths must be
   consistent. Populate long event IDs and verify 390 px layout.
2. **Repair feature access (A07/A10/A11).** Each capability link reaches the
   advertised tab/section, or an explicit run picker/setup/API explanation.
   Identify which rule/recovery operations are available through UI versus API/CLI.
3. **Present the full mission story (A08/A09).** One user objective, one changing
   facility, one connected lifecycle. Explain the user's problem and result at
   each stage. Put architectural names behind understandable roles.
4. **Connect stronger proof (A12).** Link a fresh verified model-backed mission,
   graph evidence and relevant memory to the public journey. Preserve historical
   disclosures and distinguish configuration from validated operation.

These are presentation and workflow tasks. They do not authorize adding physical
manipulation, a general fleet scheduler, external ACE/Agentic Kernel integration,
hardware certification or cross-platform skill transfer to the capability claims.
