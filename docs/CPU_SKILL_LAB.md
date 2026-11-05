# CPU skill lab

An optional, local-first experiment in learning and controlled reuse of one
pick-and-place behavior. It uses native MuJoCo CPU physics and the existing
Next.js/Three.js workspace. Isaac Sim and a dedicated GPU are not required.

## What is actually learned

Robot A is a three-axis Cartesian gantry with a parallel two-finger gripper.
Twelve seeded expert executions produce measured joint-state observations and
continuous position/gripper targets. Those observations and labels are retained
in a compressed NumPy dataset with pickle disabled by consumers; no external
model, paid API or pretrained network is used.

An affine behavior-cloning policy is fitted with NumPy least squares. Its input
is the measured joint position, source/destination coordinates and one of eight
task phases. Its output is five actuator targets. The phase sequence and
completion criteria are programmed; task decomposition, vision, sensing and
arbitrary skill discovery are not learned. This intentionally small linear task
can achieve extremely low fitting error; that is not evidence of general robotics
intelligence or readiness for an industrial cleanroom.

Every execution creates fresh MuJoCo model/data. The free container moves through
gravity and contact/friction forces. There is no grasp weld, attachment, object
teleport or expert-target fallback during learned execution. `qpos` is assigned
only to set initial conditions. A compatible recipient uses the same learned
weights without retraining, with a new held-out source/destination.

## Evaluation and transfer

- Training: seeds 71–82, twelve executions on the source robot.
- Evaluation: seeds 9001–9006, disjoint positions, six executions with bounded
  mass/inertia and friction variation. All must succeed.
- Counterfactual: zero the learned gripper outputs. This no-grip ablation must
  fail before evaluation can pass.
- Recipient execution: seeds 12001–12100, separate from training and evaluation.
  The workspace currently uses seed 12001.
- Success requires a measured lift above 0.12 m, final XY error below 0.035 m,
  and a settled object height close to the modeled floor-supported height.

Small numerical placement errors are properties of this simple simulation with
privileged coordinates and deterministic servos, not physical positioning claims.

## Lifecycle and controller

`trained → evaluated → approved → released → installed → grant → execute`

Evaluation failure blocks approval. Approval and release are separate actions
on an exact digest. A release lasts one hour. Robot B and Robot A share the exact
gantry profile; Robot C is deliberately incompatible and refused.

The artifact binds learned weights, dataset hash, engine version, runtime code
hash, XML environment hash and capability profile. Changing any of these requires
new validation rather than silently inheriting an approval.

Installation does not move anything. Execution requires an HMAC-signed grant
binding the artifact digest, recipient, environment, task seed, controller
generation, fleet authority epoch, expiry and work limits. Grants expire after
30 seconds and are durably consumed before physics starts. A crash after
consumption does not permit replay; inspect the interrupted attempt and obtain
fresh permission.

Local control bounds target positions, command slew, joint velocity, actuator
forces, control ticks and wall time. Lab stops and fleet stops do not depend on
planning models. Reset does not restore an old grant: controller generations
and fleet epochs prevent resurrection. Withdrawal can interrupt an active lab
execution and prevents subsequent starts. This differs from a routing caution
withdrawal, which affects subsequent route retrieval rather than cancelling
navigation commands already admitted.

One worker runs training/evaluation/execution at a time, outside the async API
event loop. Stop and withdrawal do not wait for that worker lock. Mutation
invalidates the controller's eligibility snapshot immediately; full signed-ledger
verification also runs periodically (at most 100 ms of wall time between checks).
The lab is single-process software. It is not a safety-rated hardware controller
and must not be used to drive a physical robot.

## Enable and use

Install from the root, in the environment running the backend:

```powershell
.\.venv\Scripts\python.exe -m pip install -e './backend[skills]'
$env:SKILL_LAB_ENABLED='true'
$env:MUJOCO_GL='disable'
```

Start/restart a backend with that flag, leaving active mission processes alone.
Sign in as an operator and open `/skills`. Training, evaluation, approval,
release, install, grants, execution and stop reset require an operator token
even in development. Read access follows the site's existing viewer policy.
The stop input accepts viewers under that policy.

For Docker, set `BACKEND_EXTRAS=postgres,skills` and `SKILL_LAB_ENABLED=true`
in the relevant Compose environment file and rebuild the backend. Defaults keep
the optional experiment disabled. No live production deployment was changed as
part of the local implementation.

The two 3D views are explicitly labelled **recorded CPU physics replay**. They
display the expert demonstration and recipient trace after backend work finishes;
they are not a live camera feed or a simultaneous whole-warehouse physics engine.
The existing warehouse geometry, robots and navigation remain separate.

## Persistence and API

Files are based on `AUTHORITY_DB_PATH`:

- `<path>.skills.sqlite`: HMAC-signed lifecycle, grant and outcome events.
- `<path>.skills.sqlite.anchor.sqlite`: independent inventory/checkpoint ledger.
- `<path>.skills.sqlite.artifacts/`: retained compressed demonstration datasets.

Persist all three and protect the checkpoint and signing secret independently.
The current trust model cannot defend against an administrator who replaces both
all records and all trust anchors. There is no validated multi-process writer or
high-availability worker deployment.

| Endpoint | Action |
| --- | --- |
| `GET /skills` | Status, versions, evaluation, installations and attempt evidence |
| `POST /skills/train` | Collect demonstrations and train a new immutable version |
| `POST /skills/{version}/evaluate` | Run held-out evaluation and no-grip ablation |
| `POST /skills/{version}/approve` | Approve a passed exact version |
| `POST /skills/{version}/release` | Release an approved version for one hour |
| `POST /skills/{version}/withdraw` | Remove eligibility, including during execution |
| `POST /skills/{version}/install` | Install on a compatible lab recipient |
| `POST /skills/{version}/grant` | Issue a bounded single-use execution grant |
| `POST /skills/execute` | Verify and consume a grant, execute and record outcome |
| `POST /skills/stop`, `/skills/reset` | Latch a stop / operator reset |

Version actions carry `digest`; install/grant also carry `robot_id`; grant accepts
the bounded execution `seed`. Execute takes the signed envelope returned by grant.
The frontend does not automatically retry mutating requests.

## Validation

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_cpu_skills.py -q
```

Tests perform actual CPU physics and training, held-out evaluation, same-model
recipient execution, no-grip failure, compatibility rejection, lifecycle ordering,
single-use/restart behavior, expiry, stop/reset fencing, fleet epoch revocation,
withdrawal during execution, model/dataset/ledger tampering and API roles.
Generated evidence is under ignored `backend/data/cpu-skill-validation/`.

Docker/GPU/hardware validation is not implied by these local tests. Next steps
would expand the task distribution, measure disturbances/noise, add harder
holdouts and only then consider different robot geometries or physical hardware.
