# Experience lifecycle validation — 2 November 2026

Backend: 403 tests passed across the regression and an isolated rerun. The last full run reported 402 passed and one tracing HTTP timeout during concurrent browser load; that tracing case passed alone (20.52 seconds). An earlier complete suite passed all 403 cases. Environment integration also passed independently.

Frontend: the production `.next-validation` build compiled, type-checked, linted and generated all 13 pages successfully. `git diff --check` is used for source whitespace verification.

The [seeded graph benchmark](../../../backend/bench/results/experience/README.md) reports 28.6% lower modeled travel-plus-queue time across 20 seeds, with all 15 deliberately stale records excluded. These are graph costs, not physical robot results.

Browser harness: `tests/experience.browser.cjs` against `scripts/browser_validation_stack.py` on loopback ports 19300/18080/18090. State is isolated per launch. Model credentials are disabled; a signed fixture is labelled `robot-A (fixture)`. External HTTP requests are blocked in the primary context. `BROWSER_FORCE_FALLBACK=1` checks interaction with WebGL unavailable; the normal rendering mode uses a 10 FPS test-host cap. No user mission databases are used.

The final [browser report](browser-results.json) passed all six workflow assertions in forced WebGL fallback mode: fixture provenance, two-robot state, UI mission creation and environment replacement, old-record exclusion, pause/kill/refused-resume/reset/resume, and usable mission/stop controls without WebGL. Both scenario POST responses returned 200. The mission first held with no route, then replaced its route with 21 waypoints after clearing the pallet. No unexpected page errors or external asset requests were recorded.

`experience-before.png`, `mission-replanned.png`, `experience-invalidated.png` and `graphics-fallback.png` capture this successful run. Screenshots were visually inspected. `factory.png` is from a separate normal-rendering probe: the factory rendered and robot inspection worked with external requests blocked. The complete workflow was verified in fallback mode because normal software rendering was slow on this host; this is not a normal-rendering frame-rate acceptance result. Earlier harness failures exposed hydration timing, a tab locator, and Windows launcher-child cleanup; the harness now checks scenario responses, uses fresh databases, checks ports, and terminates its process tree.
