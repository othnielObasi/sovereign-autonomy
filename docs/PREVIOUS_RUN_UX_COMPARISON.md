# Previous run experience compared with Mission Control

Reviewed 3 November 2026. This is a source-level comparison, supported by the
earlier real-service browser workflow report in
`validation/2026-11-02-poisoning/browser-results.json`. That earlier run used
WebGL fallback; it does not establish visual parity between the two 3D scenes.

## Previous journey

`/twin` opens an immersive scene. Plan mission opens `MissionControls`, where
the operator chooses a bay or open floor, saves a draft and starts a governed
run. Start then navigates to `/runs/{runId}`. The detailed execution experience
therefore lives on the run page as well as in the twin renderer.

The run page consumes plan events, live planning progress, decisions, path
previews, executed telemetry paths, risk cells and safety reports. It passes
these to the shared warehouse renderer and displays additional evidence panels.

## Presentation parity

| Detail | Previous experience | New Mission Control |
|---|---|---|
| Cameras | Overview, follow, robot eye; fullscreen and reset | Three perspectives implemented; explicit fullscreen/reset still absent |
| Route layers | Proposed path, plan waypoints and executed path displayed separately | Current controller target only; full route layers not migrated |
| Waypoints | Coordinate and speed-cap inspection; highlighted waypoint list | Not migrated into the main workspace |
| Safety | Stop/slow thresholds, nearby clearances, state and refusal feedback | Stop controls and decision summary; policy-distance overlays not migrated |
| Actor inspection | Robot, person and obstacle details, including position, activity and distance | Carrier selection, position and speed; detailed inspection not migrated |
| Navigation aids | Minimap, trail, risk heatmap, layer toggles | Facility view and SVG floor plan; extra layers not migrated |
| Robot-eye HUD | Gate, speed and world-projected detections explicitly labelled simulated | Perspective camera implemented; HUD not migrated |
| Execution evidence | Policy IDs/reasons, required action, chain, telemetry, learning and alerts | Compact decision trail plus a link to the retained full run record |
| Mission preparation | Bay or floor selection; explicit draft-save step | Bay selection and combined create/start with retryable saved draft |
| Scenario controls | Human proximity, blockage, spill, forklift and clear | Human approach, blockage and clear in the main workspace |

## Implementation priorities

1. Bring active-run evidence alongside the new scene: current action, actual
   decision and policy reasons, clearance values and controller admission.
2. Add separate route layers and waypoint details. A plan is not an execution
   permit; changed environment context must invalidate its current-route display.
   Keep historical routes visibly distinguishable from the current route.
3. Add detailed actor inspection, measured executed trail, minimap and optional
   risk/safety overlays, using current backend data and policy thresholds.
4. Restore floor selection, fuller scenario controls and camera navigation aids.

Port the useful information rather than every old indicator. Some older labels
and progress highlights are derived in the frontend, and waypoint highlighting
can be changed by clicking. Controller-confirmed progress must come from run
events and telemetry. World-projected detections must remain labelled simulated
and separate from configured model perception.

The realism update improves rendering; it is not full operational-detail parity.

## Follow-up implementation

The comparison above records the earlier redesign, before the workspace
completion pass. Mission Control now has an expandable detailed warehouse using
the same interactive renderer as the retained run page. It provides cameras,
fullscreen/reset, recorded plan and travelled path layers, waypoint inspection,
actor inspection, minimap, risk/trail/safety layers and the simulated robot-eye
HUD. Latest recorded decision policy IDs/reasons/required action and live
platform/clearance values are shown alongside it. Floor destinations, explicit
save-draft and the complete six-scenario set are available in the composer/lab.
The main summary view stays compact; extended historical analysis remains on the
retained run/evidence pages. These additions require their own validation and do
not retroactively change the earlier comparison results.
