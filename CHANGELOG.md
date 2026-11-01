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
- Not yet wired into the run loop or the simulator; that is the next step.
