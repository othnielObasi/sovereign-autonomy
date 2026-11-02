# Experience learning: implementation and validation plan

Date: 2 November 2026. Status: three implementation milestones delivered; physical and model-driven evaluation remain outside this scope.

Implementation started: context identity is captured in simulator/benchmark telemetry and decision receipts, and used to scope signed route memory and planner lessons. Legacy contextless data remains available for inspection but is excluded from operational retrieval. Route costs and lesson ranking decay with observation age and expire after a configurable horizon. A signed, durable memory-invalidation service is available internally and consulted on retrieval. Controller-side redemption and stop/restart fencing are now implemented as the second milestone. The third milestone adds automatic environment-event propagation, deterministic graph evaluation, dashboard evidence, and a real-service browser harness; see the implementation record below for validation and limits.

Validation on 2 November 2026: the project `.venv` completed the backend suite with **364 passed**. After the final site identity and API schema additions, the focused context/learning/lesson/factory/API suite completed with **62 passed**. Python compilation and diff whitespace checks also passed. No live model calls, browser validation, or paired learning-benefit experiment were performed for this milestone. The system Python environment was unsuitable for the full suite (missing Matplotlib and mismatched OpenTelemetry packages); use the project virtual environment.

### First milestone operational notes

- The warehouse and factory publish layout-derived map identities. Site identity is explicit for these sites; an unnamed custom layout falls back to a geometry-derived identifier and should receive an explicit `site_id` before deployment across facilities.
- The simulated fleet currently shares `sim-amr-radius-0.4m-v1`. Physical adapters must provide their own authoritative capability profile instead of reusing this simulation profile.
- SQLite adds `experience_context` and `experience_invalidations` alongside the existing `experience` table. No old records are relabelled as belonging to the current site. Planner lesson context is stored in the existing JSON record.
- `EXPERIENCE_DECAY_S` defaults to 86400 and `EXPERIENCE_TTL_S` to 604800. These are configurable simulation defaults, not established physical safety thresholds.
- `/authority/learning` reports current context, record counts, and accepted/excluded records with reasons. If current context is unavailable, operational retrieval returns no reusable experience. The route planner can still use its deterministic route and live governance checks.
- Internal `RouteMemory.invalidate(event_id, scope, reason)` persists signed, idempotent invalidation. Scope matches an AND of site/map/policy/capability fields. An invalidated generation remains ineligible even for newly written observations; move to a new authoritative version after revalidation. This is a service primitive, not a public mutation endpoint or an automatic change-event integration.
- Lifecycle records are re-read on retrieval; cache refresh cannot extend their validity. Corrupt invalidation records disable memory retrieval. Signatures detect edits, but this milestone does not provide an external anchor that detects deletion of lifecycle rows by a database administrator.

### Second milestone: controller admission and revocation

Validation on 2 November 2026: **394 backend tests passed** in the project `.venv`, including **30 new controller redemption cases** and a real localhost HTTP callback. Simulator Docker file-set imports, Compose callback/volume configuration, Python compilation, and diff whitespace checks passed. Docker itself is unavailable on this host, so an actual image build was not run. Tests now isolate lifespan and real-server databases from local mission state and other pytest processes. No live-model or browser validation is claimed.

- Dispatch checks the permit, action budget and watchdog, then journals the action as `IN_DOUBT`. It does not spend the permit.
- The controller sends a signed, short-lived request to `/authority/redeem`. The authority checks current policy, fresh world version, persisted kill locks/epoch, the exact pending action, and unused permit before atomic redemption. Policy activation is serialized with redemption. Every authority startup advances the persisted epoch.
- Permits bind controller boot identity, robot generation and site/map/capability context captured in telemetry. The signed admission response is bound to the exact request and valid for at most one second, additionally bounded by request/permit expiry.
- The network call runs outside the simulator lock. The final local check and admission are serialized with STOP, e-stop, reset, seed/scenario changes and dead-man stops. Those operations advance generations; a redeemed reply arriving afterward is refused. A command admitted first is stopped by the subsequent stop operation. Backend kill verification reports observed stopping, not instantaneous motor safety.
- `SIM_STATE_DB` persists admitted action/permit IDs, e-stops and used release tokens. A new boot identity rejects unused pre-restart permits. Admission is journalled before assigning the target; it is evidence of command admission, not physical completion. A crash in that narrow window may lose a move and must not cause blind replay.
- Definite controller refusal is recorded as not executed and dispatch attempts a containment STOP. A lost command reply remains uncertain. Reconciliation uses controller admission evidence; an unredeemed action is atomically retired before declaring it unsent. Retired and redeemed permits have distinct durable states so reconciliation itself can survive a crash. Redeemed actions without controller evidence remain `IN_DOUBT` and block automatic recovery. Telemetry exposes the latest 200 admissions per robot; older missing evidence requires investigation.
- `AUTHORITY_BASE_URL` must point from simulator to backend. Callback failure refuses new admission; there is no signature-only fallback. Compose supplies the callback URL and `controller_data` volume. The backend and simulator must be upgraded together.
- This protocol currently targets one authority process and one warehouse controller. It does not add physical robot safety, replication, automatic lifecycle-event integration, model training, or proof that shared learning improves missions.

