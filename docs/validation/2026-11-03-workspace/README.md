# Workspace and mixed-fleet validation

3 November 2026. Local implementation; no commit or push performed for this pass.
The user selected the deeper slate workspace. The original public landing is
preserved; screenshots show the operational app.

## Implemented

- Slate canvas, bright panels, stronger secondary text and input borders. The
  dark green navigation remains. Contrast checks cover visible Mission Control
  text on computed solid backgrounds, excluding disabled controls and SVG/canvas
  content. This is a focused check, not a full WCAG accessibility certification.
- Floor coordinates or 3D floor picking, explicit draft save, all six existing
  scenario types, and detailed inspection directly in Mission Control. It uses
  the retained warehouse renderer for camera/roof/layer/minimap/actor tools.
  Recorded plan waypoints, current controller target, travelled path and current
  platform/clearance are distinct. Recorded decision reasons/policies/required
  action accompany the scene. Picking ends when selecting a bay or launching.
- Two existing AMRs plus robot-3, a humanoid navigator with trusted versioned
  profile, 0.35 m body radius, 1.72 m model and 0.30 m/s speed cap. Gate, authority,
  controller and both route-generation/repair paths enforce the cap. Motion-driven
  articulation and correct camera height appear in both 3D viewers. Reservations
  retain the conservative existing AMR envelope. This is planar simulation, not
  trained biped control, manipulation or a hardware adapter.

## Verification

The full backend suite passed: **456 tests**. The production Next.js build,
including TypeScript checks, passed. After a final peer-telemetry correction,
all 22 focused mixed-fleet, fleet and facility backend tests also passed. The
full 456-test run preceded that last correction. The new mixed-fleet tests cover real
admission/movement/stop, retained AMR isolation, controller and authority speed
rejection, forged profile context rejection, route/repair caps and gate limits.
Existing context applicability tests exclude incompatible capability profiles.

`browser-report.json` records the new seven-check real-service browser workflow,
including measured trajectory, controller-recorded QC arrival, speed/contact
checks, draft-without-motion, mobile layout and both viewers. Its contrast rows
record 109 visible text elements; the earlier confirmed scan minimum was 4.75:1.
Final measurements and run identifiers are in the report. The simulator resets
robots to parking after completion; arrival is verified before that reset.

`mission-control/browser-report.json` and `parity/browser-report.json` retain the
existing regression results. Browser checks must run sequentially on this stack
because they mutate the same simulator; running multiple software-rendered 3D
tests together caused an earlier HTTP timeout. That interrupted run is not counted
as passing. A first backend test fixture used an invalid literal policy version;
it was corrected to the active policy hash before the full suite passed. Visual review then found that peer positions were
being collected after temporarily switching the selected sensing pose. The peer
list is now snapshotted before that switch. Backend and browser assertions compare
its positions with the real fleet API, preventing a duplicate AMR from appearing
under the selected humanoid.

Screenshots: `workspace-desktop.png`, `workspace-mobile.png`,
`humanoid-inspection.png`, `humanoid-run.png`.

## Reproduce (PowerShell)

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest backend/tests -q
$env:NEXT_DIST_DIR='.next-validation'
$env:BACKEND_URL='http://127.0.0.1:18080'
npm --prefix frontend run build
$env:BROWSER_SITE_LAYOUT='pharma'
.\.venv\Scripts\python.exe scripts/browser_validation_stack.py
# Another terminal, sequentially:
node tests/workspace.browser.cjs
$env:BROWSER_EVIDENCE_DIR='docs/validation/2026-11-03-workspace/mission-control'
node tests/mission-control.browser.cjs
$env:BROWSER_EVIDENCE_DIR='docs/validation/2026-11-03-workspace/parity'
node tests/facility-parity.browser.cjs
```

Stop the owned validation stack before rebuilding its `.next-validation` files:
create `backend/data/browser-validation/stop`. The isolated stack uses ports
19300/18080/18090, fresh throwaway databases and no paid model keys. Historical
run URLs in earlier evidence cease to exist after a fresh stack launch.

Final browser results: **7 workspace + 10 Mission Control + 5 facility-parity checks passed**, with no browser errors. Facility comparison: **714 static meshes**. Current contrast scan: **109 text elements**, minimum **4.75:1**. Humanoid arrival recorded at X 18, Y 2.775 (QC target X 18, Y 2.5, within the existing arrival tolerance); sampled speed never exceeded **0.30 m/s**, with **zero robot contacts**.
