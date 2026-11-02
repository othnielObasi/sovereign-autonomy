# Architecture

## System Overview

Sovereign Autonomy is a runtime governance layer for autonomous robots. Meta's Muse Spark plans each mission (seeing the robot camera) and Muse Spark Open proposes each step; a deterministic gate of 11 policies approves, slows or blocks every move; only an approved move gets a single-use permit the robot controller checks again; every decision is hash-chained and signed.

```
┌─────────────────────────────────────────────────────────────┐
│                     Operator Dashboard                       │
│        Next.js 14 • React 18 • TypeScript • three.js        │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐ ┌──────┐ │
│  │Dashboard │ │Run detail│ │Compliance│ │Audit  │ │Polic-│ │
│  │+ Missions│ │2D/3D map │ │Reports   │ │Trail  │ │ies   │ │
│  └──────────┘ └──────────┘ └──────────┘ └───────┘ └──────┘ │
│                                                              │
│  WarehouseView: Map2D (floor plan) ⇄ Warehouse3D (twin)      │
│  Planner panel • Site intelligence • Alerts • Robot camera   │
└──────────────────────┬──────────────────────────────────────┘
                       │ REST (/api proxy) + WebSocket
┌──────────────────────▼──────────────────────────────────────┐
│                    Governance API (FastAPI)                   │
│                                                              │
│  Routes: missions • runs • governance • policy proposals •   │
│          compliance • operator • llm • sim • site-intel •    │
│          ws • health • auth                                  │
│                                                              │
│  ┌────────────────────┐      ┌───────────────────────────┐  │
│  │ RunService         │      │ GovernanceEngine          │  │
│  │ _run_loop (~1 s)   │─────▶│ evaluate_and_record()     │  │
│  │ propose → evaluate │      │ rules_python: 11 policies │  │
│  │ → execute or STOP  │      │ risk score • circuit      │  │
│  └─────────┬──────────┘      │ breaker • signed receipt  │  │
│            │                 └───────────────────────────┘  │
│  ┌─────────▼──────────┐      ┌───────────────────────────┐  │
│  │ Planner            │      │ Site intelligence         │  │
│  │ Muse Spark Open    │      │ Tavily → firewall →       │  │
│  │ Muse Spark (camera)│      │ two-source rule →         │  │
│  │ (plan / replan)    │      │ tighten-only hazard zones │  │
│  │ Gemini (secondary) │      │ (gate reads geometry only)│  │
│  │ Deterministic      │      └───────────────────────────┘  │
│  │ + planner lessons  │      ┌───────────────────────────┐  │
│  └────────────────────┘      │ Governed rule changes     │  │
│                              │ propose → replay →        │  │
│                              │ benchmark → approve →     │  │
│                              │ activate → rollback       │  │
│                              └───────────────────────────┘  │
│                                                              │
│  Data: Mission ──< Run ──< Event (hash-chained)              │
│                        ├──< TelemetrySample                  │
│                        ├──< GovernanceDecisionRecord         │
│                        └──< OperatorApproval                 │
│        PolicyVersion • PolicyProposal • PolicyActivation •   │
│        CircuitBreakerState • AgentMemoryEntry • MissionAudit │
│        SQLAlchemy • Alembic • SQLite (dev) • PostgreSQL 16   │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP (+ X-Sim-Token)
┌──────────────────────▼──────────────────────────────────────┐
│                    Simulator Layer                            │
│                                                              │
│  SimAdapter: /telemetry • /world • /command • /scenario •    │
│              /seed • /frame • /path/smooth                   │
│                                                              │
│  Warehouse simulator (sim/warehouse_sim, port 8090)          │
│  Same engine as the benchmark (backend/bench/world.py):      │
│  40 m × 25 m • 4 zones • 9 solid racks • 20 bays •           │
│  workers and forklift • hazards on demand • seeded replay    │
│                                                              │
│  Future: Gazebo • Isaac Sim • Physical robot interfaces      │
└─────────────────────────────────────────────────────────────┘
```

## Runtime Loop Detail

The governance loop runs inside `RunService._run_loop()` ([`run_service.py`](../backend/app/services/run_service.py)), about once a second per active run:

