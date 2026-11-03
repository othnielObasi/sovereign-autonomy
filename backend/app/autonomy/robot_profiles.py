"""Versioned simulator platforms. These describe planar navigation, not motor skills.

The simulator selects a profile from trusted site configuration. Command payloads
cannot select their own platform or relax its limits. Existing AMR limits remain
with the site's policy; the humanoid adds a lower controller-enforced speed cap.
"""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class RobotProfile:
    version: str
    kind: str
    label: str
    radius_m: float
    height_m: float
    max_speed_mps: float | None
    role: str
    actions: tuple[str, ...] = ('MOVE_TO', 'STOP', 'WAIT')

    def public(self) -> dict:
        return asdict(self)


AMR = RobotProfile('sim-amr-radius-0.4m-v1', 'amr', 'Mobile carrier', .4, .65, None,
                   'Material delivery')
HUMANOID = RobotProfile('sim-humanoid-radius-0.35m-speed-0.3mps-v1', 'humanoid',
                        'Humanoid navigator', .35, 1.72, .3, 'QC and packaging navigation')
PROFILES = {p.version: p for p in (AMR, HUMANOID)}


def configured_profile(site: dict, robot_id: str) -> RobotProfile:
    version = (site.get('robot_profiles') or {}).get(robot_id, AMR.version)
    if version not in PROFILES:
        raise ValueError(f'Unknown configured robot capability profile: {version}')
    return PROFILES[version]


def observed_profile(state: dict) -> RobotProfile | None:
    return PROFILES.get(state.get('capability_profile_version'))


def move_violation(profile: RobotProfile | None, params: dict) -> str | None:
    if profile is None or profile.max_speed_mps is None:
        return None
    try:
        speed = float(params.get('max_speed', .5))
        if not math.isfinite(speed) or speed < 0 or speed > profile.max_speed_mps + 1e-9:
            return 'capability_speed_limit'
    except (TypeError, ValueError):
        return 'capability_speed_limit'
    return None
