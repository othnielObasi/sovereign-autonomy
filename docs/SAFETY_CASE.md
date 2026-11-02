# Safety case

**Claim.** In the simulated warehouse, an AI planner cannot make the robot perform a move
that the deterministic rules forbid, cannot move it without a fresh single-use authorization
for that exact move, and any operator can stop it at once.

**Scope and status.** This is a software safety argument for a simulation. It is **not** a
certification and does not cover a physical robot. A real deployment would need a hazard
analysis to ISO 12100, a safety-rated stop (ISO 13849 / IEC 61508), mobile-robot safety
functions (ISO 3691-4) and an independent assessment. Simulation results show the design
works as intended; they are not evidence about real-world risk.

Evidence names refer to automated tests in `backend/tests/` (run on every change), to the
security drills (`/authority/drills`, run against the live simulator), and to the seeded
safety benchmark (`backend/bench/results/`). "Earlier work" marks controls that pre-date the
hackathon. Status of every capability: [`TRACEABILITY.md`](TRACEABILITY.md).

## Assumptions

| # | Assumption | If it fails |
|---|---|---|
| A1 | The simulator's telemetry (positions, people, obstacles) is correct | Real robots need sensor fusion and calibration; perception is cross-checked but sensors are trusted |
| A2 | `PERMIT_SECRET` is known only to the backend and the controller | Rotate it (RUNBOOK); a leaked secret lets an attacker forge permits |
| A3 | The controller checks permits before moving (it is the last line) | A controller that ignores permits removes the execution boundary |
| A4 | One backend process (any number of robots) | Multi-replica backends need a shared permit and reservation store, and fencing |
| A5 | People and vehicles are treated as static between ticks (~0.5–1 s) | See residual risk R1 |

## Hazards, controls and evidence

| ID | Hazard | Controls (layered) | Evidence |
|---|---|---|---|
| H1 | Robot strikes a person | Gate: human proximity stop/slow, worker proximity, speed near people (earlier work). Permit: full path refused if it passes within 1 m of a person. Perception: unconfirmed sightings add slow zones only. | `test_governance.py::test_human_clearance_denies_high_speed_near_human`; `test_permit_refused_when_the_path_runs_through_a_person_or_obstacle`; benchmark: person contacts 117 → 38 → 9 (no gate → gate → gate + learning), **all remaining contacts while the robot was already braking** |
| H2 | Robot strikes racking, a machine or an obstacle | Gate: path-through-structure and obstacle clearance (earlier work), now checked against the site the simulator actually runs (synced at startup and on every map read). Router: structure is a hard limit in the NetworkX graph. Permit: path check against obstacles. | `test_gate_refuses_a_move_through_racking`; `test_gate_checks_the_site_the_simulator_runs`; `test_backend_startup_syncs_the_gate_with_the_simulator`; `test_learning_never_opens_a_blocked_area` |
| H3 | Robot enters a hazard (spill, dropped load) | Hazard exclusion and slow zones (earlier work); permit path check refuses entry; router avoids them | `test_permit_refused_when_the_path_runs_through_a_person_or_obstacle` (hazard case); site-intel tests |
| H4 | The model proposes an unsafe or hijacked action | The model only proposes; the deterministic gate decides; only APPROVED decisions get permits; NEEDS_REVIEW never executes; task-drift guard (earlier work); canary tripwire discards plans that obey hidden instructions | `test_only_approved_decisions_get_permits`; `test_denied_moves_stop_the_robot_and_never_execute`; canary tests; drill `canary` (Muse Spark ignored it live; an earlier non-Meta planner, since removed, obeyed it) |
| H5 | A command bypasses governance and goes straight to the controller | The controller refuses any move without a valid permit for exactly that command | `test_simulator_refuses_altered_forged_expired_and_wrong_robot`; drills `bypass`, `tamper`, `forged` |
| H6 | A command is replayed or duplicated, repeating a motion | Single-use permits (backend and controller); action journal; lost answers settled from controller state, never retried | `test_permit_used_concurrently_succeeds_once`; `test_lost_acknowledgement_is_settled_from_controller_state`; drill `replay` |
| H7 | A decision is based on stale world state | Versioned world state; telemetry re-read before the gate if planning was slow; permits bound to the world version and refused when stale | `test_stale_world_state_gets_no_permit`; `test_permit_rejected_after_world_changes` |
| H8 | An operator cannot stop the robot, or the stop fails | Kill switches at four scopes, open to everyone; controller e-stop; stop verified from telemetry and timed; spoken stop that can never start the robot | `test_kill_switch_stops_robot_voids_permits_and_survives_restart`; `test_voice_intent_only_ever_stops`; drill `kill`; live: revoked 16 ms, stop verified 453 ms |
| H9 | Authority comes back without a person deciding it | Reset needs a signed-in operator; locks survive restarts and restores; any kill or reset voids every outstanding permit; restarts pause runs | `test_reset_does_not_revive_old_permits`; `test_resume_refused_while_a_kill_switch_is_active`; `test_full_loss_then_restore`; role tests |
| H10 | The backend fails and the robot keeps driving | Controller dead-man stop (5 s); dispatch watchdog | `test_simulator_brakes_when_permitted_moves_stop_arriving` |
| H11 | Poisoned learning steers the robot into danger | Experience records are signed and quarantined if forged; learning only changes route preference, never restrictions; lessons never change rules (earlier work) | `test_signed_experience_counts_and_forged_records_are_quarantined`; drill `poison` |
| H12 | Instructions injected through outside information | Injection firewall (earlier work); outside information can only tighten hazard zones; canary | Site-intel firewall tests; drill `injection` |
| H13 | Safety rules changed without authorization | Rule changes need replay, a second person, versioning and rollback (earlier work); activation and rollback need an admin | `test_governed_rules_and_signing.py`; `test_rule_activation_needs_admin` |
| H14 | Evidence of what happened is lost or altered | Hash-chained events and signed receipts (earlier work); hash-chained action journal; signed, verified backups | `test_checkpoint_tamper_detected`; `test_tampered_or_foreign_backups_are_refused` |
| H15 | A model outage leaves the robot without a plan | Labelled deterministic fallback; gate and permits unchanged | `test_model_outage_falls_back_to_labelled_deterministic_plan` |
| H16 | Two robots collide | Each robot sees the others as obstacles (gate and path check); each move reserves its floor cells first, so overlapping paths are refused; one run per robot | `test_two_robots_cannot_hold_overlapping_paths`; `test_reservation_contention_has_one_winner`; `test_a_robot_never_sees_itself_as_an_obstacle`; live: two missions at once, 0 robot contacts |
| H17 | Authentic but stale or incompatible experience shapes a plan | Site/map/policy/capability filtering, observation-age decay and expiry, and durable memory invalidation; learning remains advisory | `test_experience_context.py`; compatibility, legacy, expiry and invalidation cases in `test_planner_lessons.py` |

