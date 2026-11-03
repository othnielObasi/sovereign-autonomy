# Facility realism update — 3 November 2026

The new Mission Control layout is retained. Its facility now uses perspective
views, physical materials, shadows, glass partition frames, room-specific lab
equipment, detailed mobile carriers, forklifts and animated PPE technicians.

- [Overview](mission-control-3d.png)
- [Follow a carrier](facility-follow.png)
- [Robot-eye perspective](facility-robot-eye.png)
- [Mobile](mission-control-mobile.png)
- [WebGL fallback](webgl-fallback.png)
- [Workflow report](browser-report.json)

Positions come from the real isolated simulator. Pose interpolation approaches
received positions without predicting future motion. Equipment is illustrative
geometry within the existing collision footprints; the update does not add
laboratory manipulation capabilities or change movement authorization.

The scene uses local procedural assets. Static equipment is memoized; rendering
pauses offscreen and in background tabs. Software renderers use lower pixel
density, a lower animation cadence and less frequent shadow updates.

Validation uses `scripts/browser_validation_stack.py` with
`BROWSER_SITE_LAYOUT=pharma` and `tests/mission-control.browser.cjs` with
`BROWSER_EVIDENCE_DIR=docs/validation/2026-11-03-facility-realism`.
No paid model calls are made. The stack has throwaway databases and signed
learning fixtures.

Final production build: passed. Browser workflow checks: **10 passed**, with
no unexpected page errors. These include mission creation, controller admission,
obstacle revalidation, pause, stop/release, mobile operation, disconnected
telemetry, WebGL fallback and the three camera perspectives.
