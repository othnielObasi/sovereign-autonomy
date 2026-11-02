# Operations runbook

What to do when something goes wrong. Commands run from `backend/` with the same
`.env` as the backend. This covers one site with one backend; a multi-site fleet
would need replication and failover that are not built.

## Recovery objectives

| Objective | Target | How it is met |
|---|---|---|
| Recovery point (data you can lose) | ≤ 1 hour | Hourly backup (cron below) |
| Recovery time (back to safe operation) | ≤ 15 minutes | Restore takes seconds; the rest is starting services and an operator check |
| Safe state during recovery | Robot stopped | The simulator's dead-man stop brakes the robot within 5 s of the backend going away; interrupted runs come back **paused** |

The restore itself is measured by `tests/test_backup_restore.py::test_full_loss_then_restore` (under 5 s for the test data).

## What is backed up

| File | Contents |
|---|---|
| `app.db` (SQLite) or `app.sql` (PostgreSQL dump) | Missions, runs, hash-chained events, signed decision receipts, rule versions |
| `authority.db` | Permit journal, action reconciliation, kill switches, learning memory |
| `experience-anchor.db` (when learning ledger exists) | Separate signed learning checkpoint, coordinated with `authority.db` |
| `manifest.json` | Size and SHA-256 of each file, signed with a key derived from `PERMIT_SECRET` |

Not in the backup, by design: the receipt signing key and every other secret. Keep them in
the secret store (`RECEIPT_SIGNING_KEY`, `PERMIT_SECRET`, `JWT_SECRET`, model keys). A restore
on a new server needs the same `PERMIT_SECRET`, or the manifest will not verify.

## Routine backups

```bash
python -m app.ops.backup create --out /var/backups/sovereign      # prints the backup folder
python -m app.ops.backup verify /var/backups/sovereign/<stamp>     # exit code 0 = good
```

Cron, hourly, keeping a week:

```
0 * * * * cd /opt/sovereign-autonomy/backend && python -m app.ops.backup create --out /var/backups/sovereign && find /var/backups/sovereign -maxdepth 1 -mtime +7 -exec rm -rf {} +
```

Copy backups off the server. A backup taken while the backend runs is consistent
(SQLite online backup API).

## Restore after data loss

1. **Make the robot safe.** Press *Stop everything* (or `POST /authority/kill {"scope":"global"}`) if the backend is still up. If it is down, the simulator's dead-man stop has already braked the robot.
2. **Stop the backend.**
3. **Verify, then restore** the newest good backup:
   ```bash
   python -m app.ops.backup verify  /var/backups/sovereign/<stamp>
   python -m app.ops.backup restore /var/backups/sovereign/<stamp> --backend-stopped
   ```
   A tampered, partial or foreign backup is refused. The files being replaced are kept as `*.before-restore`.
4. **Start the backend.** Runs that were in progress come back **paused**, never resumed on their own.
5. **Check before resuming:** `/authority/status` shows kill switches (they survive a restore) and `journal_intact: true`.
6. **Resume** each paused run from the dashboard (operator). Resume refuses while a kill switch covers the robot or mission, settles any move whose outcome was lost with the controller, and continues from the last confirmed waypoint. Every move needs a new permit; permits from before the incident expired within seconds.

## Other incidents

| Incident | Response |
|---|---|
| Backend crashed or restarted | The robot brakes (dead-man stop). On restart runs are paused. Operator resumes after checking `/authority/status`. |
| Simulator/controller unreachable | Moves fail closed; the run stops sending. Resume is refused while a move's outcome cannot be settled with the controller. |
| Model API down or slow | The planner falls back to the labelled deterministic route; the gate and permits work as normal. |
| Suspected compromise of a planner | `POST /authority/kill {"scope":"agent","id":"planner:<provider>"}`: its proposals get no permits. |
| Suspected leaked `PERMIT_SECRET` | Stop everything, rotate the secret in backend **and** simulator, restart both. Old permits become invalid at once. |
| Journal integrity alarm (`journal_intact: false`) | Stop everything, keep the database for investigation, restore the last backup that verifies. |
| Planted or edited learning records | Already quarantined automatically (`/authority/learning`); no action needed beyond investigation. |

## Drills

### Experience memory after upgrade or layout changes

The context-aware learning upgrade preserves legacy rows but excludes records without original site/map/policy/capability context. A lower eligible-cell count after upgrade is expected; do not assign the active site's identity to old data to restore the count. New runs accumulate scoped observations from decision receipts.

