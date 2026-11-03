# Memgraph validation — 3 November 2026

Actual database: Memgraph 3.14.0 in the existing Ubuntu WSL distribution, Bolt
loopback port 17687. Windows backend uses Neo4j Python driver 5.28.8. Docker is
unavailable on this machine, so Compose runtime validation is not claimed.

- Full backend regression, including the first 12 graph cases: **509 passed**
  in 262.47 seconds. The graph cases used a real database with isolated namespaces.
- Final focused graph suite: **16 passed**. Subsequent cases cover planner
  retrieval/prompt wiring without model calls, actual connection refusal,
  transaction rollback and namespace separation. Source verification and driver
  initialization were tightened after the broad run and covered by this rerun.
- Production frontend build: passed compilation, types and all 14 page builds.
- Browser acceptance: **5 checks passed**, no JavaScript errors, phone/tablet/
  desktop widths. Disabled/unavailable UI responses were explicitly mocked;
  the connected state, source table and sync used the actual backend and database.
- Existing verified mission `run_84fa654ec55a`: one projected run, **25 signed
  decision references**, 25 source-reverified facts and zero exclusions. This
  reuses the earlier live-model mission; no new paid model calls were made here.
- Browser graph inspection/sync issued no simulator or mission-control commands.

Evidence: [actual API results](live-api.json), [browser report](browser-report.json),
[verified connections](verified-connections.png), [desktop](knowledge-1440.png),
[tablet](knowledge-768.png), [phone](knowledge-390.png).

Other learning panels visible in screenshots contain explicitly labeled signed
browser fixtures. Those fixtures are not the graph's mission evidence. The graph
projects the real simulator run's signed decisions from the isolated SQL store.

Memgraph runs as an optional advisory projection. It does not replace the signed
source, modify NetworkX weights, issue permits or implement a certified physical
robot controller. See [implementation/setup/limits](../../MEMGRAPH.md).
