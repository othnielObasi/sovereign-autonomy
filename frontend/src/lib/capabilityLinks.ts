export const capabilityGroups = [
  { title: 'Assign, plan and coordinate', problem: 'Turn an instruction into a mission that stays on course.', items: [
    ['Mission management', 'Create, assign, save and supervise navigation missions.', '/missions'],
    ['AI planning', 'See the configured planner and the source actually used by a run.', '/runs?inspect=planning'],
    ['Agentic planning', 'Inspect planning context; tool-based proposals depend on the selected provider.', '/runs?inspect=planning'],
    ['Routing', 'Inspect facility paths, obstacles and current robot targets.', '/mission-control?view=2d#facility'],
    ['Fleet coordination', 'Assign independent robots and inspect shared-space constraints.', '/mission-control#fleet'],
    ['Task fidelity', 'Check whether a plan still serves the original goal.', '/runs?inspect=learning'],
  ] },
  { title: 'Observe, adapt and intervene', problem: 'Understand changes and keep operators in control.', items: [
    ['Perception', 'Inspect camera/sensor information and configured vision checks.', '/runs?inspect=intel'],
    ['Environment adaptation', 'Introduce a scenario explicitly and inspect route revalidation.', '/mission-control?panel=scenarios#mission-evidence'],
    ['Human oversight', 'Replace a route and hold, or review eligible uncertainty.', '/mission-control#mission-desk'],
    ['Emergency control', 'Stop independently; release requires authorization.', '/authority#execution-authority'],
    ['Site intelligence', 'Inspect spill guidance, live/offline search and bulletin screening.', '/runs?inspect=intel'],
  ] },
  { title: 'Learn and investigate', problem: 'Find relevant experience and explain recurring operational problems.', items: [
    ['Persistent learning', 'Explore signed route experience, planner lessons and memory search.', '/runs?inspect=memory'],
    ['Learning security', 'Inspect compatibility, freshness, quarantine and source corroboration.', '/authority#learning-evidence'],
    ['Analysis', 'Inspect scorecards, failure insights and plan/execution divergence.', '/runs?inspect=analysis'],
    ['Optimization', 'Review bounded recommendations and their tradeoffs.', '/runs?inspect=optimization'],
    ['Evidence', 'Verify decision signatures and original event chains.', '/evidence?tab=receipts'],
  ] },
  { title: 'Govern, test and recover', problem: 'Change rules deliberately, challenge behavior and continue from known progress.', items: [
    ['Safety governance', 'Inspect effective policy parameters for this deployment.', '/policies'],
    ['Execution authority', 'Inspect admitted/refused actions and permit enforcement.', '/authority#execution-authority'],
    ['Rule management', 'Propose, replay, benchmark, approve, activate and roll back.', '/policies?tab=rules'],
    ['Robustness testing', 'Inspect security drills and specialist adversarial/holdout access.', '/authority#security-drills'],
    ['Recovery', 'Understand interrupted runs, checkpoints and signed backup operations.', '/operations#recovery'],
    ['Operations and twin', 'Inspect dependency health, configuration and the shared facility.', '/operations'],
  ] },
];
export const inspectTabs: Record<string, string> = { planning: 'chain', learning: 'learning', memory: 'analysis', analysis: 'analysis', optimization: 'analysis', intel: 'intel', chain: 'chain' };
export function runInspectionHref(id: string, feature: string) {
  const tab = inspectTabs[feature] || 'learning';
  return `/runs/${encodeURIComponent(id)}?tab=${tab}&focus=${encodeURIComponent(feature)}#${feature === 'planning' ? 'planner-context' : 'run-inspection'}`;
}