Inspect `/authority/learning` for `experience_context`, `excluded`, `quarantined`, and per-record reasons. Missing current context means no memory is eligible. Corrupt lifecycle records disable memory retrieval; preserve the database for investigation. Memory invalidation controls reuse; use the stop workflow for an operational incident. Automatic environment propagation and controller fencing are implemented as described below.

### Controller admission and journal incidents

- Upgrade backend and warehouse simulator together. Set `AUTHORITY_BASE_URL` in the simulator to the reachable backend address and preserve `SIM_STATE_DB`; Compose mounts `controller_data:/app/data`.
- A callback outage causes a definite controller refusal, followed by a best-effort containment STOP from dispatch. Check the backend callback address, reachability, and matching `PERMIT_SECRET`. Do not disable redemption to restore movement.
- Authority restart advances its persisted epoch. Controller restart changes its boot identity. Old permits stay invalid even when numeric world versions start again. E-stops and consumed release tokens persist in the controller journal.
- A lost command response remains `IN_DOUBT` until admission evidence settles it. If the authority spent a permit but the controller cannot prove admission, recovery deliberately stays blocked. Preserve both journals and investigate; do not clear checkpoints or reissue the action to force recovery.
- The existing signed backup tool covers the application and authority databases, not `SIM_STATE_DB`. Preserve/snapshot the controller volume separately while services are stopped. If it is lost, a redeemed uncertain action may require manual investigation; target matching alone is insufficient.
- These controls cover simulated navigation command admission. They do not establish safe retry semantics for physical manipulation or certify a physical emergency stop.

### Security drills

Run `/authority/drills` (Authority page) after any restore or upgrade: eight real attacks
against the live simulator, all of which must be blocked.
# Automatic environment revalidation

Scenario/seed changes stop simulator targets and advance the operational map generation before new movement admission. Operators must re-observe telemetry and obtain fresh permits. Backend lifecycle snapshots and signed invalidation events use the authority database; preserve it together with the controller database across restarts.

Active runs discard obsolete routes and audit `ENVIRONMENT_CHANGE` plus `EXPERIENCE_RETRIEVAL`. `holding_no_route` means the robot remains stopped while the planner retries; inspect constraints and restore a traversable route. `replanned` means a replacement exists, not that motion or the mission completed. Authority and mission learning panels show compatibility decisions and propagation delay. Constraint changes invalidate observations up to the event cutoff; map changes require a new generation.

Run `python -m bench.experience_eval --seeds 20 --out bench/results/experience` from `backend` to reproduce the deterministic graph benchmark. For browser checks, build the frontend with `NEXT_DIST_DIR=.next-validation` and `BACKEND_URL=http://127.0.0.1:18080`, start `scripts/browser_validation_stack.py` with the project Python from the repository root, then run `node tests/experience.browser.cjs`. Ports 19300/18080/18090 are isolated loopback services; the fixture is synthetic and no model calls are made. Create `backend/data/browser-validation/stop` to terminate these services. Do not point this harness at a deployment.

## Shared-learning integrity incidents

See [LEARNING_POISONING_DEFENSES.md](LEARNING_POISONING_DEFENSES.md). `advisory` / `independent_source_required` is expected until a second robot corroborates the cell. `source_quarantined` suppresses that source's learning for the exact context; investigate sensors and traffic timing before treating it as malicious. It is not a motor stop.

An `integrity_error` disables learned routing and new memory writes. Preserve the authority database, its ledger, and `EXPERIENCE_ANCHOR_PATH` checkpoint. Fresh telemetry, STOP, deterministic routing and controller admission remain independent. Do not fix an error by deleting or recreating the checkpoint or quarantine rows.

`app.ops.backup` captures the authority database and learning checkpoint in a shared attached-database read transaction, verifies their ledger/checkpoint pair, and includes `experience-anchor.db` in the signed manifest. Restore requires a stopped backend and explicitly restores both to the configured locations. Missing or inconsistent checkpoints refuse backup/verification; do not bypass this by deleting the checkpoint. Restoring only an older authority database against the current checkpoint intentionally disables reuse. Compose provides a separate `/anchors` volume writable by the backend user, but independent administrative access controls are the operator's responsibility. Do not enable WAL on either file.

Unsigned older planner lessons remain quarantined for inspection and are not re-signed. Collect fresh signed gate evidence to generate new lessons. Receipt-key rotation can make old receipts unavailable for distillation unless their verification keys are retained by a trusted mechanism.