## Objective and scope

### Third milestone: environment lifecycle and evaluation

Validation: 403 backend cases passed across the regression and an isolated tracing rerun (the loaded full run had one HTTP timeout). The production frontend build passed compilation, types, lint and 13-page generation. Real-service browser acceptance passed in forced WebGL fallback mode; the normal factory scene was separately rendered and inspected with external requests blocked. See [validation evidence](validation/2026-11-02/README.md) for exact scope and limitations.

- Simulator seed/scenario changes stop targets, fence controller generations, and publish durable previous/current map identities. Scenario/seed mutations require operator authorization outside development mode. A new map identity prevents accidental reuse after returning to the same scenario.
- Signed lifecycle events invalidate old context on site/map/policy/capability changes and on effective constraint changes. Constraint invalidation uses an observation cutoff, allowing newly verified observations to become eligible. Identical polls and moving actors do not invalidate memory. Missed simulator events are ingested from durable history; persisted snapshots survive backend restart.
- Active runs compare their plan assumptions with effective telemetry before planning and again before governance. A change stops motion and discards old waypoints. A replacement route and retrieval evidence are audited; unavailable routes hold and retry instead of falling through to an unrestricted proposal.
- Authority and mission panels show source robot, experience ID, age, eligibility/rejection reason, context, environment events and replacement/hold decisions. Twin scene failures are contained; mission and fleet-stop controls remain outside the scene. Remote HDR dependencies are skipped in favor of local lighting.
- The saved [graph experiment](../backend/bench/results/experience/README.md) uses 20 independent seeded acquisition/evaluation trials, five no-benefit seeds, no evaluation writes, and no model calls. Compatible sharing reduces modeled travel-plus-queue time by 28.6%; paired mean saving is 8.805 seconds with bootstrap 95% interval [6.1, 11.61]. All 15 deliberately stale records are excluded; no forbidden graph edge is selected. This measures a two-corridor routing model, not physical mission time, contacts, motor safety, or neural training. Physics and model-driven paired evaluation remain future work.
- Reproduce with `python -m bench.experience_eval --seeds 20 --out bench/results/experience` from `backend`. Browser validation uses `scripts/browser_validation_stack.py` and `node tests/experience.browser.cjs`, with an isolated production frontend and local simulator/backend. The explicitly labelled signed browser fixture is synthetic; credentials and model calls are disabled. Browser evidence is stored under `docs/validation/2026-11-02`.

Limits: one local authority/controller deployment; database signatures do not externally anchor deleted records; hardware adapters must provide authoritative change events and capability identities. Environment history is bounded to the latest 50 simulator events; current-context filtering still rejects incompatible generations. No physical safety claim follows from these simulation checks.

Learn from past missions, verify against the present environment, and authorize each consequential action independently.

The initial learning mechanism is continual experience acquisition and reuse: capture mission outcomes, retrieve applicable lessons, and adapt plans. It does not update neural-network weights or train humanoid locomotion or manipulation. Offline model training and physical robot integration are separate future projects.

Existing foundations include signed route experience, policy-scoped planner lessons, replanning, deterministic governance, permits, recovery, and a two-robot simulator. This plan extends those foundations; it does not establish integration with external ACE, Agentic Kernel, AIRG, or ROS 2 products.

## Original gaps (addressed by these milestones)

- `backend/app/services/route_learning.py` stores signed cell delays without site, map, policy, or robot capability context. Identical coordinates in different sites can therefore share an inappropriate historical cost.
- `RouteMemory.load(max_age_s=5)` controls cache refresh, not experience expiry. Stored delays are averaged without age decay. A valid signature establishes integrity, not truth or current applicability.
- `backend/app/services/planner_lessons.py` already scopes lessons by policy version; extend this protection to environment and capability compatibility.
- `backend/app/autonomy/permit.py` verifies controller-side action binding and expiry without consulting current revocation state. Backend revocation alone does not invalidate a still-unexpired permit submitted directly to the simulator.
- Existing automated checks do not by themselves prove a measurable benefit from shared learning or working browser interactions.

