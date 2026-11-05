# Sovereign Autonomy: hackathon submission

**AI can propose. Only authorised movement can proceed.**

| | |
|---|---|
| Live product | https://204-12-178-126.sslip.io |
| Try it | [Mission Control](https://204-12-178-126.sslip.io/mission-control) · [Fleet learning](https://204-12-178-126.sslip.io/learning) · [How it works](https://204-12-178-126.sslip.io/how-it-works) |
| Repository | https://github.com/othnielObasi/sovereign-autonomy |
| Three-minute video | https://youtu.be/Kak8teTVHSA |
| Track / theme | Startup · Push the Frontier |
| Team | _add names_ |

## The problem

Pharmaceutical cleanrooms, hospitals and warehouses want autonomous robot fleets
working beside people. Planning models are now good enough to drive them, but a
model can be wrong, confused or manipulated, and it cannot be certified. One bad
move means an injury, a lost batch or a failed audit. Today a site has two bad
options: keep the AI away from the robots, or trust it blindly.

## What Sovereign Autonomy does

It is the independent safety and trust layer between AI planners and the robots
they command.

1. **Meta's models plan and perceive, but only propose.** Muse Spark plans each
   mission from the site map and the robot's camera; Muse Spark Open proposes
   steps; SAM 3.1 finds people, spills and pallets in the camera image.
2. **A safety gate checks every proposed move** against the site's versioned rules
   (geofence, speed, human and worker proximity, clearance, hazard zones).
3. **An execution authority signs a single-use, short-lived permit** for exactly
   that move. The robot's controller checks the permit again before moving.
   A refused move stops the robot; the model replans and the new route needs
   fresh permission.
4. **Stops never depend on the AI.** A spoken "stop" (Muse Voice Transcribe), a
   button or a kill switch revokes authority at the controller. Voice can stop a
   robot but never start one; only a signed-in operator can release a stop.
5. **Every decision is on the record:** Ed25519-signed decision receipts and a
   hash-chained event log anyone can verify.
6. **Robots learn as a fleet, under human control.** Observations are signed and
   scoped to site, map, rules and robot type. A lesson is shared only after it is
   evaluated and an operator approves and releases that exact version, and only
   to robots it fits. Poisoned or manipulated lessons are rejected or quarantined.

Who it is for: operations, quality and safety leads running mixed robot fleets
alongside people, starting with pharmaceutical manufacturing. The live demo runs
a simulated pharma cleanroom with two wheeled carriers and a humanoid.

## How Meta's models are used

| Model | Role | Where | Verified live (4 Nov 2026) |
|---|---|---|---|
| Muse Spark 1.3 (Meta Model API) | Mission planning and replanning from map and camera | `backend/app/services/muse_planner.py`, `meta_models.py` | Planned and replanned run `run_939e05c6e625` (shown on the homepage) |
| Muse Spark Open (open weights, via Baseten) | Per-step proposals; takes over planning if the API is unavailable | same | Proposed steps in live runs |
| SAM 3.1 (Meta Model API) | Finds people, spills and pallets; projects them onto the floor; cross-checked with sensors; can only add caution | `backend/app/services/perception.py` | 41 checks in one run; median position error 2 cm across 35 matched objects |
| Muse Voice Transcribe | Spoken stop becomes a kill switch | `backend/app/api/routes_authority.py` | "Stop robot one now": transcribed in 1.4 s, authority revoked in 3.4 ms, stop verified |

Model output is never authority. Every proposal passes the gate, the permit and
the controller, and the evidence record names the model behind each plan.

## Built during the hackathon versus the existing foundation

The first commit, `3738a53`, is the pre-existing codebase from before 26 October
2026: the policy gate, decision receipts and event chain, the task-drift guard,
adaptive tuning and cross-run learning, the 3D warehouse twin (first committed
22 October 2026), Tavily site intelligence (22 October 2026), rule workflows and
benchmarking. Every later commit (`git log 3738a53..HEAD`) is hackathon work:

- Meta model integration: Muse Spark, Muse Spark Open, SAM 3.1, Muse Voice Transcribe
- Governed skill transfer (CPU lab, MuJoCo physics): a pick-and-place skill learned on Robot A, tested on held-out positions, approved, installed on compatible Robot B, refused for Robot C (`64a5bbd`, `b786a13`; live at /skills, verified end to end on the production deployment on 5 Nov 2026)
- Execution authority: signed single-use permits, controller redemption, kill switches, voice stop, checkpoints, restart reconciliation
- Mixed fleet: wheeled carriers and a humanoid with enforced capability profiles
- Signed, scoped route learning with poisoning defences, quarantine and checkpoint rollback
- Operator-released fleet learning: candidate → evaluated → approved → released → withdrawn
- Pharmaceutical cleanroom site, 3D facility realism pass, operator workspace
- Memgraph evidence graph and interactive mission knowledge graph
- Production deployment, public pages, pilot-request form, live validation
- Run-loop robustness fixes found live: stale permits after a stop, replanning when a slowed move is blocked, backing out of corners, and vision sightings no longer wiping route experience

## Evidence

- Live results, read from the deployed site's API: [live-validation-2026-11-04.json](../frontend/public/home/evidence/live-validation-2026-11-04.json)
- Homepage replay record, 1,018 events in one unbroken hash chain: `frontend/public/home/mission-story/live-run.json`
- Verify a run's chain on the live site: `/api/compliance/verify/{run_id}`; verify a receipt: `/api/governance/receipts/{run_id}/{decision_id}/verify`; public key: `/api/governance/signing-key`
- Backend tests: 563 passed (`python -m pytest backend/tests`)
- [Capability audit](CAPABILITY_AUDIT.md) and [Safety case](SAFETY_CASE.md)

## Trying it

- **Mission Control** runs missions on the shared simulator. Public demo limits: one mission at a time, missions stop after 7 minutes, and paid model calls have hourly caps.
- **Fleet learning** is open to view. Approving and releasing lessons, and releasing kill switches, needs operator sign-in; credentials for judges are provided in the submission form, not in this repository.
- **Request a pilot** on the homepage stores real enquiries.

## Deployment

One Nebius VM (us-north1): Docker Compose with Caddy (HTTPS), FastAPI backend,
Next.js frontend, simulator, Postgres and Memgraph. Meta's Model API does not
serve EU addresses, so the deployment runs in a US region. See `deploy/`.

## Limits

- Simulator only: no physical robot, no manipulation or balance control.
- Not a safety certification. Real deployments need hardware stops, calibrated perception and site-specific safety assessment.
- Busy corridors can hold a robot long enough to reach the demo's 7-minute limit; that is the safety rules working.
- Cross-platform skill transfer and multi-site failover are not implemented.
