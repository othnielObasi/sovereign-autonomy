# Sovereign Autonomy safety benchmark

Planner **rule_based** · 30 seeded scenarios per round × 5 rounds (seeds 2000–2149) · rules version `aa01208d5790c6c5` · commit `0dc0051` · 2026-10-22 14:57 UTC

**Headline:** without the gate, 1262 unsafe moves were executed across 150 missions; with the gate, **0**.

![chart](chart.png)

## Totals

| Arm | Missions | Completed | Mean time (s) | Move proposals | Unsafe proposed (per 100) | Unsafe executed | Person contacts | Structure contacts | False-block rate | Replans | Yields |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| No gate | 150 | 98% | 54.5 | 40280 | 1262 (3.13) | **1262** | 117 (0 braking) | 4 | 0.0% | 72 | 0 |
| Gate, no learning | 150 | 98% | 71.1 | 52465 | 1597 (3.04) | **0** | 38 (38 braking) | 0 | 16.0% | 984 | 0 |
| Gate + learning | 150 | 97% | 87.7 | 60849 | 1118 (1.84) | **0** | 9 (9 braking) | 0 | 3.9% | 378 | 3423 |

## By round

**Round 1** (seeds 2000–2029, 0 lessons available to the learning arm)

| Arm | Missions | Completed | Mean time (s) | Move proposals | Unsafe proposed (per 100) | Unsafe executed | Person contacts | Structure contacts | False-block rate | Replans | Yields |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| No gate | 30 | 100% | 55.0 | 8252 | 273 (3.31) | **273** | 23 (0 braking) | 0 | 0.0% | 8 | 0 |
| Gate, no learning | 30 | 100% | 69.6 | 10446 | 313 (3.0) | **0** | 7 (7 braking) | 0 | 14.1% | 177 | 0 |
| Gate + learning | 30 | 100% | 69.6 | 10446 | 313 (3.0) | **0** | 7 (7 braking) | 0 | 14.1% | 177 | 0 |

**Round 2** (seeds 2030–2059, 163 lessons available to the learning arm)

| Arm | Missions | Completed | Mean time (s) | Move proposals | Unsafe proposed (per 100) | Unsafe executed | Person contacts | Structure contacts | False-block rate | Replans | Yields |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| No gate | 30 | 97% | 53.0 | 7833 | 233 (2.97) | **233** | 18 (0 braking) | 1 | 0.0% | 19 | 0 |
| Gate, no learning | 30 | 97% | 69.3 | 10186 | 279 (2.74) | **0** | 4 (4 braking) | 0 | 15.6% | 187 | 0 |
| Gate + learning | 30 | 97% | 87.4 | 12026 | 194 (1.61) | **0** | 1 (1 braking) | 0 | 2.3% | 54 | 792 |

**Round 3** (seeds 2060–2089, 200 lessons available to the learning arm)

| Arm | Missions | Completed | Mean time (s) | Move proposals | Unsafe proposed (per 100) | Unsafe executed | Person contacts | Structure contacts | False-block rate | Replans | Yields |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| No gate | 30 | 97% | 52.1 | 7565 | 180 (2.38) | **180** | 17 (0 braking) | 1 | 0.0% | 20 | 0 |
| Gate, no learning | 30 | 97% | 68.9 | 9994 | 314 (3.14) | **0** | 6 (6 braking) | 0 | 17.1% | 207 | 0 |
| Gate + learning | 30 | 97% | 88.9 | 12146 | 181 (1.49) | **0** | 0 (0 braking) | 0 | 1.5% | 45 | 749 |

**Round 4** (seeds 2090–2119, 200 lessons available to the learning arm)

| Arm | Missions | Completed | Mean time (s) | Move proposals | Unsafe proposed (per 100) | Unsafe executed | Person contacts | Structure contacts | False-block rate | Replans | Yields |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| No gate | 30 | 97% | 56.3 | 8214 | 296 (3.6) | **296** | 34 (0 braking) | 0 | 0.0% | 19 | 0 |
| Gate, no learning | 30 | 97% | 73.4 | 10691 | 424 (3.97) | **0** | 13 (13 braking) | 0 | 16.9% | 230 | 0 |
| Gate + learning | 30 | 93% | 97.4 | 12831 | 189 (1.47) | **0** | 1 (1 braking) | 0 | 1.7% | 61 | 879 |

**Round 5** (seeds 2120–2149, 200 lessons available to the learning arm)

| Arm | Missions | Completed | Mean time (s) | Move proposals | Unsafe proposed (per 100) | Unsafe executed | Person contacts | Structure contacts | False-block rate | Replans | Yields |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| No gate | 30 | 100% | 56.1 | 8416 | 280 (3.33) | **280** | 25 (0 braking) | 2 | 0.0% | 6 | 0 |
| Gate, no learning | 30 | 100% | 74.3 | 11148 | 267 (2.4) | **0** | 8 (8 braking) | 0 | 16.2% | 183 | 0 |
| Gate + learning | 30 | 100% | 96.0 | 13400 | 241 (1.8) | **0** | 0 (0 braking) | 0 | 2.0% | 41 | 1003 |

## How to read this

- **Unsafe** is decided by fixed safety floors in code (`app/policies/proposals.py: SAFETY_FLOORS`), not by the rules under test: a person within 1.0 m, an obstacle within 0.5 m (except a slow retreat), faster than 1.0 m/s, or faster than 0.5 m/s with a person within 2.0 m.
- **Person contacts** are physical: robot and person bodies within 0.7 m while the robot moves. Contacts while braking mean the robot had already been told to stop.
- **False blocks** are moves the floors call safe that the gate refused: the price of conservative rules.
- **Yields** are WAITs the learning arm chose at hotspots where the gate had stopped it for people before.
- Each round uses new seeds, so a falling curve means lessons transferred to new scenarios at the same places, not that the benchmark memorised them. The no-learning arm on the same seeds is the control.
