# Mission Control UI / UX overhaul

## Confirmed scope: presentation only

User clarification, 3 November 2026: this is a UI/UX redesign, with no removal,
replacement or reduction of existing functionality or capabilities. Preserve
existing mission preparation, execution, inspection, scenario controls and
evidence access while changing their visual presentation. A link to the old run
page alone does not establish parity in the redesigned operational workspace.
The current redesign has presentation gaps and is not a completed replacement.
Changing the default simulated site also goes beyond a purely visual redesign;
the existing environment must remain available without forced migration.

Implementation resumed for the user-approved [warehouse correction tasks](WAREHOUSE_UX_TASKS.md)
after the [original design study](ORIGINAL_DESIGN_STUDY.md). The work below records
the current redesign; it does not establish full parity with the original
execution workflow. Further migration follows the preservation-first sequence.

The correction pass separates warehouse controls into a reserved toolbar, adds
a view guide and explicit roof settings, improves map labels and high-DPI
rendering, and keeps run telemetry fresh through an independent HTTP transport
for the assigned robot. Completed simulated runs explain the existing automatic
return-to-parking behavior. The follow-up implements mixed-platform simulated navigation with two retained AMRs and one humanoid, plus a higher-contrast slate workspace.

The main operational experience is `/mission-control`. The original public
landing page has been restored verbatim from commit `2d3a984`, including its
`/overview` app links. `/demo` redirects to the guided showcase in Mission Control.

Mission Control and the retained run/twin views now use the shared
`twin/FacilityEnvironment.tsx` for static facility geometry from `/sim/world`.
This renders cleanroom benches, glass partitions, room signs and bays in the run
view as well as Mission Control. Factory/warehouse layouts retain their existing
building, racking, equipment and features. Cameras and run overlays remain with
their respective renderers; this change does not establish complete UI parity.
The [focused verification](validation/2026-11-03-facility-parity/README.md)
compares 517 actual static meshes across Mission Control and a paused run; all
four checks and the production build passed for that earlier rendering revision.

## Physical facility appearance

The acceptance criterion is a believable physical facility with clearly readable
room boundaries and partitions, beyond matching colors or object counts.
The shared cleanroom now has 3.3 m partitions, solid lower wall panels, framed
glass with visibility bands, six labelled open entrances and a four-sided
3.4 m perimeter enclosure. The original camera-dependent cutaway principle keeps
near walls out of the overview while retaining the enclosure in interior views.
Ceiling grid, sealed light fixtures, ventilation grilles and overhead services
appear below ceiling height. Overview framing is closer, and Mission Control has
an Expand facility button with native fullscreen and the existing camera modes.

These are visual changes. Layout data, route openings, mission logic and existing
run controls are preserved. Entrance headers leave at least 2.6 m headroom; no
closed door or additional floor obstacle is invented. Visual inspection of both
overview and interior captures is required alongside the geometry checks.
The [architecture validation](validation/2026-11-03-facility-architecture/README.md)
records the inspected captures and five passing browser checks for this revision.

## Design and workflow

- Slate workspace backgrounds, crisp light panels, a forest-green navigation rail, sage accents and a new brand
  mark distinguish this project from the previous dark dashboard.
- The facility, mission composer, fleet selection, authority status and decision
  trail are visible together. Detailed history, governance and security remain
  available through persistent navigation.
- The 3D facility uses a perspective camera, shadowed lighting, tiled floors,
  framed glass partitions and room-specific equipment: cold-storage cabinets,
  analytical benches, formulation vessels, microscopes and packaging rollers.
  Overview, Follow robot and Robot eye cameras keep the new dashboard intact.
  Detailed carriers, forklifts and PPE technicians use real received positions;
  movement interpolates toward telemetry without predicting future travel.
  Local geometry, bounded pixel density and visibility-aware demand rendering
  limit rendering work. A keyboard-operable SVG floor plan is also available.
  WebGL failure falls back to that plan without removing operational controls.
- The responsive navigation and operator dialog keep access available on mobile.
  The dialog supports keyboard focus containment, Escape and focus restoration.
- The toolbar keeps a real **Stop fleet** action available throughout the app.
  Confirmation follows the controller response. Releasing a stop does not resume
  paused missions.

