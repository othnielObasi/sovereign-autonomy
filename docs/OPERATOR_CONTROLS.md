# Operational human oversight

3 November 2026. This implements the previously record-only `replan` and
`force_approve` actions. Existing changes in the workspace are preserved.

## Replan and hold

An authenticated operator supplies a reason. The service serializes operator
actions per run and sends STOP immediately to fence prior controller requests.
It lets any in-flight dispatch record its acknowledgement/refusal before stopping
the idle loop, then waits up to three seconds for speed <= 0.01 m/s with no
controller target. A paused tick cannot submit another move. If the tick cannot
settle within its bounded timeout, the action fails held and resume cannot overtake
the unsettled tick. It reconciles uncertain commands,
reads current context and hazards, discards the obsolete route, and generates a
replacement to the original mission destination. PLAN and intervention events
persist the result. A restored run therefore sees the replacement, not the
obsolete plan. Humanoid planning retains its 0.30 m/s cap.

The robot remains paused. Resume is an explicit separate action. No route or
route-generation failure leaves an empty plan and a hold; no obsolete route is
silently restored. A controller stop that cannot be verified returns an error and
the service does not claim a successful replan. Emergency stop remains available
during the action. Concurrent ordinary resume is rejected while oversight work
is pending; a concurrent terminal stop prevents publication of a usable route.

## Approve an eligible uncertainty review

The API name `force_approve` is retained for compatibility; the UI calls it
**Approve review and resume**. It is not a general safety-policy override.

Approval requires all of the following:

- Signed-in operator/admin, paused active run, a reason, and the exact latest
  decision event ID the operator selected.
- A recent NEEDS_REVIEW decision, a valid signed receipt matching its proposal,
  and the same active policy version.
- Only `UNCERTAINTY_04` and/or `HITL_05` policy hits, with no hard failure. Speed,
  proximity, clearance, geofence, path and hazard violations cannot be approved.
- A verified stop, current assigned-robot telemetry, unchanged site/map/platform/
  controller boot identity, and no significant movement since the review.
- Fresh gate evaluation still finds the proposal eligible; no covering kill lock.

A lease lasts 120 seconds. Its row identity, reviewer, action binding, timestamps,
review-event reference and reason are Ed25519-signed. Unsigned or edited lease
rows cannot authorize a move. The versioned signature envelope uses the existing
notes column; approval-history responses still expose the human-readable reason. It binds robot, exact intent/parameters, controller
boot/generation, site/map/platform, active policy hash, hazard constraints,
review-policy hits and authority revocation epoch. Duplicate approval of the same
recorded decision is refused instead of extending its lease. Kill/reset epochs,
controller STOP/reset fencing and changed context prevent reuse.

On resume, the normal run loop reevaluates fresh telemetry. It may recognize the
lease only for eligible uncertainty. The reviewed result retains its reasons,
policy hits and risk and records the named reviewer/approval ID in the signed
receipt. Every MOVE_TO still needs a separate fresh, single-use controller permit.
Expiration or a new hard failure prevents further approved movement. Candidate
rule replay does not apply live human-approval leases.

`POST /operator/approve` grants the same checked lease without resuming;
`POST /operator/override` with `force_approve` grants it and resumes. Both require
`decision_event_id`. Generic resume does not approve a review. Replan revokes the
run's existing leases. Plain resume checks the assigned robot and planner-agent
kill scopes as well as global/mission stops.

## UI

Mission Control and the full run page share `OperatorActions`. The controls
require a reason, explain whether an eligible review exists, show failures, and
confirm a route remains held. The older misleading **Override & Resume** label
has been replaced by an ordinary **Resume mission** action alongside explicit
review controls. Robot/run changes remount the form to avoid retaining another
mission's status message or justification.

## Verification

`backend/tests/test_operator_controls.py` exercises API roles/states, route
replacement and restoration, no-route/failure holds, fresh review matching,
expiration, context/epoch/policy changes, hard-limit refusal, duplicate requests,
tampered/unsigned lease rejection, and settlement of an in-flight tick. Its real-controller case uses test-only
uncertain sensor observations and a real signed redemption callback: review,
permit admission, measured humanoid movement, replan and verified stop. It does
not add a production uncertainty-injection or review-bypass endpoint.

`tests/operator-controls.browser.cjs` exercises real isolated services and both
UI locations, explicit resume, held robot position, saved routes, mobile layout
and event-chain verification. Ordinary paused missions have review approval
disabled. Runtime/model uncertainty is covered by the real-controller backend
case; the browser check does not fake an eligible production review.

Final results and screenshots are recorded in
[operator validation](validation/2026-11-03-operator-controls/README.md).

The delayed-acknowledgement regression deliberately spends authority at the
controller, holds its response, and requests replan concurrently. STOP advances
the controller generation; the delayed move is refused and its outcome is
recorded before reconciliation. No action is guessed, retried or left in doubt
by cancelling its acknowledgement. Emergency stop remains responsive throughout.
