"""Current-run feedback must never become implicit historical fleet learning."""
import asyncio

import pytest

from app.config import settings
from app.schemas.governance import ActionProposal
from app.services.agent_service import AgentRouter


@pytest.mark.parametrize('change', ['robot_id', 'site_id', 'map_version', 'capability_profile_version',
                                    'policy_version', 'unknown_context', 'missing_robot', 'new_run'])
def test_short_term_feedback_is_scoped_to_run_robot_and_context(monkeypatch, change):
    from app.services import agentic_planner
    from app.policies import versioning
    seen = []
    policy = ['rules-v1']

    class FakePlanner:
        def __init__(self):
            self.memory = []

        async def propose(self, *args):
            seen.append(list(self.memory))
            return ActionProposal(intent='WAIT', params={}, rationale='test'), [], 'test-only'

        def record_outcome(self, proposal, governance, was_executed):
            self.memory.append(proposal.rationale)

    monkeypatch.setattr(agentic_planner, 'AgenticPlanner', FakePlanner)
    monkeypatch.setattr(settings, 'llm_enabled', True)
    monkeypatch.setattr(settings, 'llm_provider', 'agentic')
    monkeypatch.setattr(versioning, 'policy_version_hash', lambda: policy[0])
    pose = dict(robot_id='robot-A', site_id='warehouse', map_version='map-v1',
                capability_profile_version='amr-v1', x=3., y=3.)

    async def exercise():
        router = AgentRouter()
        proposal = await router.propose(pose, {}, 'first run')
        router.record_outcome(proposal, None, False)
        await router.propose(pose, {}, 'same run')
        assert seen == [[], ['test']], 'Feedback within the same run must still work'
        next_pose = dict(pose)
        if change == 'new_run':
            router = AgentRouter()  # RunService creates one per run loop.
        elif change == 'policy_version':
            policy[0] = 'rules-v2'
        elif change == 'unknown_context':
            next_pose.pop('map_version')
        elif change == 'missing_robot':
            next_pose.pop('robot_id')
        else:
            next_pose[change] = 'different'
        await router.propose(next_pose, {}, 'next scope')
        assert seen[-1] == [], 'A previous scope cannot supply implicit advice'

    asyncio.run(exercise())
