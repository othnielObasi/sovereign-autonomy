# Shared-learning poisoning validation — 2 November 2026

## Automated checks

- Full backend regression after core hardening and gate-receipt validation: **440 passed in 197.36 seconds**.
- Final backup/integrity/lesson suite after adding checkpoint-aware recovery and unreadable-checkpoint handling: **48 passed in 7.63 seconds** (`test_backup_restore.py`, `test_learning_poisoning.py`, `test_lesson_integrity.py`). This overlaps the full suite; do not add these counts as independent cases.
- Production frontend `.next-validation` build: compiled, linted, type-checked and generated all 13 pages.
- Source whitespace check: `git diff --check` passed.

The tests exercise source corroboration, repeated-source flooding, mild-record dilution, one-source extreme costs, false four-second stop observations, persistent source quarantine, context isolation, forged/unanchored records, inventory and checkpoint deletion, chain truncation, main-database rollback, concurrent writers, transactional rollback, unavailable/WAL checkpoints, malformed/transplanted/unsigned lessons, altered gate receipts, live backup consistency, and checkpoint-pair recovery.

## Browser evidence

[browser-results.json](browser-results.json) records a passing seven-step run against the real isolated simulator/backend/production frontend. WebGL was deliberately disabled and external requests blocked. Both acquisition records are synthetic and clearly labelled `robot-A (fixture)` and `robot-C (fixture)`. Model and tracing credentials are disabled, and receipt keys, databases and checkpoints are isolated per launch.

The UI created and started a mission, showed a stopped `holding_no_route` transition after a pallet change, then a replacement route with 22 waypoints after clearing it. Old experience was excluded. Pause, kill, refused resume, signed operator reset and UI resume matched actual controller state.

The authority page's **Run all drills** returned all executed drills passing: **8/8**, with the live-model canary explicitly skipped because no model was configured. The poisoning drill displayed **seven passing sub-checks**: single-source advisory status, dilution resistance, forgery rejection, source quarantine, bounded votes, an out-of-bounds proposal refused by the deterministic gate, and deletion disabling reuse. Its attacks use the real memory implementation in a temporary store, leaving mission memory untouched.

[poisoning-drill.png](poisoning-drill.png) was visually inspected. Other screenshots capture fixture provenance, exclusion, replanning and usable mission/stop controls after WebGL failure. The isolated services were stopped after validation.

## Modeled benefit and limits

The [hardened graph experiment](../../../backend/bench/results/experience-hardened/README.md) uses two acquisition sources before a held-out robot can reuse costs. Across 20 seeds, modeled travel-plus-queue time decreased **28.6%**, paired mean saving **8.805 seconds**, bootstrap 95% interval **[6.1, 11.61]**. All **30** deliberately stale records were rejected and no restricted graph edge was selected.

This does not establish physical performance, hardware safety, independent sensor truth, live-model quality, or resistance to colluding/impersonated source IDs. Source quarantine requires at least three identities. A separate local checkpoint detects main-database rollback; independently protected checkpoint storage remains a deployment requirement. Lesson edits are signed/validated, but lesson deletion/rollback is not separately anchored. Docker configuration was inspected; no image build is claimed. See [the defense design](../../LEARNING_POISONING_DEFENSES.md).
