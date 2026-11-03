# Operator controls validation - 3 November 2026

Implementation: [operational oversight](../../OPERATOR_CONTROLS.md).

The earlier record-only replan/force_approve actions now perform checked actions.
Replan leaves a verified stop and a persisted replacement route, with explicit
resume. Review approval accepts only a selected eligible uncertainty decision;
hard/operational limits still cannot be overridden.

## Backend checks

The focused regression run passed **87 tests**, before the final hardening and acknowledgement-race fix. The final oversight suite contains
**33 cases**, including the signed-lease tampering checks. Those cover API identity/state checks, route persistence/restoration,
no-route and failed replacement holds, exact review binding, controller/map/
platform/constraint changes, expiry, kill epochs, hard-limit rejection, duplicate
requests, in-flight tick settlement and isolation from candidate-rule replay.

The real-controller test supplies explicitly test-only uncertainty observations
to the backend adapter, then uses the real signed redemption API and simulator
physics to verify review -> permit -> humanoid movement -> replan -> stop. This
is not a production uncertainty-injection or bypass endpoint. STOP confirmation
waits for actual deceleration rather than treating acknowledgement as zero speed.

The first full regression run exposed fixture map leakage (pharma geometry left
active for later warehouse tests) and a fixed-delay movement assertion. The
fixture now restores the previous gate map, and motion is checked by a bounded
wait for measured displacement. These corrections preserve the assertions about
safe admission and actual movement. The final full-suite result is recorded below.

## Browser checks

`browser-report.json` contains the real isolated service results for Mission
Control and the retained run page. The check creates a real humanoid mission,
replans and holds from each UI, explicitly resumes, inspects saved speed-capped
waypoints and stationary telemetry, checks ordinary paused requests cannot be
force-approved, verifies responsive controls and validates the event chain.

An initial responsive run found a 3-pixel overflow in the legacy planning form
when the run was paused after execution. The input now has zero minimum width,
the form stacks on mobile, and its label reflects paused state. The exploratory
failure capture is retained as `failure-mobile.png`; final captures and report
identify the corrected version.

Screenshots: `mission-control-oversight.png`, `run-oversight.png`,
`oversight-390.png`, `oversight-1440.png`.

## Reproduce

Use the isolated stack in `scripts/browser_validation_stack.py`, pharma layout,
ports 19300/18080/18090 and a freshly built `.next-validation` directory. Run:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest backend/tests -q
# Build before starting the isolated stack:
$env:NEXT_DIST_DIR='.next-validation'
$env:BACKEND_URL='http://127.0.0.1:18080'
npm --prefix frontend run build
$env:BROWSER_SITE_LAYOUT='pharma'
.\.venv\Scripts\python.exe scripts/browser_validation_stack.py
# Another terminal, sequentially:
node tests/operator-controls.browser.cjs
```

No paid model calls or physical robot control are used. Changes remain local.

A later live rerun caught an acknowledgement race in the initial cancellation
approach. The final implementation sends STOP first, blocks further paused
moves, waits for the current tick to record its result, then stops the idle loop.
A real-controller delayed-response test verifies the old move is fenced and no
uncertain action is created by the intervention. Resume cannot overtake an
unsettled paused tick. This preserves the existing conservative reconciliation
contract rather than guessing the outcome of a spent permit.

## Final result

**489 backend tests passed in 244.19 seconds**, including all **33 oversight
cases** and the deterministic delayed-controller-acknowledgement regression.
The production Next.js build and TypeScript checks passed.
**5 oversight browser checks and 10 existing Mission Control browser checks
passed**, with no browser errors. Mobile scroll width equals its 390-pixel
viewport; desktop scroll width equals its 1440-pixel viewport. Both successful
interventions remain hash-chain verifiable.

The final results apply after signed-lease hardening, tick settlement and the
mobile planning-form correction. `verification.json` summarizes the observed
results; `browser-report.json` and `mission-control/browser-report.json` contain
the browser checks. The earlier exploratory failure capture includes the
acknowledgement race; final screenshots and passing reports show the corrected
version. Preview services remain available at port 19300. Changes are local,
uncommitted and unpushed.
