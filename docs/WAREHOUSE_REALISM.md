# Warehouse realism

The existing simulator remains the operational source of truth. This work improves
the shared Three.js facility, rather than replacing it with a separate visual-only
warehouse or an Isaac Sim integration.

## First pass: facility depth and usable interior cameras

- Both Mission Control and the twin use the same facility geometry, partitions,
  entrances, equipment and roof cutaway behavior.
- Follow cameras sit at 2.15 m, below entrance headers, with a shorter look-ahead.
  Their position is constrained against fixture footprints and the site perimeter.
  Camera easing is checked after interpolation so a turn cannot carry the lens
  through a fixture between two otherwise clear camera targets.
- Nearby worker and idle AMR labels retain a fixed screen size instead of growing
  with perspective and obscuring the facility.
- Shared floor contact shading gives partitions and equipment more grounding,
  including in low quality mode. It uses one small procedural texture and one
  plane per fixture; it is an inexpensive visual approximation, not ray tracing.

Camera clearance is presentation logic. It does not modify routes, fixture
collision footprints, robot permissions or movement policy. The existing motion
model already includes acceleration, braking distance and a turning-rate limit.

## Validation

From the repository root:

```powershell
node tests/camera-geometry.cjs
```

Six checks cover fixture clearance, open views, perimeter constraints, open
doorways and the 118 archived mission poses. The input is the tracked cleanroom
layout and archived mission audit, not a newly invented route.

The frontend TypeScript check and production build passed. An isolated build and
stack were used so the app on port 19300 was not restarted or changed:

```powershell
cd frontend
$env:NEXT_DIST_DIR='.next-realism'
$env:BACKEND_URL='http://127.0.0.1:18083'
npm run build
cd ..
$env:BROWSER_FRONTEND_PORT='19340'
$env:BROWSER_BACKEND_PORT='18083'
$env:BROWSER_SIM_PORT='18093'
$env:BROWSER_SITE_LAYOUT='pharma'
$env:BROWSER_NEXT_DIST_DIR='.next-realism'
.\.venv\Scripts\python.exe -X utf8 scripts/browser_validation_stack.py
```

With that stack running, `node tests/warehouse-realism.browser.cjs` checks the
actual mounted renderers. It intercepts read requests with a recorded pose and
blocks writes. It checks interior follow height, contact shading, identical
facility mesh counts/groups across both views, and JavaScript errors. Screenshots
and reports are saved under ignored `backend/data/realism-review/`. These are
rendering checks, not evidence of a live mission or hardware execution.

## Remaining distance to a physical simulator

The warehouse is still a kinematic simulator. It does not yet have Isaac/PhysX
rigid-body contact dynamics, calibrated sensor noise, payload dynamics, measured
wheel friction or physically validated humanoid locomotion.

Further realism should preserve one shared facility definition and be validated
in stages: richer materials and lighting, believable task-specific robot motion,
then collision and sensor fidelity against measurable reference behavior. Visual
polish alone must not be described as physics or hardware validation.
