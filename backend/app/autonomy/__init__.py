"""Execution authority for AI-planned robot actions.

A model may propose an action; only a signed, single-use permit for that exact
action, issued against fresh world state and not revoked by a kill switch, lets
it reach the controller. Built during the Meta Global AI Developer Hackathon.
"""
from .core import (Action, CheckpointStore, KillSwitch, PermitStore, Rejected,
                   TrajectoryValidator, WorldState, canonical)
from .intelligence import CanaryRegistry, Experience, MissionIntegrity, RouteGraph, TrustedExperience
from .operations import Budget, CorridorReservations, EvidenceLog, SafeDispatcher, Watchdog

__all__ = [
    "Action", "Budget", "CanaryRegistry", "CheckpointStore", "CorridorReservations", "EvidenceLog",
    "Experience", "KillSwitch", "MissionIntegrity", "PermitStore", "Rejected", "RouteGraph",
    "SafeDispatcher", "TrajectoryValidator", "TrustedExperience", "Watchdog", "WorldState", "canonical",
]