## 1. Scope experience to its context

### Implementation

Extend signed route records and planner lessons with:

| Field | Purpose |
|---|---|
| `site_id` | Separate facilities and simulation sites |
| `map_version` | Identify compatible geometry and coordinate frames |
| `policy_version` | Identify the rules under which the observation occurred |
| `source_robot_id` | Preserve provenance |
| `capability_profile_version` | Identify relevant robot configuration and capabilities |
| `observed_at`, `validated_at` | Separate observation time from subsequent verification |
| `experience_type` | Select validity and ranking rules |
| `status`, `status_reason` | Explain eligibility, quarantine, or invalidation |

Define stable site identity and authoritative version generation. A map version must cover geometry, units, and coordinate frame. Define an explicit compatibility rule for capability profiles; initially require an exact match. Source robot identity is provenance, not a requirement to restrict reuse to that same robot.

Filter incompatible records before ranking. Include the context in signed payloads and in aggregation/cache keys. Store lifecycle changes as authenticated, auditable updates rather than silently editing a signed observation. Reuse the existing storage and NetworkX routing initially.

Migrate existing records without inventing their original context. Retain them for inspection, but exclude them from operational reuse until revalidated. Signing-format changes need an explicit schema version.

### Tests and acceptance

- Warehouse experience cannot affect factory routing at identical coordinates.
- Changed map or policy versions exclude affected records.
- Incompatible capabilities prevent reuse; compatible robots can share experience.
- Context-field tampering causes quarantine.
- Legacy records remain inspectable and cannot silently become eligible.
- Retrieved lesson IDs and compatibility decisions appear in mission evidence.

Primary locations: `route_learning.py`, `planner_lessons.py`, `site_router.py`, database models/migrations, and the existing learning tests.

## 2. Separate freshness, applicability, and cache lifetime

### Implementation

| Information | Operational reuse rule |
|---|---|
| People, obstacles, robot pose | Require fresh live telemetry |
| Historical congestion | Advisory routing cost with age-decaying influence |
| Equipment availability | Verify current authoritative equipment state |
| Structural route knowledge | Require compatible map and coordinate frame |
| Authorization | Obtain fresh authorization; never retrieve permission from memory |

Use explicit validity settings by experience type. Choose thresholds through scenario testing and the safety assumptions; do not apply a universal TTL. Inject clocks into freshness logic for deterministic tests. Use monotonic time for local elapsed-time measurements and UTC timestamps for persisted observations; document clock-skew handling.

Replace unweighted congestion averages with an age-weighted estimate, for example `weight = exp(-age / decay_constant)`, subject to configured eligibility limits. Historical congestion must never open blocked graph edges or override live safety constraints.

Introduce durable invalidation events for map, policy, equipment, and robot configuration changes. Events identify scope, version, reason, affected records, and event ID. Processing must be idempotent: update eligibility, evict matching caches, mark affected plans for revalidation, and invalidate affected outstanding authorization. Check authoritative versions on retrieval and redemption as a backstop against delayed event delivery.

Keep invalidated history for audit. Missing required live state prevents new movement authorization; a retrieved experience cannot substitute for a missing sensor.

### Tests and acceptance

- With a fake clock, expiry excludes observations and age reduces congestion influence.
- Relevant events invalidate immediately; unrelated experiences remain eligible.
- Warm caches cannot return newly invalidated experience.
- Duplicate events are harmless; restart and delayed delivery do not resurrect invalid records.
- Stale or unavailable telemetry prevents permits for actions requiring it.
- Live observations override conflicting historical assumptions.
- Evidence records invalidation reason and event-to-enforcement latency.

## 3. Enforce revocation at controller acceptance

### Proposed implementation

Add controller-initiated permit redemption immediately before command acceptance:

1. The controller verifies the signature and exact command binding.
2. It authenticates to the authority and requests redemption of that permit for that action.
3. The authority atomically checks expiry, current revocation state, relevant world/policy/context versions, and single use, then records redemption.
4. The controller accepts the command only after a successful response and a final local e-stop check.

Refactor the current backend consumption step so there is one authoritative single-use transition, rather than consuming once in dispatch and again at redemption. Persist the permit-to-action relationship and controller outcome. A lost reply leaves the action uncertain; reconcile it rather than blindly issuing a replacement. A duplicate can return status but must not execute movement again.

Redemption alone does not eliminate the race between authorization and movement. Serialize local e-stop activation and command acceptance, propagate mission/agent revocation to the controller, and reject commands from revoked generations. Define the acceptance/revocation ordering and acknowledgement contract explicitly. A kill is reported as verified only after the required controller stop is observed. A reset must not make permits from an earlier generation usable again.

