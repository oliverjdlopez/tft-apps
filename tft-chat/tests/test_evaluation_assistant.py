"""Verify captured evaluation controls, provenance, and failure cleanup."""
import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from agents import RunContextWrapper

from domain.runtime.models import AssistantRunContext, ToolActivity
from domain.resources.models import ResourceRead
from dev.assistants import capture, registry_from_files
from evals.assistant_execution import execute_captured


@pytest.mark.parametrize('settings,surface', [
    ({'workspace_lineage': {'origin': 'repository'}}, 'eval'),
    ({'workspace_lineage': {'draft_revision': 'revision'}}, 'specs'),
    ({'workspace_trial': True}, 'specs'),
    ({'surface': 'playground'}, 'playground'),
])
@pytest.mark.parametrize('fail', [False, True])
def test_captured_execution_preserves_controls_and_failed_run_evidence(monkeypatch, settings, surface, fail):
    """Durable candidates and SDK settings retain typed state and actual instruction hashes."""
    graph = capture(registry_from_files({
        'root': {'system.md': 'Frozen root', 'task.md': 'TASK',
                 'agent.json': '{"model":"gpt-6-sol","resources":{"skills":[]},"handoffs":["child"]}'},
        'child': {'system.md': 'Frozen child', 'agent.json': '{"model":"gpt-6-sol","resources":{"skills":[]}}'},
    }))
    observed = []
    resource_read = ResourceRead(
        id='fixture/reference', path='fixture/reference.md', kind='reference',
        sha256='source-hash', content='Read before generation completes.', record_ids=('record-1',),
    )

    async def run(agent, *, input, context, hooks, max_turns, run_config):
        """Exercise dynamic instruction callbacks without a model or database connection."""
        assert isinstance(context, AssistantRunContext)
        assert context.runtime.surface == surface
        assert hooks is not None and max_turns == 7
        assert input[0]['content'] == 'Earlier question'
        assert input[1]['content'] == 'Earlier reply'
        assert input[2]['content'] == 'TASK\n\n## Input\n\nLatest question'
        assert run_config.model_settings.temperature == 0.2
        assert run_config.model_settings.max_tokens == 800
        assert run_config.tracing_disabled == bool(settings.get('workspace_trial'))
        wrapper = RunContextWrapper(context)
        for target in [agent, *agent.handoffs]:
            assert target.model == 'gpt-6-luna'
            target.instructions(wrapper, target)
        context.activity.calls['pending'] = ToolActivity(call_id='pending', name='test_tool')
        context.activity.resource_reads[resource_read.id] = resource_read
        observed.append(context)
        if fail:
            raise ValueError('model failure')
        return SimpleNamespace(final_output='answer')

    monkeypatch.setattr('agents.Runner.run', run)
    result, metadata = asyncio.run(execute_captured('Latest question', {
        **settings, 'assistant': 'root', 'captured_graph': graph, 'model': 'gpt-6-luna', 'max_turns': 7,
        'prompt_candidates': {'root': {'text': 'Root candidate'}, 'child': {'text': 'Child candidate'}},
        'model_settings': {'temperature': 0.2, 'max_tokens': 800},
        'messages': [{'role': 'user', 'content': 'Earlier question'},
                     {'role': 'assistant', 'content': 'Earlier reply'},
                     {'role': 'user', 'content': 'Latest question'}],
    }))
    assert bool(result) != fail
    assert metadata['assembled_instructions'] == {'root': 'Root candidate', 'child': 'Child candidate'}
    assert set(metadata['instruction_hashes']) == {'root', 'child'}
    assert metadata['captured_graph_hash'] == graph['hash']
    assert metadata['resources'] == {'reads': [{
        'id': resource_read.id, 'path': resource_read.path, 'kind': 'reference',
        'sha256': 'source-hash',
        'content_sha256': hashlib.sha256(resource_read.content.encode()).hexdigest(),
        'record_ids': ['record-1'],
    }]}
    assert set(metadata['activity']) == {'calls', 'handoffs'}
    assert metadata['activity']['calls']['pending']['status'] == 'failed'
    assert metadata['run_model_settings'] == {'temperature': 0.2, 'max_tokens': 800}
    assert observed[0].activity.calls['pending'].status == 'failed'
    if fail:
        assert metadata['execution_error'] == 'ValueError: model failure'
