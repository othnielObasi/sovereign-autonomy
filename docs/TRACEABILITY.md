# Capability traceability

Every capability in the Sovereign Autonomy plan, with its status and the evidence for it.

- **Working**: implemented, wired into the running system, and covered by automated tests.
- **Built**: implemented and tested on its own, not yet wired into the running system.
- **Partial**: some of the requirement is met; the gap is stated.
- **Not started**: nothing yet.
- **Pre-existing** marks capabilities from the codebase before 26 Oct 2026 (not hackathon work).

Last checked: 1 Nov 2026, 279 backend tests passing, plus a live run with the simulator and backend as separate processes (results below).

## Execution contract (plan §3–4)

| Requirement | Status | Evidence |
|---|---|---|
| Per-action authorization at the simulator (not a shared token) | **Working** | The simulator refuses any MOVE_TO without a valid permit (`test_simulator_refuses_altered_forged_expired_and_wrong_robot`; live: direct bypass got HTTP 403) |
| Permit bound to robot, exact parameters, policy version and world version | **Working** | Digest over all seven action fields; an altered target is refused (`action_mismatch`) |
| Expiry and unique permit id | **Working** | 5 s TTL; expired permit refused (`permit_expired`) |
| Atomic single use at the gateway | **Working** | Backend: 8 concurrent uses, exactly one wins (`test_permit_used_concurrently_succeeds_once`); simulator: replay refused (`permit_replayed`) |
| Reject revoked and stale permits | **Working** | Kill switch voids outstanding permits; world change voids them (`test_kill_switch_revokes_outstanding_permit`, `test_permit_rejected_after_world_changes`) |
| Receipts are not permits | **Working** | Signed receipts (pre-existing) now sit beside separate single-use permits |
| Only APPROVED decisions get permits | **Working** | DENIED and NEEDS_REVIEW refused (`test_only_approved_decisions_get_permits`); `/llm/execute` no longer runs NEEDS_REVIEW moves |
| Run loop sends only permitted moves | **Working** | `test_run_loop_sends_only_permitted_moves`; live: every move had a permit |
| Policy parameters in one place | **Pre-existing, working** | `app/policies/params.py` is the single source; the YAML is a description |
| Visible model provenance and fallback | **Pre-existing, working** | Plans record `model_used` / `source` |
| Process-local run state | **Partial** | Kill switches and the action journal are now on disk; plans and flags are still in memory |

## Nine pillars (plan §20)

| Pillar | Status | Notes |
|---|---|---|
| 1. Autonomous reasoning (Muse Spark) | **Not started** | Needs the Meta Model API key. Current planner is Nemotron with a labelled deterministic fallback (pre-existing) |
| 2. Multimodal perception (SAM 3.1) | **Not started** | Vision cross-check slot exists (pre-existing, Nemotron VL) |
| 3. Graph intelligence (NetworkX) | **Built** | `RouteGraph`: no-go edges learning cannot change, learned delays (tested). Not yet used by the planner |
| 4. Historical learning (Memgraph) | **Partial** | Signed experience records with quarantine are built (not wired). Learning from denials is pre-existing and unsigned. Memgraph: not started (out of scope) |
| 5. Execution governance and permit gateway | **Working** | See the execution contract above. Our own authority replaces the separate AIRG product, which is not integrated |
| 6. Observability | **Partial** | Every run's hash-chained log links PLAN → DECISION → AUTHORITY → EXECUTION; `/authority/evidence`. No OpenTelemetry export or Grafana dashboard for the new events |
| 7. AI security (injection, hijack, poisoning) | **Partial** | A compromised planner cannot authorize its own moves (structural, tested). Injection firewall pre-existing. Forged-experience quarantine built, not wired |
| 8. Canary assurance | **Built** | `CanaryRegistry` tested, not yet planted in planner inputs |
| 9. Emergency control (kill switches) | **Working** | Global, robot, mission and agent scope; controller e-stop; verified stop; survives restart; reset needs login (tests below; live numbers below) |

## Reliability capabilities (plan "Additional Critical Capabilities")

