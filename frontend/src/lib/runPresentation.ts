/** Policy approval, controller admission and observed motion are distinct facts. */
export function executionPresentation(summary: any, telemetry: any, fresh: boolean, status?: string) {
  const state = status || summary?.status;
  const p = summary?.execution?.payload;
  const a = summary?.authority;
  const latestAuthority = a && (!summary?.execution || a.ts > summary.execution.ts);
  const refusal = latestAuthority && ['permit_refused', 'dispatch_refused', 'controller_refused'].includes(a.payload?.event)
    ? a.payload?.reason || 'Controller refused the action' : p && (p.result?.ok === false || p.result?.rejected || p.verified === false)
      ? p.result?.reason || p.result?.error || 'Controller did not acknowledge the action' : null;
  if (['completed', 'stopped', 'failed', 'failed_safety'].includes(state)) return { label: state === 'completed' ? 'Mission completed' : `Mission ${state.replaceAll('_', ' ')}`, detail: 'Historical outcome. Live fleet positions are separate from this record.', tone: state === 'completed' ? 'ok' : 'warn' };
  if (state === 'paused') return { label: 'Mission paused', detail: refusal || 'Inspect the hold or review reason before explicitly resuming.', tone: 'warn' };
  if (p?.result?.reason?.startsWith('controller_outcome_unknown')) return { label: 'Movement unconfirmed', detail: 'Controller outcome is unknown. Hold and inspect evidence before resuming.', tone: 'warn' };
  if (refusal) return { label: 'Movement refused', detail: refusal.replaceAll('_', ' '), tone: 'stop' };
  if (!fresh) return { label: 'Movement unconfirmed', detail: 'Waiting for fresh robot telemetry.', tone: 'warn' };
  if (!summary) return { label: 'Checking execution', detail: 'Waiting for recorded controller evidence.', tone: 'warn' };
  const decision = summary.decision?.payload?.governance;
  if (decision?.decision && decision.decision !== 'APPROVED') return { label: decision.decision === 'NEEDS_REVIEW' ? 'Review required' : 'Movement held', detail: decision.reasons?.[0] || decision.required_action || 'Inspect the current decision.', tone: 'warn' };
  if (latestAuthority && a.payload?.event === 'permit_used') return { label: 'Move admitted', detail: 'Controller admission recorded; waiting for command acknowledgment.', tone: 'info' };
  if (p?.command?.intent === 'STOP') return { label: 'Stopped by command', detail: 'A STOP acknowledgment is recorded. Inspect the reason before continuing.', tone: 'warn' };
  if (p?.command?.intent === 'WAIT') return { label: 'Waiting', detail: 'The mission is holding movement.', tone: 'warn' };
  if (p?.command?.intent === 'MOVE_TO' && p.verified === true && (p.result?.ok || p.result?.ack)) {
    const target = p.result?.set_target || p.command.params;
    const observed = telemetry?.target;
    const matches = observed && Math.hypot(Number(observed.x ?? observed[0]) - Number(target.x), Number(observed.y ?? observed[1]) - Number(target.y)) < .1;
    if (matches && Number(telemetry?.speed) > .01) return { label: 'Movement observed', detail: 'Acknowledged action and fresh telemetry show progress toward its target.', tone: 'ok' };
    return { label: 'Command acknowledged', detail: 'Movement is not currently observed. Inspect progress and any hold before intervening.', tone: 'info' };
  }
  return { label: state === 'planning' ? 'Preparing a plan' : 'Awaiting admission', detail: 'Policy approval alone is not evidence of robot movement.', tone: 'info' };
}
