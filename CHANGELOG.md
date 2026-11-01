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