| # | Capability | Status | Evidence / gap |
|---|---|---|---|
| 1 | World-state synchronization | **Working** (single robot) | Versioned, forward-only, freshness-checked; telemetry is re-read before the gate if planning was slow. No multi-sensor fusion or clock sync |
| 2 | Trajectory safety | **Partial** | Pre-existing `PATH_CLEARANCE_07` checks each straight leg against racking. The full-path validator is built but not wired into the gate; no footprint, braking distance or moving-obstacle prediction |
| 3 | Execution reconciliation | **Working** | Every move is "in doubt" until the controller confirms; lost answers are settled from the simulator's actual target, never retried (`test_lost_acknowledgement_is_settled_from_controller_state`) |
| 4 | Identity and authorization | **Partial** | Kill-switch reset requires a logged-in operator (401 otherwise). No roles; the development token endpoint gives anyone a token outside production |
| 5 | Watchdogs and degraded mode | **Working** | Dispatch watchdog; simulator dead-man stop brakes the robot if moves stop arriving (`test_simulator_brakes_when_permitted_moves_stop_arriving`); no permit secret means nothing moves |
| 6 | Human-in-the-loop supervision | **Pre-existing, partial** | Approve/deny/override workflows exist. Approvals now expire after 120 s (`test_operator_approval_expires`) |
| 7 | Multi-robot coordination | **Built** | Exclusive corridor reservations, safe under contention (tested). The simulator has one robot |
| 8 | Digital-twin scenario testing | **Pre-existing, partial** | Seeded scenarios and hazards on demand. Attack and bypass cases are unit and integration tests, not yet simulator scenarios |
| 9 | Model and learning lifecycle | **Pre-existing, partial** | Rule changes go through replay, second-person approval, versioning and rollback. No model versioning or shadow rollout |
| 10 | Incident replay | **Pre-existing, partial** | Hash-chained events, replay service, benchmark replay by seed |
| 11 | Resource budgets | **Working** | Per-run action budget on the dispatch path; STOP never goes through it. Token budgets: pre-existing hourly limits in public-demo mode |
| 12 | Fleet disaster recovery | **Not started** | Out of scope for the hackathon |
| 13 | Checkpointing and task continuity | **Partial** | Action journal with hash chain, reconciliation and kill switches survive restart. A run interrupted by a restart is still marked failed rather than resumed from a checkpoint |
| — | Safety assurance case | **Not started** | |

## Checkpoint continuity scenarios (plan §16)

| Scenario | Status | Evidence |
|---|---|---|
| CP-01 crash before dispatch | **Safe, not tested as a crash** | An unsent permit expires in 5 s; on restart the run is stopped, nothing resumes |
| CP-02 crash after dispatch, before acknowledgement | **Working** | Lost answer stays in doubt, then settled from controller state |
| CP-03 executed before checkpoint | **Partial** | Same reconciliation covers it; not tested as a crash |
| CP-04 duplicate delivery | **Working** | Replay refused at the backend and at the simulator |
| CP-05 changed world state | **Working** | Old-world permit refused |
| CP-06 revoked mission or kill switch while offline | **Working** | Kill switch survives restart (`test_kill_switch_stops_robot_voids_permits_and_survives_restart`) |
| CP-07 corrupt or missing checkpoint | **Partial** | Journal tampering detected; no restore from backup |
| CP-08 recovery under dependency outage | **Partial** | Missing permit secret fails closed; planner outage falls back (pre-existing). Not tested as a restart |

## Live check (1 Nov 2026)

Simulator and backend run as separate processes over HTTP, with a shared random permit secret:

1. Mission started: the robot drove the route; every move went out with a permit (7 of 7 in the first 12 s).
2. Direct command to the simulator without a permit: **HTTP 403 `permit_required`**.
3. Global kill switch: authority revoked in **16 ms**, controller stop confirmed in **453 ms**; the run loop's next 5 moves were refused (`kill_switch_active`).
4. Reset without login: **HTTP 401**. Reset as an operator: e-stop released, the robot resumed with fresh permits.
