# Changelog

Work done during the Meta Global AI Developer Hackathon (building period 27 Oct – 4 Nov 2026).
The first commit in this repository is the pre-existing codebase; everything listed here came after it.

## 2026-11-01

- **Execution-authority package** (`backend/app/autonomy/`), with 26 tests in `backend/tests/test_autonomy.py`:
  - Signed, short-lived, single-use permits bound to one exact action, robot, mission and world-state version. Replayed, tampered, expired, mismatched and stale permits are rejected; a permit used by several callers at once succeeds exactly once.
  - Kill switches at global, robot, mission and agent scope. Activating or resetting one voids every outstanding permit; resets require authorization.
  - Versioned world state that only moves forward and refuses stale observations.
  - Durable mission checkpoints with a hash-chained event journal. Every dispatched action is marked in doubt until reconciled against the controller, and is never retried blindly.
  - Full-path checks (bounds, restricted zones, obstacle clearance) sampled along every segment.
  - Graph routing (NetworkX) with hard no-go edges that learning cannot change, and learned edge delays.
  - Signed experience records; forged or invalid records are quarantined.
  - Canary markers, mission action allowlists, action budgets, a dispatch watchdog and exclusive corridor reservations.
  - A single dispatch path: watchdog, permit, budget, mark in doubt, then send.
- **Execution authority wired in** (`app/services/execution_authority.py`, 14 end-to-end tests):
  - Every approved move gets a permit and goes through the one dispatch path; the run loop re-reads telemetry before the gate if planning was slow, so permits bind to fresh state.
  - The warehouse simulator checks each move's permit itself against the exact command it received and refuses missing, altered, forged, expired, reused and wrong-robot permits. STOP never needs one.
  - Controller e-stop: engaged by global and robot kill switches, released only with a backend-signed token.
  - Dead-man stop in the simulator: the robot brakes if permitted moves stop arriving (default 5 s).
  - Kill-switch API (`/authority/kill`, `/authority/reset`, `/authority/status`, `/authority/evidence`): stopping is open to anyone; reset needs an operator login. Locks are stored on disk and survive restarts. Each kill reports revocation and verified-stop times.
  - Moves whose answer is lost are settled from the simulator's actual target, never retried.
- `/llm/execute` no longer executes NEEDS_REVIEW moves; only APPROVED moves run, each with a permit.
- Operator approvals now expire (120 s).
- `PERMIT_SECRET` is required by Docker Compose and in production.
- `docs/TRACEABILITY.md`: every planned capability with its status and evidence.
- **Meta models**: Muse Spark plans missions with the robot camera frame attached; Muse Spark Open on Baseten proposes steps; SAM 3.1 reads the camera, with detections projected onto the floor and cross-checked; Muse Voice Transcribe turns a spoken stop into a kill switch (voice can never start the robot). `scripts/check_meta.py` checks real keys.
- **Learned routing**: the live router runs on NetworkX; racks and hazard zones are hard limits; delays learned from where runs were slowed or stopped steer the route. Experience is signed; forged or edited records are quarantined.
- **Canary tripwire** on every mission plan; a plan that obeys it is discarded.
- **Full-path check** before every permit (people, obstacles, hazard zones, bounds).
- **Restart recovery**: interrupted runs are paused, not failed; resume refuses under a kill switch, settles uncertain moves with the controller and continues from the last confirmed waypoint.
- **Security drills** (`/authority/drills`): bypass, tampered, replayed and forged permits, poisoned memory, injected site text, canary, kill switch, each against the live simulator.
- **Dashboard**: new Authority page (kill switches, voice stop, reset, drills, live permit events), authority controls on every run, Overview rewritten around the hackathon work with "New" and "Earlier work" labels.
- **Observability**: Prometheus `/metrics` for the safety path; Grafana dashboard rebuilt on those metrics.
- **LangSmith tracing**: one trace per mission (planning calls with prompt and answer, plan, each gate decision, each permit used or refused, canary trips), plus kill switches, resets and drills. Off without `LANGSMITH_API_KEY`; never blocks a safety decision; camera images and keys are never sent.
- **Roles and sign-in**: viewer < operator < admin, with password-hashed accounts (`AUTH_ACCOUNTS`, `scripts/add_account.py`) and `/auth/login`. Stopping stays open to everyone; mission control, approvals, kill-switch reset and drills need an operator; activating or rolling back safety rules needs an admin. Enforced in production; in development a token that is sent must still carry the role. Sign-in control in the dashboard; every write carries the token.
- **Backup and restore** (`python -m app.ops.backup create|verify|restore`): consistent copies of the app and authority databases (or a PostgreSQL dump) with a signed manifest; tampered, partial or foreign backups are refused; restore needs the backend stopped. After a full loss and restore, kill switches still hold and used permits stay used. `docs/RUNBOOK.md` sets recovery objectives and the incident steps.
- **Safety case** (`docs/SAFETY_CASE.md`): the claim, assumptions, 15 hazards each linked to its controls and to the tests and drills that show them working, and the residual risks, including that every person contact left in the benchmark happens while the robot is already braking.
- **OpenTelemetry**: the same mission tracing also goes out as OTLP/HTTP spans when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (mission → model calls, gate decisions, permits; kill switches and drills on their own). Prompt text stays out of OpenTelemetry; LangSmith holds full model input and output.
