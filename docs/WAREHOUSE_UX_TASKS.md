# Warehouse UX correction tasks

Requested 3 November 2026. Scope: preserve mission/governance/controller
capabilities while correcting presentation, facility placement and telemetry.
This file records acceptance criteria and implementation boundaries.

The presentation corrections and mixed-fleet reconciliation below are complete
for this pass. Build, backend checks and browser results are recorded in the
[warehouse validation](validation/2026-11-03-warehouse-ux/README.md). The follow-up adds functional mixed-platform navigation and improves workspace contrast; see the workspace validation record.

| Task | Changes | Verification |
|---|---|---|
| Facility placement | Both renderers consume the same `/sim/world` footprints. Mission Control's floor plan now uses the same increasing-Y-up orientation as the run map. | Six rooms, two benches per room, clear destinations; proxy geometry retained for warehouse, factory and pharma; routes from both parking positions to every bay avoid solids. Browser checks compare map and rendered partition bounds with simulator data. |
| Stable partitions | Single transparent glass planes replace overlapping transparent box faces. Crossbars are recessed behind posts. Wall/roof cutaways use hysteresis around camera thresholds. Canvas drawing buffers match device pixel ratio. | Compare stationary SVG footprints and Three transforms over live refreshes; inspect screenshots. This does not establish flicker-free rendering on every GPU. |
| Legible floor plan | High-contrast room labels sized for the displayed map, mobile wrapping, distinct boundary strokes, accessible equipment titles. Thin partitions no longer contain squeezed text. Canvas labels use larger fonts; speed labels appear on zoom/waypoint inspection. | Desktop/mobile label measurements, screenshots and high-DPI canvas check. |
| Understandable controls | Dedicated toolbar reserves space outside the scene. Camera/inspection actions remain visible; layers, display settings and view guide have separate panels. FPS is under display diagnostics. | Exercise controls and panels, verify toolbar/scene do not overlap, retain routes, minimap, safety layers and inspection. |
| Roof and lighting | Automatic roof cutaway remains camera-dependent, with explicit Show/Hide roof controls. Interior views retain ceiling, light fixtures and ventilation. | Inspect roof-visible and robot-eye captures; verify ceiling visibility for manual and automatic modes. |
| Actual robot operation | Run page polls the assigned robot and run status independently of WebSockets; socket messages from another robot are ignored. Mission Control also requests the selected robot's telemetry. Stale samples remain visibly stale. | Disable WebSockets, verify robot-2 data, interrupt/recover HTTP, then actual signed-permit movement, pause/resume, arrival, obstruction and stop tests. |
| Mixed fleet reconciliation | Earlier proposal and current support are reconciled below. No unsupported capabilities are advertised. | Inspect real capability profiles and controller action model; verify per-platform navigation, controller limits and rendering. |
| End-to-end review | Inspect facility, controls, mobile views and a real delivery together. | Production build/type checks, focused backend tests and browser evidence. Final results belong in the validation report. |

The existing simulator resets a robot to its parking coordinates immediately
after a completed delivery. This is not a driven return journey. Arrival must
therefore be verified against the governed STOP decision and execution record,
not only the live position sampled after completion. The UI now explains this
behavior explicitly on completed simulated run pages.

## What each former overlay means

| Former label | Meaning and new location |
|---|---|
| Reconnecting / last update | Age of received robot data, not proof that motors stopped. Toolbar now says Live robot data or Data delayed. The run header distinguishes live polling from a live socket stream. |
| Reset camera | Restore the default position for the selected perspective. Visible camera action. |
| Quality Auto | Graphics quality, unrelated to controller execution. Display settings. |
| Minimap | Small facility locator; click to recenter Overview. Map layers. |
| FPS / low | Rendering frame rate and graphics quality. Display diagnostics, not a robot performance measure. |
| Hide route / waypoints | Toggle route graphics; waypoints describe a plan, not execution permits. Map layers. |
| Inspect robot | Position, speed, clearance and gate feedback. Visible inspection action. |

## Mixed fleet: proposal versus implementation

The earlier supplied discussion proposes an AMR delivering materials plus a
humanoid serving QC and packaging. It explicitly limits that humanoid to governed
navigation; manipulation and opening doors would require additional supported
actions. Later discussion correctly states that both current simulated robots
share `sim-amr-radius-0.4m-v1` and cannot establish cross-type learning.

Current implementation: both existing AMRs remain. The pharma site adds
`robot-3`, a simulated humanoid navigator with profile
`sim-humanoid-radius-0.35m-speed-0.3mps-v1`. The trusted site selects its profile;
command payloads cannot choose a faster platform. Routing and route repair cap
moves at 0.30 m/s; the governance gate, execution authority and controller enforce
that cap. Permit context binds the selected profile. Peer sensing/contact checks
use per-platform radii. Routing/reservations retain the conservative existing
AMR clearance envelope, which also covers the smaller humanoid footprint.

Fleet cards, mission assignment, floor-plan glyphs and both 3D viewers preserve
platform identity. The humanoid model is 1.72 m tall with articulated limbs;
gait follows measured received travel and settles when stopped. Robot-eye camera
height follows platform type. Human traffic remains distinct.

This validates planar simulated navigation, not physical biped balance, trained
locomotion, grasping, manipulation or a hardware humanoid adapter. Cross-profile
experience reuse remains excluded by the existing exact capability-context check;
adding a second profile does not authorize cross-type transfer.

## Placement boundary

The current pharma world models six rooms, sixteen partitions, twelve benches,
six destination bays, two AMRs, one humanoid navigator, human traffic, a forklift and injected hazards.
The earlier proposed vault, controlled door and reserved airlock are not modeled
here. Adding decorative versions would imply constraints the gate does not
enforce, so those remain separate functional work rather than invented obstacles.
