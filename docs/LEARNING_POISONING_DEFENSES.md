# Shared-learning poisoning defenses

The gate and controller remain the movement authority. Learning is advisory and cannot authorize a move, remove a restricted edge, change policy, or validate sensor truth.

## Routing policy

Only records with valid signatures, compatible site/map/policy/capability context, valid age, and an anchored inventory entry are candidates. A single robot's observations remain visible as **advisory**. Multiple missions from that robot do not provide corroboration.

New route records and planner lessons are distilled only from gate rows whose Ed25519 receipt verifies. Unsigned historical decisions, changed telemetry, changed policy hits and changed verdicts are excluded rather than laundered into freshly signed memory. This verifies what the backend recorded, not whether a sensor was truthful. Receipt key rotation without a trusted verification-key history may make old decisions ineligible for further distillation.

For each cell, keep each distinct robot's largest age-decayed delay. Select the two largest source peaks and clip both to the smaller value; their equal-weight average is the learned cost. Thus each selected source supplies at most 50% of the supporting vote, a lone extreme cannot raise the cost above its corroborator, and flooding mild records cannot dilute a previous stop. Other sources remain advisory. The maximum observation is 60 seconds; costs are nonnegative and decay/expire as before. This favors conservative historical peaks until they decay or are invalidated; it can retain congestion longer than a mean.

Source identity is the identity captured in the backend's governance telemetry. Distinct IDs are not independent hardware attestation. A compromised adapter that can impersonate multiple robots, colluding robots, compromised signing keys, or corrupted telemetry can defeat the independence assumption.

## Source quarantine

A source is quarantined for an exact context after high outliers in at least three cells, each compared with at least two agreeing peers. Peers must be within 0.5 seconds of their median; the source peak must be at least 3.5 seconds, at least 2.5 times the peer median, and at least two seconds higher. This includes false four-second stop observations against 1.5-second slow observations.

The signed quarantine survives restart and affects both routing and planner lesson retrieval. It does not stop the robot or revoke movement authority. It is an anomaly heuristic: differing traffic times can legitimately produce disagreement. Do not call it proof of maliciousness. A newly revalidated context has a separate scope. There is no automatic trust restoration or public endpoint that clears source quarantine; investigate before an explicit, audited remediation. Never delete quarantine rows to restore learning.

Two agreeing peers require at least three robot identities. The current two-robot simulator can corroborate shared costs, but cannot automatically identify a liar from peer disagreement alone. The poisoning drill includes a third synthetic source to exercise that conditional defense.

## Integrity and deletion detection

`memory_ledger` chains signed inventory entries for route records, invalidations and source quarantine. A signed head is committed in a **separate SQLite file** via an attached rollback-journal transaction. It detects removed records, removed quarantine/invalidation rows, chain truncation, missing checkpoints and rollback of the main database relative to the checkpoint. Ordinary row signatures still detect record edits. Extra forged records are quarantined, not adopted into the inventory.

`EXPERIENCE_ANCHOR_PATH` selects the checkpoint file. By default it is `<authority DB>.anchor.sqlite`; Compose mounts a separate `memory_anchor_data` volume at `/anchors`. A separate file/volume is not an external trusted service: an administrator controlling both files can roll both back. To establish an independent trust boundary, place the configured checkpoint under separately managed storage/access controls. This implementation does not provision a remote immutable anchor or claim protection against host/root or signing-key compromise.

SQLite WAL and in-memory journals are refused for these cross-file transactions. Do not switch either database to WAL. Keep checkpoints associated with their original database and signing secret. The initial additive migration anchors existing inventory as found, while still verifying record signatures; it cannot detect deletions that happened before the migration. Unanchored records inserted afterward are not reused.

An integrity failure disables memory reuse and prevents new learning writes. It does not hide fresh simulator telemetry or disable STOP; deterministic planning, current governance and controller admission remain independent. The authority dashboard reports the failure. Preserve both files for investigation; do not erase the checkpoint or automatically rebuild it from a suspect database.

`app.ops.backup` copies both files under one attached-database read transaction and verifies the resulting pair. The signed manifest includes `experience-anchor.db`; a missing checkpoint refuses backup. A stopped-backend restore restores both files to their configured locations, making it an explicit operator-authorized recovery from a trusted backup. Restoring only an older main database against a newer checkpoint intentionally disables reuse. There is no automatic reset command.

## Planner lessons

New lessons use schema 3 and a domain-separated HMAC bound to the actual row ID. All retrieval, inspection and aggregation verify signatures and typed, bounded fields, including policy/zone identifiers, context, counters, coordinates, source/run lists, timestamps and regenerated template text. Copying content to another row invalidates its signature. Unsigned schema-2 lessons remain inspectable as quarantined evidence; they are not silently signed, merged or fed to a prompt.

Two non-quarantined source identities are required for operational lesson retrieval. Ranking caps the denial and run multipliers. Lesson signatures detect edits/transplants, but lesson deletion or rollback in the application database is not independently checkpointed by the route inventory. A privileged database writer remains a threat; this document does not claim complete poisoning prevention.

## Drill and validation

The authority page's **Run all drills** includes `poisoning`: single-source suppression, mild-record flooding, forgery, repeated source outliers, vote limits, an out-of-bounds proposal refused by the real deterministic gate, and deletion detection. These attacks use the actual memory implementation in a temporary store, never live mission memory. Every sub-check is displayed individually. No model, sensor-truth, physical contact, or hardware safety claim follows from a passing drill.

Tests: `test_learning_poisoning.py`, `test_lesson_integrity.py`, and the context/lifecycle/planner regression cases. The hardened graph benchmark requires two acquisition robots before the held-out robot can use their shared experience; the original single-source benchmark artifact remains historical evidence of the previous policy.

Validation: [saved results and screenshots](validation/2026-11-02-poisoning/README.md), including 440 regression passes, 48 final focused recovery/security passes, a production frontend build, and a passing real-service browser run with all seven poisoning sub-checks. The hardened graph experiment retains 28.6% modeled benefit and rejects 30/30 stale records under two-source corroboration.
