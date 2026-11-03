const ts = require('../frontend/node_modules/typescript');
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync('frontend/src/lib/runPresentation.ts', 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const sandbox = { exports: {} }; vm.runInNewContext(code, sandbox);
const display = sandbox.exports.executionPresentation;
const ack = { status: 'running', decision: { payload: { governance: { decision: 'APPROVED' } } },
  execution: { ts: '2026-11-03T20:00:01', payload: { command: { intent: 'MOVE_TO', params: { x: 6, y: 19 } }, result: { ok: true, set_target: { x: 6, y: 19 } }, verified: true } } };
const tel = { speed: .3, target: { x: 6, y: 19 } };
const cases = [
  ['Fresh acknowledged target with speed', ack, tel, true, 'running', 'Movement observed'],
  ['Telemetry expired', ack, tel, false, 'running', 'Movement unconfirmed'],
  ['Speed without matching target', ack, { speed: .3, target: { x: 30, y: 12 } }, true, 'running', 'Command acknowledged'],
  ['Acknowledgment without motion', ack, { ...tel, speed: 0 }, true, 'running', 'Command acknowledged'],
  ['Approval alone', { ...ack, execution: null }, tel, true, 'running', 'Awaiting admission'],
  ['New permit refusal overrides prior acknowledgment', { ...ack, authority: { ts: '2026-11-03T20:00:02', payload: { event: 'permit_refused', reason: 'trajectory_obstacle_clearance' } } }, tel, true, 'running', 'Movement refused'],
  ['Controller refusal with no reason remains refused', { ...ack, authority: { ts: '2026-11-03T20:00:02', payload: { event: 'controller_refused' } } }, tel, true, 'running', 'Movement refused'],
  ['Rejected execution despite approved policy', { ...ack, execution: { payload: { result: { ok: false, rejected: true }, verified: false } } }, tel, true, 'running', 'Movement refused'],
  ['Unknown controller outcome is not a refusal or success', { ...ack, execution: { payload: { result: { ok: false, reason: 'controller_outcome_unknown:timeout' } } } }, tel, true, 'running', 'Movement unconfirmed'],
  ['Paused run overrides old movement', ack, tel, true, 'paused', 'Mission paused'],
  ['Historical completed run is not live movement', ack, tel, true, 'completed', 'Mission completed'],
  ['Needs review overrides previous acknowledgment', { ...ack, decision: { payload: { governance: { decision: 'NEEDS_REVIEW' } } } }, tel, true, 'running', 'Review required'],
  ['Held policy overrides previous acknowledgment', { ...ack, decision: { payload: { governance: { decision: 'DENIED' } } } }, tel, true, 'running', 'Movement held'],
  ['Permit admission alone is not observed motion', { ...ack, authority: { ts: '2026-11-03T20:00:02', payload: { event: 'permit_used' } } }, tel, true, 'running', 'Move admitted'],
  ['STOP acknowledged', { ...ack, execution: { payload: { command: { intent: 'STOP' }, result: { ok: true }, verified: true } } }, tel, true, 'running', 'Stopped by command'],
];
for (const [name, s, t, fresh, status, expected] of cases) { assert.equal(display(s, t, fresh, status).label, expected, name); console.log('PASS', name); }
console.log(cases.length + ' execution presentation checks passed');
