# Sovereign Autonomy safety benchmark

Seeded warehouse scenarios driven through Sovereign Autonomy, measuring what the gate prevents and what learning changes.

```bash
cd backend
python -m bench run --planner rule_based --rounds 5 --seeds-per-round 30 --out bench/results/rule_based
python -m bench run --planner nemotron --rounds 3 --seeds-per-round 20 --out bench/results/nemotron   # needs NEBIUS_API_KEY
```

Each run writes `results.json` (every scenario, every arm), `README.md` (tables) and `chart.png`.

## What it does

- **Site** ([`layout.json`](layout.json)): the demo warehouse's racks, zones, bays and boundary. Racks are solid. Three static obstacles in the demo world sit in aisle intersections and seal off whole aisles (72 of 380 bay pairs unreachable); here they are moved to the edges so every bay pair is reachable.
- **Engine** ([`world.py`](world.py)): fixed 10 Hz physics, one seeded RNG, edge-to-edge clearances, a robot that turns on the spot, workers, forklifts whose drivers stop for the robot, and spills or dropped pallets that appear ahead of it.
- **Scenarios** ([`scenarios.py`](scenarios.py)): people cross at site hotspots (cross-aisles, corridor, packing stations, dock doors), timed around the robot's arrival. Easy, medium and hard by seed.
- **Arms** ([`runner.py`](runner.py)), on identical worlds:
  - *No gate*: proposals go straight to the robot.
  - *Gate, no learning*: every proposal passes the gate; denials stop the robot; three in a row trigger a replan; the robot follows the gate's speed instructions and backs away slowly when too close to something.
  - *Gate + learning*: as above, plus lessons distilled from earlier rounds' gate decisions.
- **Labels**: a move is *unsafe* by fixed floors in code (`SAFETY_FLOORS`), not by the rules under test. *Person contacts* are physical (bodies within 0.7 m while the robot moves), split into "while braking" (the robot had already been told to stop) and the rest.
- **Rounds** use fresh seeds, so improvement means lessons transferred to new scenarios at the same places.

## Planners

| Planner | What it is |
|---|---|
| `rule_based` | Grid route at each zone's limit. Uses lessons: slows near learned hotspots, caps speed where only slower moves were approved, routes around learned obstacle spots |
| `reckless` | Same route at 0.9 m/s, ignores lessons; a stress test for the speed rules, not a model of a real planner |
| `nemotron` | NVIDIA Nemotron on Nebius Token Factory plans and replans (reasoning tier), with lessons in its prompt |

Models are called only to plan and replan; the 5 Hz step loop is mechanical, as in the live system.

## On Nebius Serverless Jobs

The benchmark is CPU-only and self-contained. One large single round can be split into shards, one per job, then merged:

```bash
# each job (i = 0..3)
python -m bench run --rounds 1 --seeds-per-round 500 --shard i/4 --out /results/shard-i
# then
python -m bench merge /results/shard-*/results.json --out /results/full
```

Learning rounds share lessons, so a learning run is one job. Container: the backend image (`backend/Dockerfile`) with `python -m bench ...` as the command; for `nemotron`, pass `NEBIUS_API_KEY` as a job secret.

## Known limits

- The simulation is 2-D with simple kinematics and perfect-shape geometry; it measures governance behaviour, not a specific robot.
- Person contacts while braking are not zero: a person walking quickly into a robot that is already stopping. The gate cannot prevent those at a 5 Hz check rate; a faster control loop or a larger stop radius would.
- A spill or pallet can leave a goal unreachable; those missions end incomplete with the robot waiting.
