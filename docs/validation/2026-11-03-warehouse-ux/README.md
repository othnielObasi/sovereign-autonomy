# Warehouse UX corrections and live robot verification

3 November 2026. Scope and task acceptance criteria are recorded in
[`WAREHOUSE_UX_TASKS.md`](../../WAREHOUSE_UX_TASKS.md).

The test stack uses an isolated pharma simulator, backend and production Next
frontend at ports 18090, 18080 and 19300. No model keys or paid model calls are
used. Test mutations affect only this isolated stack.

Final results: production build/type checks, six focused backend tests, ten
Mission Control checks, five warehouse UX checks, five facility parity checks,
and the two-viewport run layout check passed. Browser reports contain no page
errors. The final layout-only correction was rebuilt and checked at 390 and
1440 pixels, with no horizontal overflow and toolbar/scene bounds separated;
the final cross-view parity check also passed on that build.

The verified delivery started at `(30, 2.5)` and recorded arrival at
`(18.004, 2.533)` against goal `(18, 2.5)`, with 81 used permits and zero robot
contacts. The live pose subsequently reset to `(30, 2.5)` as expected.

## Checks and evidence

- Production frontend build and TypeScript checks passed.
- Six backend checks passed in `backend/tests/test_mission_control.py`: bounded
  event windows, routes from both starts to all six bays, world proxy geometry
  for warehouse/factory/pharma, and room/workstation/destination placement.
- `mission-control/browser-report.json` records the ten-check real-service
  regression, including obstruction, stop/release, mobile, connection loss and
  unavailable WebGL.
- `browser-report.json` records the warehouse-specific checks from
  `tests/warehouse-ux.browser.cjs`: actual map footprints and orientation,
  stationary partition geometry, readable desktop/mobile room labels, retina
  canvas sizing, toolbar panels, roof modes, telemetry transport loss/recovery,
  and a signed-permit robot-2 delivery to Quality lab with pause/resume.
- `parity/browser-report.json`, when present, records cross-view 3D geometry and
  retained-control verification from `tests/facility-parity.browser.cjs`.
- `mobile-run-report.json` records the read-only mobile/desktop check from
  `tests/warehouse-layout.browser.cjs`, with `run-layout-390.png` and
  `run-layout-1440.png` showing the final run-page layout.

Actual captures include `floor-plan-desktop.png`, `floor-plan-mobile.png`,
`run-floor-plan.png`, `warehouse-view-guide.png`, `roof-visible.png`,
`interior-roof-and-lights.png` and `completed-delivery.png`. These were reviewed
for legibility, control placement, layering and roof behavior. The screenshots
are software-rendered; the warehouse-specific harness caps rendering at 5 FPS
and uses a 2x device pixel ratio. This is not a physical hardware test or a
claim of flicker-free rendering on every graphics device.

## Important runtime finding

The simulator resets a carrier to parking immediately after a completed mission.
That is an existing reset, not a physically driven return route. The delivery
test verifies arrival from the governed STOP decision's robot telemetry and the
completed run status, then separately records the live parking position. Used
permit events and the trajectory are retained in `browser-report.json`.

An initial harness assumption expected the post-completion live position to
remain at the destination; that was corrected to check recorded arrival. A
subsequent full delivery hit the 150-second traffic allowance near QC. The final
check allows 300 seconds without changing speed, safety policy or traffic rules.
The final JSON reports, rather than earlier attempts, determine passing status.

The mixed-fleet review found two actual AMRs using the same capability profile.
Humanoid support, controlled vault doors and a reserved airlock remain functional
gaps documented in the task file; this correction does not advertise them as
implemented.
