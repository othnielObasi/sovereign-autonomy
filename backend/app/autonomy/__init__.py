"""Execution authority for AI-planned robot actions.

A model may propose an action; only a signed, single-use permit for that exact
action, issued against fresh world state and not revoked by a kill switch, lets
it reach the controller. Built during the Meta Global AI Developer Hackathon.

Modules:
  permit        permit wire format (standard library only; also used by the simulator)
  core          world state, kill switches, permit store, checkpoints, path checks
  intelligence  graph routing, signed experience, canaries, mission scope
  operations    budgets, watchdog, corridor reservations, evidence log, dispatch

Import from the submodules; this package deliberately imports nothing, so the
simulator can load `permit` without the backend's other dependencies.
"""
