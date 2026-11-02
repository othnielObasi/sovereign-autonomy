# Capability traceability

Every capability in the Sovereign Autonomy plan, with its status and the evidence for it.

- **Working**: implemented, wired into the running system, and covered by automated tests.
- **Ready, needs key**: implemented and tested against Meta's documented API shapes; runs as soon as the key is set.
- **Partial**: some of the requirement is met; the gap is stated.
- **Not started**: nothing yet.
- **Pre-existing** marks capabilities from the codebase before 26 Oct 2026 (not hackathon work).

Last checked: 1 Nov 2026. 303 backend tests passing; frontend type-checks; a live run with the simulator, backend and dashboard as separate processes (results at the end).

## Execution contract (plan §3–4)

| Requirement | Status | Evidence |
|---|---|---|
| Per-action authorization at the simulator (not a shared token) | **Working** | The simulator refuses any MOVE_TO without a valid permit (`test_simulator_refuses_altered_forged_expired_and_wrong_robot`; drill `bypass`) |
| Permit bound to robot, exact parameters, policy version and world version | **Working** | Altered target refused, `action_mismatch` (drill `tamper`) |
| Expiry and unique permit id | **Working** | 5 s TTL; expired permit refused |
| Atomic single use at the gateway | **Working** | 8 concurrent uses, one wins; replay refused at the simulator (drill `replay`) |
| Reject revoked and stale permits | **Working** | Kill switch and world change void outstanding permits |
| Only APPROVED decisions get permits | **Working** | The gate's verdict is checked first; `/llm/execute` no longer runs NEEDS_REVIEW moves |
| Run loop sends only permitted moves | **Working** | `test_run_loop_sends_only_permitted_moves`; live run: 16 of 16 moves with permits |
| Full-path check before a permit | **Working** | Straight move sampled against people (1 m), obstacles, hazard exclusion zones and bounds; a robot already too close can still back away (`test_permit_refused_when_the_path_runs_through_*`) |
| Policy parameters in one place | **Pre-existing, working** | `app/policies/params.py` |
| Visible model provenance and fallback | **Pre-existing, working** | Plans record `model_used` / `source` |

## Nine pillars (plan §20)

| Pillar | Status | Notes |
|---|---|---|
| 1. Autonomous reasoning | **Ready, needs key** | Muse Spark 1.3 plans missions with the robot camera frame attached; Muse Spark Open (Baseten) proposes steps; labelled deterministic fallback. `MusePlanner`, `test_meta_models.py`. Live check: `scripts/check_meta.py` |
| 2. Multimodal perception | **Ready, needs key** | SAM 3.1: one prompt per object type, boxes projected onto the floor and cross-checked with the sensors; can only add caution (`test_sam_detection_becomes_a_floor_position_that_matches_the_sensors`) |
| 3. Graph intelligence | **Working** | The live router runs on NetworkX; racks and hazard zones are hard limits; learned delays steer the route (`test_learning_and_canaries.py`) |
| 4. Historical learning | **Working** (SQLite) | Signed experience recorded at the end of every run; forged or edited records quarantined (drill `poison`). Memgraph: not used |
| 5. Execution governance and gateway | **Working** | Our own execution authority; the separate AIRG product is not integrated |
| 6. Observability | **Working** (Prometheus); LangSmith **ready, needs key** | `GET /metrics`: decisions, permits issued/refused by reason, dispatch outcomes, kill switches with revoke and stop times, quarantined memory, model calls; `infra/grafana/dashboard.json` uses these names. LangSmith: one trace per mission linking each model call to the gate decisions and permits that followed, plus kill switches and drills (`test_tracing.py`; check with `scripts/check_langsmith.py`). OpenTelemetry: the same mission spans over OTLP/HTTP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (prompt sizes only) |
| 7. AI security | **Working** | A planner cannot authorize a move; injection firewall (pre-existing, drill `injection`); poisoned memory quarantined; canary tripwire |
| 8. Canary assurance | **Working** | Every mission plan carries a canary inside the untrusted context; a plan that obeys it is discarded. Live: Nemotron Ultra obeyed it and its plan was discarded |
| 9. Emergency control | **Working** | Global, robot, mission and agent kill switches; controller e-stop; verified stop; survive restarts; reset needs login; spoken stop via Muse Voice Transcribe (ready, needs key) |

## Reliability capabilities

