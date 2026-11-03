# Presentation audit evidence — 3 November 2026

See the [full findings and 22-area matrix](../../PRESENTATION_CAPABILITY_AUDIT.md).

- [Inventory](inventory.json): visible text, collapsed/full text, headings,
  navigation targets, controls and desktop overflow across 11 pages. No page
  JavaScript errors were observed. The only non-GET browser request was a
  development token request; response tokens were not saved.
- [Runtime metadata](runtime.json): health/availability, actual facility bounds,
  policy-catalog defaults, site-intelligence state, current run status and recent
  event summaries. Contains no credentials. The refusal responses are genuine
  records from the existing active mission, not an injected test scenario.
- [Mobile dimensions](mobile.json): 390 px landing and Mission Control fit;
  populated authority event rows overflow. A subsequent inspection measured
  approximately 647 px document width on that page.
- Screenshots capture the landing, guide, Mission Control and Trust & security.
  Learning fixtures remain visibly marked as fixtures; their counts are not
  presented here as real mission-learning results.

This was a read-only audit in the existing isolated preview. Model, vision,
voice and Tavily integrations were disabled there; Memgraph was connected.
The active mission belonged to the existing workspace and was left untouched.
No scenario, stop, resume, mission creation, policy change or model request was
issued. Runtime snapshots on different pages were taken at different times.

Reproduce the navigation inventory with `node scripts/audit_presentation.cjs`.
The report describes the captured state; later live missions can produce
different statuses, event rows and overflow conditions.
