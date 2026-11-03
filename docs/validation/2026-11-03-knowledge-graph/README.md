# Interactive operational graph — 3 November 2026

The workspace now plots the Memgraph-backed, source-reverified relationships in
`/authority`. The overview groups decisions, floor cells and policies; the
single-decision view shows an actual event and its evidence. Source IDs and the
original table remain available. This is historical inspection, not robot control.

Validation uses the isolated backend/simulator and actual Memgraph 3.14.0 through
WSL. The real reference run is `run_84fa654ec55a`, with 25 signed decision records.
Its overview has five nodes: mission, robot, run, approved-decision group and
location group. No policy node is invented when the sample has no policy hits.

Production build passed compilation, type checking and 14 page builds. Seven
graph browser checks cover source counts, pointer/keyboard selection, single-event
inspection, source hashes, filters/empty state, zoom/fit, responsive node layout,
policy connections and absence of robot commands or browser errors. The existing
five operational graph browser checks also passed after the new plot was added.
No backend code changed for this visualization.

The blocked/review/policy branches are exercised with an explicitly synthetic,
30-observation API response in the browser test. It is never ingested into the
database and is not presented as a real mission. Its mobile screenshot is named
`fixture-mixed-decisions-mobile.png`. Real-source captures use `live-graph-*`.

Screenshots were inspected at phone, tablet and desktop sizes. Labels were
shortened and narrow-screen arrow geometry adjusted to prevent crowded text and
connections passing through unrelated nodes. The layout is fixed and reflows;
there is no moving force layout or remote graph visualization dependency.

Reproduce with `node tests/knowledge-graph.browser.cjs` against the isolated
preview containing that reference run. See [browser report](browser-report.json),
[desktop](live-graph-1440.png), [tablet](live-graph-768.png),
[phone](live-graph-390.png) and [synthetic mixed decisions](fixture-mixed-decisions-mobile.png).
