# Original design study and revised overhaul sequence

## Baseline and scope

Study date: 3 November 2026. Baseline: revision `2d3a984`, before the current
frontend overhaul. An isolated snapshot under `backend/data/original-ui-review`
preserves the original frontend, dark palette, backend and factory simulation.
The review uses ports 19310 / 18081 / 18091 and throwaway state, independently
of the new preview. Model credentials are disabled.

Source review covers the original twin, mission controls, run page, scene,
building, equipment, actors, textures, map layers and evidence panels. Original
3D inspection and robot-eye screenshots were captured. Software rendering
reached roughly 1 FPS, so the remaining execution walkthrough uses the original
WebGL fallback. That constraint prevents a full visual-performance comparison.

Evidence: [original-design captures](validation/2026-11-03-original-design-study/).
The earlier [feature comparison](PREVIOUS_RUN_UX_COMPARISON.md) is supplementary;
it was a source-level comparison, not this isolated original-design walkthrough.

### Observed results and limits

The walkthrough observed draft saving, run navigation, planning and waypoint
detail, governance, the learning/telemetry/alerts/analysis tabs, obstruction
handling and retained stopped-run evidence. The obstruction produced a real
`ENVIRONMENT_CHANGE` event with `holding_no_route`. Pause returned HTTP 200 and
the backend reported `paused`.

A subsequent paused-page reload did not populate run metadata/world data before
the resume-control wait timed out. A fresh visit to the stopped record loaded
successfully. Thus controller pause was observed, but reliable paused-page
recovery was not established on this host. Full arrival/completion, accelerated
3D performance and live model services were not validated. The automation report
remains marked incomplete; [review-summary.json](validation/2026-11-03-original-design-study/review-summary.json)
separates observed behaviour from these limitations.

The blocked-route capture still showed the previous route and approval while
the backend had recorded an environment hold. Historical approval should not
override current hold/revalidation status in the revised interface.

## What the original design is doing

Its central experience is an operating facility with visible execution
evidence. The 3D scene, route layers, mission controls and governance feedback
explain the same mission together. They are not independent decorative panels.

The journey spans two screens:

1. `/twin`: inspect the facility, choose a bay or open-floor destination, save a
   draft, then explicitly start a governed run.
2. `/runs/{id}`: follow planning and execution beside the map, inspect policy
   decisions, introduce hazards, review replanning, stop or resume as permitted,
   and inspect the retained run evidence.

The run screen keeps mission identity, goal, execution state and current
governance decision visible. Additional detail lives in Learning & task,
Site & vision, Chain & telemetry, Alerts and Analysis tabs. The planner panel
shows proposal, planning, governance, execution and audit stages.

## Why the original scene feels more real

- The building provides enclosure and scale: cladding, structural framing,
  lighting, dock doors, exits and signage. Camera-dependent cutaways preserve
  visibility rather than removing the whole building.
- Floor markings describe how the site works: aisles, pedestrian routes,
  crossings, loading areas and boundaries.
- Racks, stock, machines, workstations and handling equipment create purposeful
  density. Their placement makes the floor an operating facility.
- Workers and forklifts have visible identities, poses, destinations and
  activities. Robot movement is shown in relation to them.
- The minimap, safety distances, route layers, inspection and robot-eye HUD
  explain the scene while it runs.

The recent redesign simplified the building and equipment before preserving
this relationship between scene and operation. Better lighting and a closer
camera alone do not establish parity.

The original twin also gives the facility almost the entire viewport. The new
header, metrics, mission desk and fixed scene frame reduce the space available
for operations. The revised active-run layout should prioritize scene height
and a persistent decision/inspection panel, with setup controls moved into a
contextual drawer once a run starts. This is a proposal for the revised plan,
not an implemented layout.

Reuse candidates from the original include `Building`'s camera-dependent walls
and roof, procedural floor/signage textures, articulated `Worker` actors,
`MapLayers`, and the shared `WarehouseView` contract. Adapt these to the selected
facility and new identity rather than replacing useful detail with simpler
unrelated models. The two renderers should consume the same operational data.

## Preservation requirements

| Original capability | Requirement for the revised design |
|---|---|
| Bay and floor destination selection | Preserve both, with coordinates and clearance feedback |
| Explicit saved draft | Preserve a reviewable preparation step and recoverable start failure |
| Full run context | Keep mission, assigned carrier, goal, state and distance/progress accessible beside the scene |
| Planning stages | Show actual backend progress and identify configured planner versus fallback |
| Route layers | Distinguish proposed route, checked plan, admitted target and measured execution |
| Waypoint detail | Preserve coordinates, speed limits and inspection; derive completion from evidence |
| Governance detail | Keep action, policy IDs, reasons, required operator action and admission outcome visible |
| Safety overlays | Use current policy thresholds and selected-carrier telemetry for stop/slow/clearance information |
| Actor inspection | Preserve carrier, person and obstacle inspection, including available activity/destination data |
| Spatial aids | Preserve minimap, trail, risk layers, route toggles, camera reset and fullscreen |
| Robot-eye feedback | Preserve useful HUD information; distinguish projected simulated detections from model perception |
| Scenario demonstrations | Preserve proximity, obstruction, spill, forklift and clear scenarios with visible outcomes |
| Detailed evidence | Preserve learning, telemetry, chain, alerts, safety and analysis access |
| Failure states | Keep stop and mission controls usable under graphics failure; identify stale telemetry and unavailable services |

## Correctness requirements while preserving detail

Preserve the information without copying every old frontend inference:

- Clicking a waypoint or playing a local animation is not proof it executed.
  Progress must follow run events, controller acknowledgements and telemetry.
- A planner route is not a controller permit. A per-action approval does not
  establish that an entire route has been admitted for execution.
- Changed environment context must invalidate the current route display.
  Previous routes can remain as clearly labelled historical evidence.
- Selecting robot 2 must switch its telemetry and run context, including
  clearance readings. Fleet pose plus robot 1's sensors is insufficient.
- Policy explanations should use recorded policy results and actual thresholds,
  rather than generic checkmarks or hard-coded assumptions.
- Model-disabled operation must remain honest. This study does not validate
  live model planning, physical robots or pharmaceutical certification.

## Revised implementation order

1. **Establish the baseline.** Complete the original walkthrough and preserve
   its screenshots, screen inventory, data dependencies and observed limitations.
2. **Preserve the operating workflow.** Define the active-run layout around
   the scene, current action, governance reasons, safety state and operator controls.
   Add a feature-by-feature migration checklist before changing screens.
3. **Restore execution detail.** Migrate route layers, waypoint inspection,
   evidence-backed progress, selected-carrier inspection and diagnostic panels.
4. **Restore spatial interaction.** Bring over floor selection, navigation aids,
   layer controls and the full scenario demonstration flow.
5. **Refine the visual identity.** Apply the new branding and cleanroom setting
   with the original's purposeful detail, enclosure, scale and operating cues.
6. **Verify equivalence.** Run the same mission and hazard sequence in both
   versions; compare information and controls at draft, planning, movement,
   hold, replan, pause, stop and completion. Then check mobile, stale data,
   role restrictions, graphics fallback and rendering responsiveness.

No additional product UI changes are part of this study. The existing redesign
remains an incomplete migration until the operating detail has been carried over.
