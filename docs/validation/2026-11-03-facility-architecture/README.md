# Physical facility appearance

3 November 2026. This revision addresses the user's requirement that the facility
feel like a real physical interior, with readable room partitions, rather than
only sharing colors or layout geometry between screens.

Validation: production build/type checks passed; all five browser checks passed
with no page errors. Both views contain 714 matching static facility meshes.
Overview and illuminated interior captures were visually inspected.

The shared cleanroom includes sixteen 3.3 m partitions with solid lower panels,
glass, mullions and visibility bands; six labelled open entrances; four 3.4 m
perimeter walls with camera cutaways; and a ceiling grid, light fixtures,
ventilation grilles and overhead services visible from interior cameras. Local
ceiling lights illuminate the rooms. Mission Control can expand the actual live
scene to fullscreen. Robot-eye and follow cameras remain available.

The simulator layout and mission/controller behavior are unchanged. Entrance
headers leave more than 2.6 m clear headroom, and no closed doors are added to
the existing open routes. Both operational views use the shared environment.

Evidence:

- `mission-control.png`: normal dashboard framing.
- `facility-overview-expanded.png`: actual fullscreen 3D overview.
- `facility-interior-eye.png`: actual robot-eye interior with ceiling visible.
- `run-full-facility.png`: same facility in the run workspace with route overlays.
- `browser-report.json`: geometry, architecture, fullscreen and retained-control checks.
- `restored-landing.png`: previous landing page remains restored.

The images come from the real isolated local pharma simulator/backend/Next
production stack, with no model calls. Software WebGL is capped at 5 FPS only
in the test harness. Geometry equivalence verifies consistency, not subjective
realism; overview and interior screenshots were also visually inspected. These
are procedural 3D models, not photographs or a scan of an actual facility.

Reproduce with the production validation build and
`BROWSER_SITE_LAYOUT=pharma` for `scripts/browser_validation_stack.py`, then set
`BROWSER_EVIDENCE_DIR=docs/validation/2026-11-03-facility-architecture` and run
`node tests/facility-parity.browser.cjs`. The test run is stopped afterwards.
