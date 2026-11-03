# Shared facility rendering and restored landing

3 November 2026. Local isolated simulator/backend/Next production stack at
19300/18080/18090, `SITE_LAYOUT=pharma`, no configured model keys or model calls.
The previous public landing file is restored byte-for-byte from `2d3a984`.

Production build and type checks passed. All four focused browser checks passed,
with 517 matching static facility meshes and no browser page errors.

`tests/facility-parity.browser.cjs` inspects the mounted Three scene graphs in
Mission Control and a real paused run. It compares static mesh types, geometry
parameters, bounding boxes, transforms and colors. Per-mount shape UUIDs are
excluded. The script also checks retained run navigation controls and switching
between the floor plan and 3D. See `browser-report.json` for the final outcome.

- `restored-landing.png`: original public landing page.
- `mission-control.png`: Mission Control with the shared cleanroom geometry.
- `run-full-facility.png`: the run view with the same geometry and run overlays.
- `browser-report.json`: focused browser verification result.

Screenshots use software WebGL with a test-only 5 FPS rendering cap. Camera,
lighting, actors and operational overlays remain specific to each existing view;
the shared static facility is the subject of the equivalence check. This is not
a full capability-parity or production-performance claim. The run is stopped
after verification. Earlier harness attempts required selector and geometry
normalization corrections; they did not identify a product failure.

To reproduce, first build the frontend with `NEXT_DIST_DIR=.next-validation` and
`BACKEND_URL=http://127.0.0.1:18080`, then launch
`scripts/browser_validation_stack.py` with `BROWSER_SITE_LAYOUT=pharma`, and run
`node tests/facility-parity.browser.cjs`.
