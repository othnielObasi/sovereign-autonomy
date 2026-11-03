# Hackathon submission draft

Project: Sovereign Autonomy

Team name:

Participants:

Track: Startup (README classification; confirm eligibility before submission).

Theme: Push the Frontier.

Repository: https://github.com/othnielObasi/sovereign-autonomy

Public demo URL:

Three-minute video URL:

## What it does

Meta models propose navigation using the mission, facility map and robot camera.
Deterministic policies check actions. A separate authority issues signed,
expiring, single-use permits that the simulator controller must admit before
movement. Operators can pause, replace a route, inspect evidence and review
scoped uncertainty. The pharmaceutical workspace shares facility geometry across
2D/3D views. Humanoid support is navigation, without manipulation or balance.

## New work versus the existing foundation

Do not present all capabilities as new hackathon work. Baseline `3738a53` already
contains the policy gate, receipt/event foundation, task guard, warehouse twin,
rule workflows, benchmarking and Tavily site intelligence. Git history alone
does not independently establish when earlier work was originally conceived.

Later work adds Meta adapters, execution permits/controller admission, restart
reconciliation, scoped signed learning with poisoning/rollback defenses, mixed
robot profiles, the cleanroom workspace, operator route replacement/review and
expanded public explanation pages. Current validation fixes event ordering and
original-content verification and distinguishes configured from verified search.
An optional Memgraph projection now connects verified decision evidence for
investigation and compatible planner context; NetworkX remains the route engine.
See [implementation and limits](MEMGRAPH.md).
The video should identify the foundation and focus on these additions.

## Verified on 3 November 2026

- Muse Spark 1.3 and Muse Spark Open answered live HTTP requests.
- Fresh run `run_84fa654ec55a` used a Muse Spark plan with camera context and
  completed after pause, spill injection, clearance and resume.
- Live Tavily results corroborated flammable guidance from NOAA and OSHA. The
  simulated exclusion zone expanded from 1.2 m to 3 m and speed tightened to
  0.2 m/s. A pure policy evaluation of a move into the zone was denied by
  `HAZARD_EXCLUSION_08`; no controller move into the spill was attempted.
- A malicious bulletin was quarantined without changing rules.
- All 88 original events passed content/link verification; all 25 signed
  decision receipts passed Ed25519 verification.
- Full backend suite: 496 passed. After extending integrity checks to every
  compliance export, 52 focused tests passed, including the new regression.
- Production frontend build passed; 13 public-page browser checks passed.

Evidence: [connectivity](validation/2026-11-03-live-integrations/connectivity.json),
[fresh mission and receipts](validation/2026-11-03-live-integrations/mission.json),
[public pages](validation/2026-11-03-public-pages/).

Provider calls include retries and fallbacks; not every call succeeded. SAM and
voice were not freshly validated here. The older public recorded story retains
its disclosed historical chain gaps; this passing run does not rewrite it.

## How Tavily is used

`backend/.env` now contains the configured Tavily key; env files remain ignored.
Spill telemetry creates an immediate baseline zone and schedules background
search. Restricted-domain results pass injection screening and keyword-based
hazard classification. Two distinct trusted domains must corroborate a class
before reviewed rules tighten geometry or speed. Outside text never authorizes
movement. Missing credentials/search errors use labeled sample guidance.

The UI now distinguishes a configured key from a successful live lookup.
Keyword matching does not establish contextual understanding or independent
sources. These simulation constraints are not chemical handling instructions.

## Reproduce

Follow the README for normal operation. For isolated paid-provider checks, build
the frontend against backend port 18080. Set `BROWSER_LIVE_INTEGRATIONS=1`,
`BROWSER_SITE_LAYOUT=pharma`, and `BROWSER_NEXT_DIST_DIR` to that output directory
before launching `scripts/browser_validation_stack.py` with the project venv.
Run `scripts/validate_live_mission.py` in another terminal. It controls a single
mission against the isolated local simulator; do not adapt it to physical robots.

## Remaining submission actions

Fill participants/team when ready, confirm track eligibility, record the
[three-minute script](demo-script.md), publish an accessible video, confirm judge
access and submit the official form. Localhost is not a public deployment. This
draft does not claim a recorded video or a completed portal submission.