## Real state and honest evidence

Mission creation, start, pause, resume, end, scenario injection and stop release
use existing backend endpoints and access controls. A failed start retains the
draft for retry. A robot with an active mission cannot receive another mission
from the composer. Selecting another carrier updates the mission context.

No simulated random counters are presented as live figures. Fleet positions
become explicitly stale when the connection fails; launch requires current
telemetry, fleet and authority status. Planner and voice availability follow
backend configuration. Recorded decisions remain identified as recorded evidence.
The landing illustration is explicitly illustrative.

The recent-events query adds `latest=true` to `/runs/{id}/events`; it returns
the newest bounded window in chronological display order. Existing ascending
pagination remains the default. The world proxy now preserves site identity.

Operator sessions use `sovereign-autonomy.session.v1` in local storage. This
avoids reusing the earlier generic storage key. Real account and signing-key
configuration still belongs to the project's backend deployment.

## Default cleanroom showcase

`SITE_LAYOUT=pharma` (the default for new deployments) selects `backend/bench/sites/pharma.json` for the simulator.
Restart the simulator and backend together after changing the setting so that
the gate synchronizes with the active world. An explicit `SITE_LAYOUT=factory` or `SITE_LAYOUT=warehouse` keeps either alternative available. Existing explicit environment settings take precedence.

The fictional Demo Pharma Plant facility has six destinations, glass
partitions, benches, a shared transfer corridor, two mobile carriers and a simulated humanoid navigator. Its
collision geometry is shared by routing, governance and rendering. Every
destination is tested from all parking positions for reachability and clear
route segments. This does not add humanoid manipulation or compliance certification.

## Reproduce validation (PowerShell)

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_mission_control.py backend/tests/test_factory.py backend/tests/test_resume.py backend/tests/test_operator_stop.py -q
$env:NEXT_DIST_DIR='.next-validation'
$env:BACKEND_URL='http://127.0.0.1:18080'
npm --prefix frontend run build
$env:BROWSER_SITE_LAYOUT='pharma'
.\.venv\Scripts\python.exe scripts/browser_validation_stack.py
# In another terminal, after the stack reports ready:
node tests/mission-control.browser.cjs
# Shut down only the isolated validation stack:
New-Item -Path backend/data/browser-validation/stop -ItemType File -Force
```

The browser checks use real isolated services on ports 19300, 18080 and 18090,
throwaway databases and no model API calls. Screenshots and the JSON report are
written to `docs/validation/ui-overhaul`. `/twin` remains available as a reference view. The new `/mission-control`
interface remains the main design; its 3D presentation now incorporates the
immersive perspective and detail of the twin. Existing detailed records use
the new shell and palette, while retaining their established detailed controls.

All 449 backend tests, the production build and all nine browser workflow checks passed. Screenshots
and the report are indexed in [browser evidence](validation/ui-overhaul/README.md).

The 3 November realism update passed the production build and ten browser
workflow checks, including live overview, follow and robot-eye camera views.
See [updated visual evidence](validation/2026-11-03-facility-realism/README.md).

## Workspace completion pass

Mission Control now exposes the original warehouse inspection tools directly in
an expandable detail workspace: camera/reset/fullscreen, actor inspection,
minimap, safety/risk/trail layers, robot-eye HUD, recorded plan waypoints and
measured travelled path. Waypoint coordinates/speed caps and full latest recorded
policy reasons/required action accompany the scene. A plan remains labelled
recorded evidence, never a current permission. Environmental changes hide the old
plan until a newer plan event is available. Telemetry continues independently.
Opening detailed inspection changes the overview to the floor plan so two heavy
3D canvases do not run together by default.

The composer supports explicit draft saving and floor destinations, with numeric
coordinate entry as an alternative to 3D picking. Robot assignment remains on the
mission payload after coordinate normalization. All six existing scenario types
are available in the scenario lab. Existing full run evidence and analysis pages
remain available.

Text and background changes apply throughout the app shell and shared palette:
slate canvas `#dce5ef`, ink `#192e42`, secondary text `#40566b`, clearer borders and
crisp panels. The original static landing file remains unchanged. Validation:
[workspace checks](validation/2026-11-03-workspace/README.md).
