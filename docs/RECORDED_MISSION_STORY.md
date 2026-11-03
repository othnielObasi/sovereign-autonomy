# Recorded mission story

The landing section `/#experience` now demonstrates a single historical
simulator mission before introducing the five platform capability groups.
It presents five selected moments: Plan, Move, Stop, Replan and Arrive.

## Source and claims

Source run: `run_f8bdbc5984ab`, robot-2, 3 November 2026. The recorded destination
was Quality lab at (18, 2.5). The original validation report is
`docs/validation/2026-11-03-warehouse-ux/browser-report.json`; its completion
capture is `completed-delivery.png` in the same directory.

The archived database contains 413 events, 81 permit-use records and eight
hard-fail decisions. The selected proximity denial records a human distance of
0.378m and zero robot speed. A verified, gate-enforced STOP follows. A replacement
fallback plan and subsequent permit use precede continuation. The last recorded
decision shows arrival at (18.004, 2.533) with zero speed and a verified STOP.
The simulator's later automatic parking reset is explicitly distinguished from
driven movement.

This is a recording of simulator behavior with fallback planning. It does not
demonstrate physical hardware, live AI model calls or shared learning. Operator
pauses, intermediate events, review decisions and integrity warnings are retained
in the download but omitted from the five selected highlights. The story makes
no claim that every proposal was safe or that the run was flawless.

## Integrity limitation found during export

Recomputing each SHA-256 event hash, with the original UTC timestamp offset,
verified all 413 individual event contents. Chronological previous-hash linkage
has 37 discontinuities in this historical record. Therefore the archive states
`individual_hashes_verified: true` and `chronological_chain_valid: false`, and
includes the affected event IDs. The recording limits and a visible note on the
landing disclose this. It must not be described as a fully verified continuous
audit chain. No historical data was repaired or rewritten to hide the issue.
This finding concerns the archived run; it does not establish current runtime
behavior. Backend implementation changes are outside this UI task.

## Presentation and data boundaries

- `frontend/public/landing/mission-story/summary.json` contains selected source
  event IDs, UTC time ranges, actual poses and prior recorded positions.
- The same summary is embedded in the page, so the highlights need no API call.
- The simplified SVG floor plan is generated from `backend/bench/sites/pharma.json`.
  Dashed routes are proposals; solid trails contain observed robot positions.
  The worker markers at the stop come from that decision's telemetry.
- A context image shows the actual simulator facility, labelled as a reference
  rather than a frame of the chosen moment. A separate expandable image is the
  actual completed-run interface capture and is labelled as post-completion.
- `audit.json` retains all source event payloads/hashes and the recorded safety
  report. This ~1.35MB download is not fetched by the public page automatically.
  The ~1.18MB full interface image loads on expansion. The initial context image
  reuses the existing ~96KB facility asset.
- `story.js` handles only local presentation. It sends no robot commands, creates
  no missions, requests no models and does not run timers or autoplay.
- Native buttons support pointer/keyboard use; arrow keys, Home and End navigate
  the five moments. The scrollable mobile floor plan keeps room labels readable
  and centers the selected recorded robot position.

Re-export, read-only:

```powershell
.\.venv\Scripts\python.exe scripts/export_public_mission_story.py backend/data/browser-validation/app-1793706920064305600.db
```

The exporter refuses credential-like fields, verifies original content hashes
before writing, and preserves rather than suppresses linkage failures.

## Verification

`node tests/public-pages.browser.cjs` passes 13 read-only browser checks. The new
coverage checks source event references, pose provenance, stop/arrival speed,
permit counts, disclosed linkage failures, five-moment navigation and visible
robot markers at 390/768/1024/1440px. Existing public-page filters, capability
expansion, links, keyboard controls, local fonts and reduced-motion checks pass.
Screenshots and the report are under
`docs/validation/2026-11-03-public-pages/`.
