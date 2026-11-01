"""Runtime telemetry validation — physics plausibility and anomaly detection.

Catches reward-hacking attempts that rely on spoofed or implausible telemetry:
- Teleportation (impossible position jumps)
- Speed/distance incoherence (reported speed doesn't match actual displacement)
- Impossible sensor readings (negative distances, out-of-range values)
- Frozen telemetry (identical readings repeated → possible replay attack)

Returns validated telemetry with anomaly flags. Hard anomalies trigger
automatic STOP; soft anomalies are logged and flagged for review.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.world_model import GEOFENCE

logger = logging.getLogger("app.telemetry_validator")

# Physics constants for a warehouse robot
MAX_PLAUSIBLE_SPEED_MS = 2.0       # absolute max robot speed (m/s)
MAX_DISPLACEMENT_PER_TICK = 5.0    # max distance between ticks (m) — generous for ~2s ticks
SPEED_DISPLACEMENT_TOLERANCE = 0.5 # tolerance for speed vs displacement mismatch
FROZEN_TICK_THRESHOLD = 8          # identical readings = suspicious
MIN_OBSTACLE_DISTANCE = 0.0        # can't be negative
MAX_HUMAN_DISTANCE = 1000.0        # sanity cap


@dataclass
class TelemetryAnomaly:
    """A detected anomaly in telemetry data."""
    type: str           # TELEPORT, SPEED_INCOHERENT, IMPOSSIBLE_VALUE, FROZEN, BOUNDS
    severity: str       # hard (auto-stop) or soft (flag + continue)
    detail: str
    field: str          # which telemetry field triggered it
    value: Any = None   # the problematic value


@dataclass
class ValidationResult:
    """Result of telemetry validation."""
    valid: bool                          # False if any hard anomaly detected
    anomalies: List[TelemetryAnomaly] = field(default_factory=list)
    hard_anomaly: bool = False           # True if robot should be stopped
    telemetry: Dict[str, Any] = field(default_factory=dict)  # the validated telemetry

    @property
    def anomaly_count(self) -> int:
        return len(self.anomalies)


class TelemetryValidator:
    """Stateful per-run telemetry validator.

    Maintains a sliding window of recent readings for cross-tick validation.
    Create one per run — not shared across runs.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._prev_position: Optional[tuple[float, float]] = None
        self._prev_speed: Optional[float] = None
        self._prev_reading: Optional[Dict[str, Any]] = None
        self._frozen_count: int = 0
        self._tick_count: int = 0
        self._total_anomalies: int = 0
        self._anomaly_history: List[TelemetryAnomaly] = []

    def validate(self, telemetry: Dict[str, Any]) -> ValidationResult:
        """Validate a single telemetry reading against physics and history.

        Call this once per tick, before governance evaluation.
        """
        self._tick_count += 1
        anomalies: List[TelemetryAnomaly] = []

        x = float(telemetry.get("x", 0.0))
        y = float(telemetry.get("y", 0.0))
        speed = float(telemetry.get("speed", 0.0))
        nearest_obstacle = float(telemetry.get("nearest_obstacle_m", 999.0))
        human_distance = float(telemetry.get("human_distance_m", 999.0))

        # --- Check 1: Impossible values ---
        if speed < 0:
            anomalies.append(TelemetryAnomaly(
                type="IMPOSSIBLE_VALUE", severity="hard",
                detail=f"Negative speed: {speed}",
                field="speed", value=speed,
            ))
        if speed > MAX_PLAUSIBLE_SPEED_MS:
            anomalies.append(TelemetryAnomaly(
                type="IMPOSSIBLE_VALUE", severity="soft",
                detail=f"Speed {speed:.2f} exceeds physical max {MAX_PLAUSIBLE_SPEED_MS}",
                field="speed", value=speed,
            ))
        if nearest_obstacle < MIN_OBSTACLE_DISTANCE:
            anomalies.append(TelemetryAnomaly(
                type="IMPOSSIBLE_VALUE", severity="hard",
                detail=f"Negative obstacle distance: {nearest_obstacle}",
                field="nearest_obstacle_m", value=nearest_obstacle,
            ))
        if human_distance < MIN_OBSTACLE_DISTANCE:
            anomalies.append(TelemetryAnomaly(
                type="IMPOSSIBLE_VALUE", severity="hard",
                detail=f"Negative human distance: {human_distance}",
                field="human_distance_m", value=human_distance,
            ))

        # --- Check 2: Position within world bounds (generous margin) ---
        margin = 5.0  # allow some margin beyond geofence for edge cases
        if not (GEOFENCE["min_x"] - margin <= x <= GEOFENCE["max_x"] + margin):
            anomalies.append(TelemetryAnomaly(
                type="BOUNDS", severity="hard",
                detail=f"X position {x:.2f} far outside world bounds",
                field="x", value=x,
            ))
        if not (GEOFENCE["min_y"] - margin <= y <= GEOFENCE["max_y"] + margin):
            anomalies.append(TelemetryAnomaly(
                type="BOUNDS", severity="hard",
                detail=f"Y position {y:.2f} far outside world bounds",
                field="y", value=y,
            ))

        # --- Check 3: Teleportation detection ---
        if self._prev_position is not None:
            dx = x - self._prev_position[0]
            dy = y - self._prev_position[1]
            displacement = math.sqrt(dx * dx + dy * dy)

            if displacement > MAX_DISPLACEMENT_PER_TICK:
                anomalies.append(TelemetryAnomaly(
                    type="TELEPORT", severity="hard",
                    detail=f"Position jumped {displacement:.2f}m in one tick (max {MAX_DISPLACEMENT_PER_TICK}m)",
                    field="position", value=displacement,
                ))

            # --- Check 4: Speed-displacement coherence ---
            if self._prev_speed is not None:
                avg_speed = (speed + self._prev_speed) / 2
                # Expected displacement ≈ avg_speed * tick_interval
                # We use a generous tolerance since tick intervals vary
                if displacement > 0.1 and avg_speed < 0.01:
                    anomalies.append(TelemetryAnomaly(
                        type="SPEED_INCOHERENT", severity="soft",
                        detail=f"Moved {displacement:.2f}m but reported speed ~0",
                        field="speed", value=speed,
                    ))
                elif displacement < 0.01 and speed > 0.5:
                    anomalies.append(TelemetryAnomaly(
                        type="SPEED_INCOHERENT", severity="soft",
                        detail=f"Reported speed {speed:.2f} but no displacement",
                        field="speed", value=speed,
                    ))

        # --- Check 5: Frozen telemetry (replay attack detection) ---
        if self._prev_reading is not None:
            key_fields = ["x", "y", "speed", "theta", "nearest_obstacle_m", "human_distance_m"]
            identical = all(
                telemetry.get(f) == self._prev_reading.get(f)
                for f in key_fields
                if f in telemetry and f in self._prev_reading
            )
            if identical:
                self._frozen_count += 1
                if self._frozen_count >= FROZEN_TICK_THRESHOLD:
                    anomalies.append(TelemetryAnomaly(
                        type="FROZEN", severity="soft",
                        detail=f"Telemetry frozen for {self._frozen_count} consecutive ticks",
                        field="all", value=self._frozen_count,
                    ))
            else:
                self._frozen_count = 0

        # Update state
        self._prev_position = (x, y)
        self._prev_speed = speed
        self._prev_reading = {k: v for k, v in telemetry.items()
                              if isinstance(v, (int, float, str, bool))}

        # Classify result
        hard_anomalies = [a for a in anomalies if a.severity == "hard"]
        has_hard = len(hard_anomalies) > 0

        self._total_anomalies += len(anomalies)
        self._anomaly_history.extend(anomalies)
        # Keep bounded history
        if len(self._anomaly_history) > 200:
            self._anomaly_history = self._anomaly_history[-100:]

        if anomalies:
            severity_label = "HARD" if has_hard else "SOFT"
            logger.warning(
                "Run %s tick %d: %d telemetry anomalies (%s): %s",
                self.run_id, self._tick_count, len(anomalies), severity_label,
                "; ".join(a.detail for a in anomalies),
            )

        return ValidationResult(
            valid=not has_hard,
            anomalies=anomalies,
            hard_anomaly=has_hard,
            telemetry=telemetry,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics for this run's telemetry validation."""
        type_counts: Dict[str, int] = {}
        for a in self._anomaly_history:
            type_counts[a.type] = type_counts.get(a.type, 0) + 1
        return {
            "run_id": self.run_id,
            "ticks_validated": self._tick_count,
            "total_anomalies": self._total_anomalies,
            "anomaly_types": type_counts,
            "frozen_count": self._frozen_count,
        }