## Residual risks

| # | Risk | Why it remains | What would reduce it |
|---|---|---|---|
| R1 | A person walks into the robot while it is braking | Checks treat people as static each tick; there is no motion prediction. Every person contact left in the benchmark is of this kind. | Predict people's paths over the stopping distance; larger slow zones in crossing hotspots |
| R2 | Point-robot path model | The path check samples the robot's centre with fixed margins; no body shape or braking distance | Swept footprint and speed-dependent stopping distance in the path check |
| R3 | Software stop only | The e-stop is software in the controller | A safety-rated hardware stop that does not depend on any software here |
| R4 | Shared-secret permits | HMAC means the controller could in principle forge permits too | Asymmetric signatures (backend signs, controller only verifies) |
| R5 | Single backend process | Permit store, reservations and kill switches are per process (SQLite and memory); two robots are coordinated, but only by one backend | Shared transactional store, fencing tokens, a fleet scheduler |
| R6 | Perception tested only in simulation | SAM 3.1 and the vision cross-check see rendered frames | Real cameras, calibration, and measured miss rates |
| R7 | Model behaviour can change | Models may follow injected instructions (seen live) | Already contained by the gate and permits; keep the canary and drills running |
| R8 | Redemption succeeds but controller admission evidence is unavailable | A lost reply or lost controller journal cannot prove whether a redeemed command was admitted; admission also does not prove physical completion | Current behavior keeps the action uncertain and blocks automatic recovery. Preserve the controller journal and investigate; no blind replay |
| R9 | Lifecycle events are not automatically delivered, or lifecycle records are deleted | Memory invalidation is currently an internal primitive; signatures detect edits but not deletion without an external anchor | Wire authoritative change producers through to planning and execution; independently anchored lifecycle audit |

## How the argument is kept current

Controller redemption now checks current policy, world freshness and durable authority epochs immediately before admission (`test_controller_redemption.py`). Controller boot/generation fences reject pre-restart or overtaken replies; stop/reset operations are locally serialized with admission. This closes the previous direct-delivery revocation gap for the warehouse controller. Automatic external change-event propagation remains partial (R9), and local safety/braking limitations remain (R1-R3).

Every control above has an automated test that runs on each change, and the security drills
run against the live system from the Authority page. When a control or test changes, update
this table and [`TRACEABILITY.md`](TRACEABILITY.md) in the same commit.
# Environment lifecycle evidence (2 November 2026)

Simulator environment mutations fence controller generations and stop targets before new admission. Persisted, signed backend lifecycle events invalidate affected route memory; active runs stop, discard obsolete waypoints, and replan under current context and constraints. No replacement route causes a stopped retry hold. Tests cover restart/idempotency, missed source events, observation cutoffs, hold/release, and real simulator change propagation with old permit refusal.

The learning benchmark is a deterministic graph experiment: 20 paired seeds show 28.6% lower modeled travel-plus-queue time, all 15 deliberately stale records rejected, and zero forbidden graph edges. These results do not measure physical contacts, stopping distance, motor safety, or model training. Signed records do not detect privileged deletion without an external anchor. Hardware adapters require their own authoritative context/event sources.