```
┌─────────────┐
│  Poll       │ GET /telemetry from simulator; add active hazard zones
│  Telemetry  │ Store TelemetrySample
└──────┬──────┘
       ▼
┌─────────────┐
│  Diagnose   │ Distance to goal, waypoint reached?, stagnation,
│  State      │ inside a hazard zone?
└──────┬──────┘
       ▼
┌─────────────┐
│  Propose    │ Next waypoint of the approved plan (consumed on arrival)
│  Action     │ or a planner proposal; replan after repeated denials
└──────┬──────┘
       ▼
┌─────────────┐
│  Evaluate   │ GovernanceEngine.evaluate_and_record(telemetry, proposal)
│  Governance │ → APPROVED / DENIED / NEEDS_REVIEW
│             │ → risk_score, policy_hits, reasons, policy_state
└──────┬──────┘
       ▼
┌─────────────┐
│  Record     │ Append DECISION event (hash-chained)
│  Decision   │ Store GovernanceDecisionRecord with Ed25519 signature
└──────┬──────┘     and the policy version it was judged under
       ▼
┌─────────────┐
│  Execute    │ APPROVED → POST /command
│  or STOP    │ DENIED / hard NEEDS_REVIEW → STOP sent and recorded
│             │ Append EXECUTION event
└──────┬──────┘
       ▼
┌─────────────┐
│  Broadcast  │ WebSocket → operator dashboard
└──────┬──────┘
       ▼
┌─────────────┐
│  End of run │ Safety validation; lessons distilled from the
│             │ gate's decision records
└─────────────┘
```

## Policy Engine

The engine evaluates a proposal against all 11 policies in [`policy_catalog.yaml`](../backend/app/policies/policy_catalog.yaml) and [`rules_python.py`](../backend/app/policies/rules_python.py), and returns a composite decision:

```
Input: telemetry + hazard zones + ActionProposal(intent, params, rationale)
                           │
  GEOFENCE_01 · SAFE_SPEED_01 · HUMAN_PROXIMITY_02 · HUMAN_CLEARANCE_02
  OBSTACLE_CLEARANCE_03 · UNCERTAINTY_04 · HITL_05 · WORKER_PROXIMITY_06
  PATH_CLEARANCE_07 · HAZARD_EXCLUSION_08 · HAZARD_SLOW_09
                           │
            policy_hits + risk_score (max of hits)
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
      APPROVED          DENIED         NEEDS_REVIEW
      (no hits)       (hard deny)      (risk ≥ 0.75)
```

**State machine:** SAFE → SLOW → STOP → REPLAN. STOP takes priority over SLOW; REPLAN means the path is blocked and the planner must find another route.

Thresholds change only through governed proposals ([`proposals.py`](../backend/app/policies/proposals.py)). Fixed safety floors in code label moves safe or unsafe, and no proposal can change them.

## Chain of Trust

Every decision creates an immutable `Event` record:

```json
{
  "id": "evt_abc123",
  "run_id": "run_xyz",
  "ts": "2026-10-22T10:00:00Z",
  "type": "DECISION",
  "payload_json": {
    "context": { "telemetry": {...}, "mission_goal": {...} },
    "proposal": { "intent": "MOVE_TO", "params": {...} },
    "governance": { "decision": "APPROVED", "risk_score": 0.12, "policy_state": "SAFE" }
  },
  "hash": "sha256(canonical(payload + prev_hash))",
  "prev_hash": "previous_event_hash"
}
```

The `prev_hash` field links the chain: tampering with any event invalidates every later hash. Verify with `GET /compliance/verify/{run_id}`.

Each governance decision is also signed with Ed25519 (what was proposed, what the gate saw, the rules version, the outcome). Verify with `GET /governance/receipts/{run_id}/{id}/verify`; the public key is at `GET /governance/signing-key`.

## Trust Boundaries

| Input | Trusted? | Where it can go |
|---|---|---|
| Gate decision records | Yes (deterministic) | Audit chain, receipts, planner lessons |
| Muse Spark / Muse Spark Open output | No | Proposals only; every one passes the gate, and no model can issue a permit |
| Perception output (SAM 3.1) | No | Cross-checked with the sensors; misses are logged; unconfirmed sightings become short slow zones (tighten only) |
| Tavily results, bulletins | No | Firewall → fixed rules → tighten-only zones; planner gets sanitised notes in a fenced untrusted block; the gate gets none |
| Planner lessons | Advisory | Planner prompt only; scoped to the policy version |

## Deployment

```
┌──────────────────────────────────────────┐
│        Single VM (e.g. Scaleway)         │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │ Caddy :80/443 (automatic HTTPS)  │    │
│  └────┬─────────────────────┬───────┘    │
│       │ /                   │ /api /ws   │
│  ┌────▼─────┐        ┌──────▼───────┐    │
│  │ frontend │        │   backend    │    │
│  │ :3000    │        │   :8080      │────┼──▶ Meta Model API, Baseten
│  └──────────┘        └──┬────────┬──┘    │    (Muse Spark, SAM 3.1, Open)
│                         │        │       │
│               ┌─────────▼──┐ ┌───▼──────┐│
│               │ sim :8090  │ │PostgreSQL││
│               │ (warehouse)│ │  :5432   ││
│               └────────────┘ └──────────┘│
└──────────────────────────────────────────┘

```

- One Docker Compose stack: [`docker-compose.yml`](../docker-compose.yml) (production deployment to be added)
- Public-demo guardrails (`PUBLIC_DEMO=true`): one run at a time, hourly budgets, auto-stop, read-only rule changes
- The safety benchmark runs headless: see [`backend/bench/README.md`](../backend/bench/README.md)

