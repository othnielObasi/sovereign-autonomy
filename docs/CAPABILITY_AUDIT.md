# Platform capability audit - 4 November 2026 update

Checked against the live deployment (Nebius us-north1, https://204-12-178-126.sslip.io)
with real missions, and against the test suite (531 passed, 4 skipped).

## What changed since 3 November

| Area | Change | Verified |
|---|---|---|
| Fleet learning release | Lessons now have a real lifecycle: candidate, evaluated, approved, released, withdrawn. Evidence must come from two robots in the same or a touching 0.5 m cell. Approval and release need a signed-in operator and are signed, tamper-evident events. Planners use only released versions that match their site, map, policy and robot type. | Live: a lesson built from robot-1 and robot-2 observations was released; both carriers received it and the humanoid (robot-3) was excluded as incompatible. robot-2's next route plan recorded the lesson. |
| Run loop: stale permits | After a soft review the robot is stopped, which advances its controller generation. The slower retry was permitted against telemetry from before the stop, so the controller refused it on every tick and the robot never replanned. Telemetry is now re-read first, and controller refusals count as denials. | Live: the mission that had 90 refusals now completes. |
| Run loop: blocked path | When the path check refuses a slowed move, the loop now replans instead of pausing for an operator. | Live: robot-1 delivery completed after two replans. |
| Meta models live | Meta's Model API returns no models to EU addresses (tested from Scaleway Paris, Amsterdam and Warsaw). The deployment moved to Nebius us-north1, where Muse Spark 1.3, SAM 3.1 and Muse Voice Transcribe are available. | Live: Muse Spark 1.3 planned a mission; SAM 3.1 matched people to simulator ground truth within about 1 cm at ~0.8 s per check. |
| Public pages | Homepage has a Built on Meta section; How it works uses the pharma cleanroom illustration, names the Meta models and lists 23 capabilities including fleet learning release. | Browser checks at 390 and 1440 px, no script errors. |

## Live status, 4 November

| Capability | Live | Notes |
|---|---|---|
| Missions, safety gate, signed permits, controller redemption | Yes | |
| Replanning after refusals | Yes | Muse Spark / Muse Spark Open |
| Muse Spark 1.3, SAM 3.1, Muse Voice Transcribe | Yes | Nebius us-north1 |
| Muse Spark Open (Baseten) | Yes | |
| Mixed fleet (2 carriers, 1 humanoid) | Yes | |
| Fleet learning release | Yes | Released lessons expire after their TTL (default 1 hour, maximum 24 hours) |
| Evidence chain and Ed25519 receipts | Yes | Receipt verification passes; the public-key listing endpoint returns an empty list (minor) |
| Tavily site intelligence | Configured | No live lookup exercised yet |
| LangSmith tracing | Key set | Trace delivery not confirmed |
| Memgraph | Off | Optional, off by default |

Known limits: worker-heavy corridors can keep a robot stopped long enough to hit the
public demo's 7-minute mission limit (safe behaviour, not a fault); an integrity alert
message shows a garbled dash; robots navigate, stop and wait only.

# Earlier audit - 3 November 2026

Checked repository implementation, saved validation reports and the running
isolated preview at port 19300. This was a read-only runtime check; no missions,
stop commands, paid model calls or configuration changes were made.

## Platform-wide inventory

Subsequent addition: optional [Memgraph operational graph](MEMGRAPH.md), with
source-reverified mission/decision relationships, exact-context nearby retrieval,
planner context and a workspace evidence panel. This adds graph retrieval; the
original memory and NetworkX routing mechanisms remain responsible for learning
eligibility and route costs.

The initial audit focused on robot navigation and missed much of the platform.
The operator-control findings were subsequently implemented; see the follow-up
at the end of this document.
This expanded inventory reviews API handlers, service implementations, UI routes,
tests and existing validation evidence. **Implemented** means a corresponding
implementation exists; it does not mean every deployment has it enabled or that
this read-only audit newly executed every workflow. **Conditional** identifies
configuration/model-dependent execution. **Partial** identifies a stated limit.

The source scan found 115 API/WebSocket route declarations in `app/api`; the
running OpenAPI schema exposes 116 HTTP operations, including authentication.
These are route counts, not capability counts. The machine-readable inventory
is [saved here](validation/2026-11-03-capabilities/inventory.json).

| Area | Implemented capabilities | State / boundary | Principal implementation |
|---|---|---|---|
| Mission management | Create/list/edit/delete missions; bay and coordinate goals; robot assignment; drafts; start/pause/resume/stop; mission replay; per-mission/global audit history | Implemented; replay re-executes a mission and differs from audit playback | `routes_missions.py`, `mission_service.py`, `routes_runs.py` |
| Geometric routing | NetworkX aisle routing; obstacle/rack avoidance; hazard exclusion; zone speed caps; densified waypoints; blocked-leg repair; path preview | Implemented; conservative planar geometry | `site_router.py`, `path_planner.py`, `bench/world.py` |
| Model mission planning | Natural-language waypoint proposals; map/camera context; model selection/tier cascade; response parsing; deterministic fallback; governed execution of proposed plans | Conditional model calls; fallback active in preview | `routes_llm.py`, `muse_planner.py`, `model_runtime.py`, `local_fallback_planner.py` |
| Tool-using planning | Agentic propose endpoint; world-state and policy-check tools; bounded iterative proposals; decision feedback/memory | Conditional; tools propose and pre-check, they do not independently authorize movement | `agentic_planner.py`, `routes_llm.py` |
| Perception | Robot camera frames; model detection; image-box floor projection; sensor comparison; caution zones and perception status/check | Conditional live vision; robot camera is a simulated heading-up top-down image, not a physical camera feed | `perception.py`, `meta_models.py`, `routes_sim.py`, simulator `camera.py` |
| Task fidelity | Task-drift checks; plan/goal consistency; geometric route replacement when a proposed route drifts | Implemented for navigation goals; no general physical task planner | `task_guard.py`, `/plans/check`, `test_task_guard.py` |
| Safety policy gate | Geofence; speed; human/worker proximity; obstacle/path clearance; hazards; uncertainty/review; hard/soft failure classification; policy test/evaluate endpoints | Implemented; exact current policy set is defined in the catalog and rules | `rules_python.py`, `policy_catalog.yaml`, `routes_governance.py` |
| Execution authority | Fresh/versioned world state; exact-action signed single-use expiring permits; controller redemption; revocation epochs; dispatch checkpoints; action budgets | Implemented independently of model planning; no accepted move without admission | `execution_authority.py`, `autonomy/core.py`, `permit.py`, `controller.py`, `operations.py` |
| Human oversight and identity | Operator approval records; context-bound uncertainty-review leases; operational replan-and-hold and resume; viewer/operator/admin roles; JWT accounts and production access checks | Operational oversight implemented in the follow-up linked below; no SSO or tenant isolation; physical safety remains outside simulator validation | `routes_operator.py`, `operator_approval.py`, `auth/`, `test_roles.py` |
| Emergency controls | Global/robot/mission/agent kill scopes; controller e-stop; verified stopping; authenticated release; dispatch watchdog; dead-man stop; stop-only voice | Implemented; voice conditional on configured transcription; reset does not imply automatic mission resumption | `routes_authority.py`, `execution_authority.py`, simulator `server.py` |
| Fleet and platforms | Independent robot telemetry/targets/authority; one active mission per robot; path-cell reservations; peer obstacles/contact monitoring; AMR/humanoid profiles | Implemented for simulated navigation; no general scheduler/deadlock solver or manipulation | `autonomy/robot_profiles.py`, `autonomy/operations.py`, `test_fleet.py`, `test_mixed_fleet.py` |
| Environment lifecycle | Detect changed environment context; invalidate incompatible memory; fence stale controller actions; hold movement; replace obsolete routes and revalidate | Implemented; safe hold when no replacement is available | `environment_lifecycle.py`, `run_service.py`, `test_environment_integration.py` |
| Persistent learning | Signed route-delay experience; planner lessons from governance outcomes; stored decision/denial/strategy memory; relevance ranking; TF-IDF cosine memory search; cross-run patterns/baselines | Implemented; memory search is lexical TF-IDF rather than neural embeddings; cross-platform transfer absent | `route_learning.py`, `planner_lessons.py`, `persistent_memory.py`, `cross_run_learning.py` |
| Learning integrity | Context applicability; age decay/expiry; two-source corroboration; bounded source votes; anomaly quarantine; signed lesson integrity; deletion/rollback detection with separate checkpoint | Implemented with tests; source IDs are not independent sensor truth and the checkpoint is not remote immutable storage | `experience_policy.py`, `memory_ledger.py`, `test_learning_poisoning.py`, `test_lesson_integrity.py` |
| Governed rule lifecycle | Inspect active parameters; create/reject proposals; replay evaluation; seeded candidate benchmarking; named approval; versioned activation/history; rollback | Implemented; recommendations cannot silently mutate active safety rules | `routes_policy_proposals.py`, `policies/proposals.py`, `test_governed_rules_and_signing.py` |
| Optimization and scoring | Safety/compliance/mission-success/efficiency/smoothness scorecards; bounded optimizer recommendations; historical tuning recommendations; score trends | Implemented recommendations and analysis; not autonomous unreviewed safety relaxation | `scoring_engine.py`, `optimizer.py`, `adaptive_tuning.py` |
| Robustness and gaming checks | Per-run/cross-run reward-hacking indicators; adversarial and holdout policy suites; post-run safety reports; near-miss/violation analysis | Implemented diagnostic checks; benchmark results are not a physical safety certification | `integrity_monitor.py`, `adversarial_validator.py`, `safety_validator.py`, `test_reward_hacking.py` |
| AI security and site intelligence | Injection screening/quarantine; planner canaries; poisoned-memory drills; bulletin filtering; spill baseline exclusions; trusted-source guidance lookup that can only tighten constraints | Implemented offline controls; external Tavily lookup conditional; outside text cannot directly approve actions or change rules | `site_intel/`, `canaries.py`, `drills.py`, `poisoning_drill.py` |
| Evidence and reporting | SHA-256 event chains; Ed25519 decision receipts/public-key verification; policy decision history/stats; timeline replay; JSON audit bundles; JSON/text reports and framework mappings | Implemented audit support; framework mappings do not establish legal compliance or certification | `routes_governance.py`, `routes_compliance.py`, `replay_service.py`, `compliance_report.py` |
| Analysis and explanations | Recorded planner/tool steps; denial history and memory recalls; telemetry/scene/failure analysis; plan-versus-execution divergence explanations; executed paths and spatial risk heatmaps | Computed/recorded views implemented; model-written explanations conditional and not proof of internal model reasoning | `routes_llm.py`, `routes_runs.py`, `routes_governance.py` |
| Reliability and operations | Interrupted runs restart paused; unknown dispatch reconciliation without blind retry; confirmed-waypoint continuity; signed backup manifests; backup verify/restore; coordinated learning checkpoint backup | Implemented single-site workflows; no multi-site replication or automatic fleet failover | `ops/backup.py`, `run_service.py`, `test_backup_restore.py`, `test_resume.py`, `RUNBOOK.md` |
| Observability and digital twin | Dependency health; Prometheus metrics/Grafana config; model usage/latency; optional LangSmith/OTLP spans; WebSocket/HTTP telemetry; three site layouts; seeded scenarios; 2D/3D, camera/layers/actor inspection/mobile/fallback | Implemented local telemetry/UI; tracing/exporters conditional; software rendering differs from physical robot sensing | `observability/`, `routes_health.py`, `routes_ws.py`, `frontend/src/app/`, `SIMULATOR_CONFIG.md` |

## Where these capabilities appear

- `/mission-control`: current fleet, mission preparation/control, scenario lab,
  detailed live facility and compact decision/learning evidence.
- `/missions`: mission CRUD, drafts and assignment workflows.
- `/runs` and `/runs/{id}`: historical and active mission records, detailed
  execution/evidence, analytics and additional operator/planning tools.
- `/authority`: execution authority, kill scopes, security drills and learning
  integrity status.
- `/policies`: policy inspection, testing and governed change workflows.
- `/evidence`, `/audit`, `/compliance`: evidence summaries, mission audit and
  reporting; the full API exposes additional analysis/export operations.
- `/twin`: retained immersive facility/mission experience.
- Operations CLI and infrastructure config: backup/restore, benchmarks, metrics,
  Grafana and tracing configuration. These are not all dashboard buttons.

The redesigned Mission Control is a compact operational entry point. It is not
an exhaustive catalog of the project's implemented capabilities. Preserving
backend functionality alone also does not prove that every older workflow is
fully represented in the new main workspace. UI discoverability/parity must be
reviewed separately against this inventory.

## Current runtime

Health reports database and simulator OK, pharma site, execution authority
enabled and no kill locks. Fleet API returns robot-1/robot-2 as AMRs and robot-3
as a humanoid navigator. This isolated validation stack deliberately runs without
model keys: planner_provider=fallback; Muse/Gemini/Muse Open/voice disabled,
vision_provider=null. This does not establish the configuration of another
running deployment or the user's normal environment.

## Robot navigation detail and limits

| Area | Verified implementation | Limit |
|---|---|---|
| Robot actions | MOVE_TO, STOP, WAIT in proposal schema and simulator command handler | Both robot types have the same action set. No picking, grasping, door opening, equipment operation or physical QC action |
| AMRs | Two independent simulated carriers; per-robot admission, stop and telemetry; zone speed limits | Material-delivery role describes navigation; no payload handling actuator |
| Humanoid | Separate trusted capability profile, 0.35 m body radius, 1.72 m visual model, articulated motion and 0.30 m/s cap enforced by gate/authority/controller and routing | Planar navigation simulation. No balance controller, trained gait, manipulation or hardware adapter |
| Task assignment | Assign any fleet robot to a bay or floor destination | Role strings are descriptive. QC/packaging versus material-delivery eligibility is not enforced as a task-capability matrix |
| Governance | Policy decisions, fresh-state path checks, signed single-use permits, controller redemption, kill/stop/dead-man paths | Simulator-level assurance; physical braking and full moving-obstacle prediction are not demonstrated |
| Coordination | Per-robot reservations, one active run per robot, peers treated as obstacles; per-platform contact/sensing radii | Conservative existing AMR routing/reservation envelope retained; no central fleet scheduler or general deadlock resolution |
| Learning | Signed context-scoped route experience and planner lessons; quarantine/invalidation | Incompatible capability profiles are excluded. AMR-to-humanoid transfer is not implemented |
| Planning/perception/voice | Model adapters and deterministic fallback exist | Only fallback is active in this preview. Live model accuracy and availability were not checked here |
| Workspace | Bay/floor missions, draft save, mission execution controls, six scenarios, detailed inspection, plan/travelled paths, policy evidence, 2D/3D and mobile | Extended historical analysis remains on run/evidence pages |
| Facility | Pharma, factory and warehouse layouts; shared static geometry for Mission Control and run | Vault, controlled-door and reserved-airlock workflows are absent |

## Evidence

Sources: `backend/app/autonomy/robot_profiles.py`,
`backend/app/schemas/governance.py`, `sim/warehouse_sim/server.py`,
`backend/app/services/execution_authority.py`, `site_router.py`,
`backend/app/services/mission_service.py` and `route_learning.py`.

Saved validation: full backend suite 456 passed; after the final peer-position
snapshot correction, 22 focused backend checks passed. Workspace browser report
7 checks, Mission Control 10 checks and facility parity 5 checks, all passing
with no browser errors. Those runs precede this audit; they were inspected, not
rerun. See `validation/2026-11-03-workspace/README.md`.

## Follow-up priorities

1. Make task language and the capability display explicit about navigation-only
   roles; avoid implying the humanoid performs physical QC or sample handling.
2. Add a task-capability eligibility model before introducing genuinely different
   jobs/actions. Profile labels alone do not enforce job compatibility.
3. Validate configured model integrations separately when live-model operation
   is requested. The present preview is deliberately deterministic.
4. Define and test a compatibility/translation contract before attempting
   cross-platform experience transfer.
5. Update older capability summaries: TRACEABILITY contains historical two-robot,
   two-site and single-robot descriptions. Current pharma runtime has three robots
   across two platform types, and the repository supports three layouts. Preserve
   dated evidence when revising those summaries.

## Operator implementation follow-up

The original record-only override finding has been addressed in
[OPERATOR_CONTROLS.md](OPERATOR_CONTROLS.md). Replan now stops, replaces and
persists a route while holding the robot paused. Review approval validates a
specific signed uncertainty decision against fresh context, creates a bounded
lease and resumes through the normal permit path. It cannot clear speed,
proximity, path, hazard or other safety-limit violations. The UI exposes these
actions explicitly in both operational locations. Verification results are kept
with the implementation document and its validation artifacts.

Oversight follow-up verification: **489 backend tests**, including 33 oversight cases, and **15 browser checks** passed; production build/type checking passed. This closes the previously record-only operator-action gap within the simulator scope. Other conditional integrations and stated platform limits remain as listed.
