# Original design evidence

Baseline: `2d3a984`, before the frontend overhaul. The original frontend,
palette, factory simulator and backend were restored in an isolated snapshot.
The new preview and its state were kept separate.

## Visual inspection

- [Original factory and carrier inspection](01-original-twin-inspection.png)
- [Original robot-eye view](02-original-robot-eye.png)
- [Original draft setup](03-original-mission-draft.png)

The 3D screenshots use the original low-quality scene with a test-host animation
cap. The software renderer reached roughly 1 FPS, causing stale-telemetry
indicators. They establish appearance and visible controls, not acceptable
production performance. Later workflow captures use WebGL fallback.

## Run-detail inspection

- [Run layout and planning/evidence panels](04-original-active-run.png)
- [Learning and task](05-learning-task.png)
- [Chain and telemetry](05-chain-telemetry.png)
- [Alerts](05-alerts.png)
- [Analysis](05-analysis.png)
- [Obstruction response](06-original-blocked-route.png)
- [Retained stopped record](08-original-stopped-record.png)
- [Coverage and limitations](review-summary.json)

The original draft/start journey, run navigation and panel structure were
reviewed in real services. Model keys were disabled, so model-dependent analysis
and perception were source-reviewed rather than validated against live models.
The paused walkthrough can still display the model's route; route display is
distinct from permission for current movement.

The local review script and `study-report.json` describe the final walkthrough.
Earlier attempts are retained separately: one used an overly strict button
selector, and another reused a world where the carrier had already reached the
destination. These are study-harness limitations, not product failure claims.

The final automation remains marked incomplete: the backend confirmed a pause,
but the paused-page reload did not populate mission/world data before the resume
control timed out. A later fresh visit loaded the retained stopped record.
The obstruction hold was confirmed in backend events. Full arrival/completion
and live model services were not exercised. This is a design study with explicit
limits, not an all-passing regression report.

See [original design study and revised plan](../../ORIGINAL_DESIGN_STUDY.md).