Authenticate the redemption channel and fail closed when it is unavailable. Keep local dead-man stopping and live safety checks for movement already accepted. Document this additional availability dependency. Use persistent epochs/generations so restarts cannot restore old authority.

### Tests and acceptance

- Issue a permit, kill its mission or agent, submit directly to the simulator: rejected.
- Issue a permit, engage and reset e-stop, submit the old permit: rejected.
- Relevant map, policy, or world changes reject outstanding permits.
- Concurrent duplicate submissions produce at most one command acceptance.
- Authority outage causes no new movement acceptance.
- Lost redemption/command replies reconcile without duplicate execution.
- Restart either process; used or revoked permits remain unusable.
- Use barriers to race kill and command acceptance deterministically: commands after the controller revocation boundary are refused; earlier accepted movement stops and produces measured evidence.
- Existing fleet isolation, budget, recovery, and kill-switch tests still pass.

Primary locations: `autonomy/core.py`, `autonomy/operations.py`, `autonomy/permit.py`, `services/execution_authority.py`, `services/sim_adapter.py`, authority API routes, and `sim/warehouse_sim/server.py`.

## 4. Measure whether learning helps

### Experiment

Extend `backend/bench` with paired seeded scenarios:

| Condition | Purpose |
|---|---|
| A: learning disabled | Baseline |
| B: compatible shared experience | Measure useful reuse |
| C: deliberately stale/incompatible experience | Measure rejection and recovery |

Robot A generates experience in a separate acquisition phase; Robot B is evaluated on comparable missions. Prevent evaluation outcomes from leaking into the initial memory of other conditions. Reset memory and simulator state between independent trials. Hold seeds, tasks, capabilities, and obstacle schedules constant across paired comparisons.

Start with deterministic planning to isolate memory effects. Run model-driven planning separately and record provider/model configuration and fallback use. Include both useful-memory scenarios and scenarios where historical knowledge should provide no advantage.

### Measures and acceptance

Record mission completion, elapsed time, distance, planning calls, gate denials, interventions, contacts, stale-memory rejection/false invalidation, invalidation latency, and execution without valid authorization. Save per-run records, configuration, seeds, and aggregate paired differences with uncertainty estimates.

Before running the comparison, select a primary efficiency measure and an improvement threshold. Accept B only if it meets that threshold without degrading the defined safety measures. For C, require every deliberately incompatible record to be excluded from operational reuse in the specified cases, with rejection evidence and safe recovery behavior. Report failed cases and distributions rather than only successful demonstrations. Zero observed violations in these trials is not a universal safety guarantee.

## 5. Explain decisions and verify the browser

### Implementation

Expose a mission evidence sequence:

`retrieved → compatibility/freshness checked → accepted or rejected → plan updated → action authorized → outcome verified`

Show experience ID, source robot, site/map version, age, applicability decision, and reason. Distinguish an accepted controller command from a completed waypoint or successful mission. Keep approved visual sections intact and contain rendering failures so mission controls remain usable.

Three.js is already npm-managed in this repository. Audit runtime assets separately; do not replace the renderer solely because the earlier HTML prototype depended on CDNs.

### Browser acceptance

Run Playwright against the real backend and simulator, with deterministic fixtures for optional model calls:

- Factory scene renders and both robot states appear.
- A mission shows its retrieved experience and resulting decision.
- A controlled environment change displays invalidation and replanning.
- Kill/reset/resume UI state agrees with controller telemetry.
- Failed 3D assets produce a usable fallback without disabling critical controls.
- Required locally packaged scenes and controls work with external asset requests blocked.
- Capture console errors, failed requests, and screenshots for failures; verify behavior through state assertions as well as images.

## Delivery sequence and completion evidence

1. Context schema, migration, retrieval filtering, and isolation tests.
2. Freshness rules, invalidation propagation, and deterministic clock/event tests.
3. Controller redemption, durable revocation, and concurrency/recovery tests.
4. Paired learning benchmarks with saved results.
5. Dashboard evidence and real-service browser checks.

Each stage should be independently reviewable. Run focused tests during development, then backend regression tests, frontend type-check/build, and relevant integration/browser checks. Avoid calling real paid model services in ordinary tests.

Update [TRACEABILITY.md](TRACEABILITY.md), [SAFETY_CASE.md](SAFETY_CASE.md), and [RUNBOOK.md](RUNBOOK.md) when implementation and evidence land. Mark a capability working only when its acceptance checks pass; link actual results and disclose remaining limitations. The milestone records distinguish implemented behavior from remaining physical and model-driven validation.
