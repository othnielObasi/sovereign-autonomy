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

Run `/authority/drills` (Authority page) after any restore or upgrade: eight real attacks
against the live simulator, all of which must be blocked.
