# Operator release is required for historical route reuse

## Behavior

Observation collection stays automatic. Signed route observations are retained
and verified even when no lesson has been released. Verification and corroboration
make evidence eligible for review, not eligible for automatic operational reuse.

Runtime reuse follows:

`observations → candidate → evaluated → approved → released → compatible recipient`

Only a currently released, exact-context version contributes bounded positive
congestion costs. The restriction applies to source robots as well as other
recipients. Approving a version without releasing it has no routing effect.
Existing observation databases are retained; no legacy records are automatically
approved or migrated into released lessons.

## Boundaries closed

- **NetworkX routing:** removed the automatic raw-memory baseline. Released
  caution penalties are the only historical route costs used by the live router.
- **Planner context:** distilled spatial lessons remain audit-only candidates.
  Planning and replanning receive deterministic summaries of released congestion
  cautions, not arbitrary candidate text, operator titles or notice prose.
- **Memgraph planner history:** historical facts must match the source run, robot,
  cell, observation kind and timestamp selected by a current released lesson, in addition to existing source
  integrity, freshness and context checks. Operator graph inspection is retained.
- **Short-term agent feedback:** each run loop owns its agent instance. The agent
  clears short-term memory when robot identity, site/map/policy/capability context
  changes or becomes unavailable. Current-run feedback remains usable without
  silently carrying it into another run or robot.
- **Route simplification:** learned detours keep their bends. Geometry-only
  simplification previously could shortcut straight through a congestion caution.
- **Inspection:** route-lesson preview resolves a current receiving robot.
  Observation counts and released routing counts are labelled separately.

Withdrawal, superseding revision, expiry, evidence invalidation, incompatible
context and unavailable release storage exclude advice on subsequent retrieval.
There is no fallback to unreleased raw costs. Static routing and current safety
rules remain available when historical advice is unavailable.

This change does not install new speed rules, allow model output to grant
movement authority, or implement physical skill transfer. Live sensor reactions,
current-run denial feedback, static maps and safety constraints are not historical
fleet learning and continue to operate without a lesson release.

## Operational limits

Release eligibility is checked at planning/retrieval time. Withdrawing a caution
prevents future retrieval; it is not an emergency stop and does not retroactively
cancel an already issued route or movement permit. Use the existing stop and
replan controls for immediate intervention. Every move still requires current
policy checks and controller admission.

The release ledger's existing protection model is unchanged: tampering detection
depends on protecting the signing secret and independent checkpoint. No new
claim of physical safety certification is made.

## Validation

Run from `backend` with the project virtual environment:

```powershell
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_learning_release.py tests/test_learning_and_canaries.py tests/test_lesson_integrity.py tests/test_operational_graph.py tests/test_planner_lessons.py tests/test_agent_memory_scope.py -q
```

Coverage includes:

- Verified observations, candidates, evaluated versions and approved-but-unreleased
  versions cannot reach runtime router costs, spatial planner context or graph history.
- Exact released versions produce planner advice and route costs; unrelated graph
  evidence stays excluded.
- Withdrawal, revision, expiry, invalidation, all context fields, missing identity
  and storage failure remove runtime advice without a raw-memory fallback.
- A real NetworkX route stays unchanged after collecting observations, detours
  after release, and returns to its original route after withdrawal.
- Signed spatial candidates remain inspectable without becoming planner permission.

The tests use isolated databases and mocked model transports. Optional real
Memgraph integration tests require a separately configured `MEMGRAPH_TEST_URI`.
Local validation is not evidence that an existing deployed service has been
updated; deployment/restart is a separate operational action.

Validation on 4 November 2026: the broader backend run passed 582 tests with four
optional graph cases skipped during implementation. Subsequent focused checks
covering the final learning/prompt/graph/memory changes passed 92 tests with four
optional graph cases skipped. Run-loop, fleet, operator and environment checks
with per-run agent isolation passed 94 tests. Frontend TypeScript checking passed.
These runs overlap and their counts must not be added together.