| # | Capability | Status | Evidence / gap |
|---|---|---|---|
| 1 | World-state synchronization | **Working** (single robot) | Versioned, forward-only, freshness-checked; telemetry re-read before the gate if planning was slow |
| 2 | Trajectory safety | **Working**, point model | Full-path check at permit time plus the pre-existing racking check. No footprint, braking distance or moving-obstacle prediction |
| 3 | Execution reconciliation | **Working** | Lost answers settled from controller state, never retried |
| 4 | Identity and authorization | **Working** | Roles viewer < operator < admin with password-hashed accounts; stopping open to all, mission control and reset need an operator, rule activation and rollback need an admin; enforced in production (`test_roles.py`). No SSO or per-tenant separation |
| 5 | Watchdogs and degraded mode | **Working** | Dispatch watchdog; simulator dead-man stop; no permit secret means nothing moves; model outage falls back |
| 6 | Human-in-the-loop supervision | **Pre-existing, working** | Approve/deny/override; approvals expire after 120 s; operator kill and reset in the dashboard |
| 7 | Multi-robot coordination | **Working** (2 robots) | The simulator runs a fleet (robot-1, robot-2); each robot has its own permits, e-stop and dead-man stop and sees the others as obstacles. Before each permit the move's floor cells are reserved, all or nothing, so two robots never hold overlapping paths; a conflict is refused like a path check. One active run per robot. Live: two missions at once, 67 permits, 0 robot contacts (`test_fleet.py`). No central scheduler or deadlock resolution beyond waiting and replanning |
| 8 | Digital-twin scenario testing | **Working** | Two sites: the benchmark warehouse (pre-existing) and a new precision-parts factory (`test_factory.py`); seeded scenarios plus `/authority/drills`, eight real attacks against the live simulator |
| 9 | Model and learning lifecycle | **Pre-existing, partial** | Governed rule changes with replay, approval and rollback. No model shadow rollout |
| 10 | Incident replay | **Pre-existing, partial** | Hash-chained events, replay service, benchmark replay by seed |
| 11 | Resource budgets | **Working** | Per-run action budget on the dispatch path; STOP never goes through it |
| 12 | Fleet disaster recovery | **Working** (single site) | Signed, verified backups and restore; full-loss drill keeps kill switches and used permits (`test_backup_restore.py`); recovery objectives and steps in `docs/RUNBOOK.md`. No multi-site replication |
| 13 | Checkpointing and task continuity | **Working** | A restart pauses runs; resume refuses under a kill switch, settles uncertain moves and continues from the last confirmed waypoint (`test_resume.py`) |
| — | Safety assurance case | **Working** | `docs/SAFETY_CASE.md`: claim, assumptions, 15 hazards each linked to controls and tests, residual risks. Not a certification |

## Checkpoint continuity scenarios (plan §16)

| Scenario | Status | Evidence |
|---|---|---|
| CP-01 crash before dispatch | **Working** | Unsent permit expires; restart pauses the run; resume needs new permits |
| CP-02 crash after dispatch, before acknowledgement | **Working** | `test_resume_settles_a_lost_answer_before_moving` |
| CP-03 executed before checkpoint | **Working** | Resume continues from the last acknowledged waypoint, never repeating a completed leg |
| CP-04 duplicate delivery | **Working** | Replay refused at backend and simulator |
| CP-05 changed world state | **Working** | Old-world permit refused |
| CP-06 kill switch while offline | **Working** | Kill switch survives restart; resume refused while it holds |
| CP-07 corrupt checkpoint | **Partial** | Journal tampering detected; no restore from backup |
| CP-08 dependency outage | **Working** | Resume refused if the controller cannot be asked about an uncertain move; no permit secret fails closed |

## Live check (1 Nov 2026)

Simulator, backend and dashboard as separate processes, shared random permit secret, Nemotron as the planner (no Meta key yet):

1. Security drills from the dashboard: **8 of 8 passed** (bypass, tamper, replay, forged, poison, injection, canary, kill).
2. Mission to B-03: NetworkX route; **16 of 16 moves sent with permits**; dead-man stop never tripped.
3. The canary tripped: Nemotron Ultra copied the hidden instruction, so its plan was discarded and the aisle route used.
4. After the run, its signed experience was recorded (3 learned cells, 0 quarantined).
5. Earlier drill on the same system: direct command HTTP 403; global kill revoked authority in 16 ms with the stop verified in 453 ms; reset without login HTTP 401.
