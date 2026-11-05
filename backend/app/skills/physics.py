"""CPU MuJoCo pick-and-place. No rendering, teleports or grasp welds at runtime.

The small robot is a Cartesian gantry with three actuated prismatic joints and
two fingers. A fixed eight-phase task scaffold is explicit; continuous joint and
gripper targets are learned by linear behaviour cloning from expert rollouts.
This is state-based imitation, not vision learning or arbitrary skill discovery.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

try:
    import numpy as np
except ImportError:  # Optional lab must not break navigation-only installations.
    np = None

PHASES = ('approach', 'descend', 'grasp', 'lift', 'transfer', 'lower', 'release', 'retreat')
PROFILE = 'cpu-cartesian-gripper-v1'
ENVIRONMENT = 'cpu-container-bench-v1'
XML_PATH = Path(__file__).with_name('gantry.xml')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def environment_hash():
    return hashlib.sha256(XML_PATH.read_bytes()).hexdigest()


def features(q, source, target, phase):
    # Phase-conditioned affine policy. Observations are measured joint positions
    # and task coordinates; weights, rather than a recorded trajectory, determine
    # every continuous target during learned-policy execution.
    base = np.array([1., *q[:3], *source, *target], dtype=float)
    result = np.zeros((len(PHASES), len(base)))
    result[phase] = base
    return result.ravel()


def expert(source, target, phase):
    xy = source if phase < 4 else target
    height = .23 if phase in (0, 3, 4, 7) else .085
    close = .046 if phase in (2, 3, 4, 5) else 0.
    return np.array([*xy, height - .4, close, close])


def scenario(seed, *, heldout=False):
    rng = np.random.default_rng(seed)
    # Disjoint seeded holdout positions; targets stay within the gantry workspace.
    shift = .012 if heldout else 0.
    return ([-.22 + rng.uniform(-.07, .07), rng.uniform(-.10, .10) + shift],
            [.22 + rng.uniform(-.07, .07), rng.uniform(-.10, .10) - shift])


def rollout(source, target, *, weights=None, collect=False, guard=None, trace=True, mass_scale=1., friction=2.):
    import mujoco
    model = mujoco.MjModel.from_xml_path(str(XML_PATH))
    model.body('container').mass[0] *= mass_scale
    model.body('container').inertia[:] *= mass_scale
    model.geom_friction[:, 0] = friction
    data = mujoco.MjData(model)
    data.qpos[:5] = [0, 0, -.17, 0, 0]
    # Initial-condition setup only. After this point, all object movement comes
    # from contact forces and gravity; no qpos assignments, welds or attachments.
    data.joint('container_free').qpos[:3] = [*source, .026]
    data.joint('container_free').qpos[3:] = [1, 0, 0, 0]
    mujoco.mj_forward(model, data)
    inputs, outputs, frames = [], [], []
    max_height, contacts, max_force, steps, reason = .026, 0, 0., 0, None
    started = time.perf_counter()
    command = np.array(data.qpos[:5])
    # At 500 Hz physics, 50 Hz control. The task scaffold has a bounded dwell and
    # timeout; it never substitutes expert targets when a learned action fails.
    for phase in range(len(PHASES)):
        reached_at = None
        for tick in range(150):
            if guard:
                reason = guard()
                if reason:
                    break
            obs = features(data.qpos, source, target, phase)
            action = expert(source, target, phase) if weights is None else obs @ weights
            if not np.isfinite(action).all() or np.any(action < [-.40, -.24, -.325, -.002, -.002]) or np.any(action > [.40, .24, -.10, .052, .052]):
                reason = 'controller_action_out_of_bounds'
                break
            if collect:
                inputs.append(obs.tolist()); outputs.append(action.tolist())
            # Enforce target slew locally. This is not a backend round trip.
            command += np.clip(action-command, [-.008, -.008, -.008, -.003, -.003], [.008, .008, .008, .003, .003])
            data.ctrl[:] = command
            for _ in range(10):
                mujoco.mj_step(model, data)
                steps += 1
                if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all():
                    reason = 'physics_nonfinite'; break
                if np.max(np.abs(data.qvel[:3])) > 2.:
                    reason = 'controller_velocity_limit'; break
            cube = data.body('container').xpos.copy()
            max_height = max(max_height, float(cube[2]))
            max_force = max(max_force, float(np.max(np.abs(data.actuator_force))))
            contacts += sum(1 for c in data.contact if model.geom(c.geom1).name == 'container_geom' or model.geom(c.geom2).name == 'container_geom')
            if trace and tick % 3 == 0:
                frames.append(dict(t=round(float(data.time), 4), phase=PHASES[phase],
                    joints=data.qpos[:5].tolist(), container=cube.tolist(),
                    quaternion=data.body('container').xquat.tolist()))
            if reason:
                break
            # Closing fingers are constrained by contact, so phase completion
            # uses XYZ convergence plus measured dwell rather than ideal finger q.
            reached = np.linalg.norm(data.qpos[:3]-action[:3]) < .008
            if reached:
                reached_at = tick if reached_at is None else reached_at
                if tick - reached_at >= (30 if phase in (2, 6) else 12):
                    break
        if reason:
            break
        if reached_at is None:
            reason = 'phase_timeout'; break
    # Let a released object settle under gravity. No settling after an interrupted
    # execution: the frozen trace is a software stop in this isolated lab.
    if not reason:
        for settle_step in range(150):
            if guard and settle_step % 10 == 0:
                reason = guard()
                if reason:
                    break
            mujoco.mj_step(model, data)
            steps += 1
        frames.append(dict(t=float(data.time), phase='settled', joints=data.qpos[:5].tolist(),
                           container=data.body('container').xpos.tolist(), quaternion=data.body('container').xquat.tolist()))
    final = data.body('container').xpos.copy()
    error = float(np.linalg.norm(final[:2]-target))
    success = not reason and error < .035 and abs(float(final[2])-.025) < .012 and max_height > .12
    result = dict(success=bool(success), reason=reason or ('placed' if success else 'placement_or_lift_failed'),
        final_position=final.tolist(), target=list(target), source=list(source), placement_error_m=error,
        max_object_height_m=max_height, contact_samples=contacts, max_actuator_force_n=max_force,
        physics_steps=steps, simulated_s=float(data.time), wall_s=time.perf_counter()-started,
        frames=frames, physics='MuJoCo CPU', mujoco_version=mujoco.__version__)
    return result, inputs, outputs


def train(*, seed=71, demonstrations=12, guard=None):
    xs, ys, records = [], [], []
    started = time.perf_counter()
    for index in range(demonstrations):
        source, target = scenario(seed+index)
        result, x, y = rollout(source, target, collect=True, trace=False, guard=guard)
        if not result['success']:
            raise ValueError('demonstration_failed:' + result['reason'])
        xs.extend(x); ys.extend(y); records.append({k:v for k,v in result.items() if k != 'frames'})
    x, y = np.array(xs), np.array(ys)
    weights = np.linalg.lstsq(x, y, rcond=1e-8)[0]
    return dict(schema='cpu-skill-policy-v1', algorithm='phase-conditioned affine behaviour cloning',
        weights=weights.tolist(), profile=PROFILE, environment=ENVIRONMENT, environment_hash=environment_hash(),
        phases=list(PHASES), observation='joint positions + source/target coordinates + phase',
        training_seed=seed, demonstrations=demonstrations, samples=len(xs), dataset_hash=digest(dict(x=xs,y=ys)),
        training_mse=float(np.mean((x@weights-y)**2)), training_wall_s=time.perf_counter()-started,
        demonstrations_summary=records, _dataset=dict(observations=xs, actions=ys))


def evaluate(policy, *, guard=None):
    weights = np.asarray(policy['weights'])
    results = []
    # Frozen test seeds are outside the training range. Include bounded payload
    # and friction variation; this is a small local holdout, not certification.
    for index in range(6):
        source, target = scenario(9001+index, heldout=True)
        result, _, _ = rollout(source, target, weights=weights, trace=False, guard=guard,
                               mass_scale=1.+.05*index, friction=1.6+.1*index)
        results.append(result)
    return dict(passed=all(r['success'] for r in results), successes=sum(r['success'] for r in results),
                trials=len(results), seed_range=[9001,9006], results=results,
                scope='Six CPU simulation holdouts; privileged object coordinates; fixed task phases; no hardware validation')
