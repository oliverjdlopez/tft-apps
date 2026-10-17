"""Verify progressive reads, dynamic policy, and captured-run isolation."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agents import RunContextWrapper
from agents.tool_context import ToolContext

from domain.assistants import Assistant, AssistantRegistry
from domain.assistants.capture import capture
from domain.assistants.specs import AssistantSpec
from domain.assistants.resources import resource_entries
from domain.resources.library import build_library
from domain.runtime.models import ToolActivity
from domain.tools import get_tool


@pytest.fixture(autouse=True)
def resources(monkeypatch, tmp_path):
    """Supply a real metadata hierarchy and prevent model calls in preparation."""
    import yaml
    references, skills = tmp_path / 'references', tmp_path / 'skills'
    references.mkdir()
    skills.mkdir()
    for resource_id, kind, parent, body in [
        ('set18', 'index', None, 'Directory'),
        ('set18/units', 'index', 'set18', 'Unit directory'),
        ('set18/units/roster', 'reference', 'set18/units', 'PRIVATE REFERENCE'),
        ('set17', 'index', None, 'OTHER SET SECRET'),
    ]:
        path = references / (resource_id.replace('/', '-') + '.md')
        scope = resource_id.split('/')[0].removeprefix('set')
        metadata = {'id': resource_id, 'title': resource_id, 'description': 'Discover resources',
                    'kind': kind, 'parent': parent, 'sets': [scope]}
        path.write_text('---\n' + yaml.safe_dump(metadata) + '---\n' + body)
    for name in ('allowed', 'other'):
        package = skills / name
        package.mkdir()
        (package / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: {name} workflow\n---\nPRIVATE {name.upper()}')
    playbooks = tmp_path / 'playbooks'
    for name in ('allowed', 'other'):
        package = playbooks / name
        package.mkdir(parents=True)
        (package / 'PLAYBOOK.md').write_text(f'---\nname: {name}\ndescription: Specific {name} guide\n---\nPLAYBOOK {name.upper()}')
    monkeypatch.setattr('domain.assistants.runtime.get_library', lambda: build_library(references, skills, playbooks))

    async def forbidden(*args, **kwargs):
        """Fail if preparation or a resource read invokes another model."""
        pytest.fail('Resource preparation/read made a model call')

    monkeypatch.setattr('domain.assistants.assistant.Runner.run', forbidden)
    return references, skills


def registry(*, resources=True, root_name='root', root_skill_names=()):
    """Build an isolated graph with nested handoffs and distinct permissions."""
    root = AssistantSpec(name=root_name, description='Root', handoff_description='Root',
                         system_prompt='ROOT', task_prompt='TASK', path='root/system.md',
                         model='gpt-6-luna', repository_context=resources,
                         tool_group_keys=('context',) if resources else (),
                         handoff_names=('child',) if resources else (), skill_names=root_skill_names, playbook_names=())
    child = replace(root, name='child', system_prompt='CHILD', task_prompt='',
                    handoff_names=('leaf',), skill_names=('allowed',), playbook_names=('allowed',))
    leaf = replace(child, name='leaf', system_prompt='LEAF', handoff_names=(), skill_names=('other',), playbook_names=('other',))
    result = AssistantRegistry([root, child, leaf])
    from domain.assistants.utils import configure_tools
    configure_tools(result)
    return result


def instructions(agent, invocation):
    """Exercise the same dynamic instruction callback used by the SDK."""
    return agent.instructions(RunContextWrapper(invocation.context), agent)


def read(invocation, agent, resource_id):
    """Invoke the registered SDK tool with real typed context and agent identity."""
    payload = json.dumps({'resource_id': resource_id})
    ctx = ToolContext(context=invocation.context, agent=agent, tool_name='read_resource',
                      tool_call_id='read', tool_arguments=payload)
    return asyncio.run(get_tool('read_resource').on_invoke_tool(ctx, payload))


def test_preparation_exposes_metadata_without_bodies_or_selection():
    """Every handoff sees a permitted catalogue without any initial injection."""
    messages = [{'role': 'user', 'content': 'Tell me about Riven'},
                {'role': 'assistant', 'content': 'A bruiser'},
                {'role': 'user', 'content': 'What about her items?'}]
    timing = {}
    invocation = asyncio.run(Assistant('root', registry=registry(), set_number=18).prepare(
        messages, system='PREFIX', record=True, timing=timing))
    assert invocation.input[-1]['content'] == 'TASK\n\n## Input\n\nWhat about her items?'
    assert messages[-1]['content'] == 'What about her items?'
    root, child = invocation.agent, invocation.agent.handoffs[0]
    leaf = child.handoffs[0]
    for agent in (root, child, leaf):
        text = instructions(agent, invocation)
        assert '"id": "set18"' in text
        assert 'set18/units/roster' not in text
        assert 'PRIVATE' not in text and 'set17' not in text
    assert instructions(root, invocation).startswith('PREFIX\n\nROOT')
    assert not instructions(child, invocation).startswith('PREFIX')
    assert 'skill:allowed' in instructions(child, invocation)
    assert 'skill:other' not in instructions(child, invocation)
    assert 'skill:other' in instructions(leaf, invocation)
    assert not invocation.context.resources.reads
    assert 'resource_catalogue_ms' in timing
    assert 'context_selection_ms' not in timing and 'skill_selection_ms' not in timing
    assert invocation.instructions['root'] == instructions(root, invocation)


def test_reads_return_complete_contents_and_track_only_actual_reads():
    """A read produces tool output without adding resource bodies to instructions."""
    invocation = asyncio.run(Assistant('root', registry=registry(), set_number=18).prepare('Question'))
    child = invocation.agent.handoffs[0]
    before = instructions(child, invocation)
    reference = read(invocation, child, 'set18/units/roster')
    skill = read(invocation, child, 'skill:allowed')
    assert reference['complete'] and 'PRIVATE REFERENCE' in reference['content']
    assert skill['content'] == 'PRIVATE ALLOWED' and skill['kind'] == 'skill'
    assert instructions(child, invocation) == before
    read(invocation, child, 'skill:allowed')
    assert len(invocation.context.resources.reads) == 2
    assert set(invocation.context.resources.reads) == {'set18/units/roster', 'skill:allowed'}


@pytest.mark.parametrize('resource_id', ['skill:other', 'set17',
                                         '../private.ini', 'reference:/etc/passwd', 'missing'])
def test_read_denies_unknown_paths_sets_and_disallowed_skills(resource_id):
    """Exact catalogue membership enforces references and skills alike."""
    invocation = asyncio.run(Assistant('root', registry=registry(), set_number=18).prepare('Question'))
    result = read(invocation, invocation.agent.handoffs[0], resource_id)
    assert result['found'] is False and 'content' not in result
    assert not invocation.context.resources.reads


def test_chat_and_transcript_boundaries():
    """Chat cannot read skills and transcript-only invocations have no resources."""
    invocation = asyncio.run(Assistant('chat', registry=registry(root_name='chat', root_skill_names=('allowed',)),
                                       set_number=18).prepare('Question'))
    assert 'skill:allowed' not in instructions(invocation.agent, invocation)
    assert read(invocation, invocation.agent, 'skill:allowed')['found'] is False
    transcript = asyncio.run(Assistant('root', registry=registry(resources=False), set_number=18).prepare('Transcript'))
    assert instructions(transcript.agent, transcript) == 'ROOT'
    assert resource_entries(transcript.context.resources, 'root') == []


def test_context_disabled_and_empty_allowlists_deny_reads():
    """Explicit workflow permission can stand alone; empty access stays closed."""
    source = registry()
    source.install(AssistantRegistry([
        replace(source.get_spec('root'), repository_context=False, skill_names=('allowed',)),
        replace(source.get_spec('child'), repository_context=False, skill_names=(), playbook_names=()),
        source.get_spec('leaf'),
    ]))
    invocation = asyncio.run(Assistant('root', registry=source, set_number=18).prepare('Question'))
    assert read(invocation, invocation.agent, 'skill:allowed')['found']
    assert not read(invocation, invocation.agent, 'set18/units/roster')['found']
    assert resource_entries(invocation.context.resources, 'child') == []


def test_capture_and_run_state_are_isolated():
    """Registry reloads and subsequent reads cannot mutate existing policy or state."""
    source = registry()
    graph = capture(source)
    instance = Assistant.from_capture(graph, 'root', set_number=18,
                                      base_instructions_by_name={'child': 'CANDIDATE'})
    first = asyncio.run(instance.prepare('Question'))
    source.install(AssistantRegistry([replace(source.get_spec(name), system_prompt='CHANGED', skill_names=())
                                      for name in source.list_assistants()]))
    second = asyncio.run(instance.prepare('Another question'))
    child = first.agent.handoffs[0]
    assert instructions(child, first).startswith('CANDIDATE')
    assert read(first, child, 'skill:allowed')['found']
    assert not second.context.resources.reads
    assert first.agent is not second.agent
    assert first.context.evidence is not second.context.evidence
    assert first.context.activity is not second.context.activity
    assert child.model == graph['specs']['child']['resolved_model']


def test_explicit_empty_captured_prompt_keeps_only_metadata():
    """An empty prompt replacement must not restore the captured durable prompt."""
    invocation = asyncio.run(Assistant.from_capture(capture(registry()), 'root', set_number=18,
                        base_instructions_by_name={'child': ''}).prepare('Question'))
    text = instructions(invocation.agent.handoffs[0], invocation)
    assert text.startswith('## Available resources') and 'CHILD' not in text and 'PRIVATE' not in text


def test_tool_access_is_required_in_addition_to_resource_flags():
    """A saved graph with no read tool does not gain resource access implicitly."""
    source = registry()
    source.install(AssistantRegistry([replace(source.get_spec(name), tool_group_keys=())
                                      for name in source.list_assistants()]))
    invocation = asyncio.run(Assistant('root', registry=source, set_number=18).prepare('Question'))
    assert instructions(invocation.agent, invocation) == 'ROOT'
    assert not read(invocation, invocation.agent, 'set18/units/roster')['found']


def test_sync_and_async_entry_points_supply_same_contract(monkeypatch):
    """Both APIs retain typed state and original task wrapping."""
    instance = Assistant('root', registry=registry(resources=False), set_number=18)
    contexts = []

    async def run(agent, *, input, context, hooks, **kwargs):
        """Inspect execution without external generation."""
        contexts.append(context)
        assert input == 'TASK\n\n## Input\n\nQuestion' and callable(agent.instructions)
        return SimpleNamespace(final_output='Answer')

    monkeypatch.setattr('domain.assistants.assistant.Runner.run', run)
    assert instance.run_sync('Question').final_output == 'Answer'
    assert asyncio.run(instance.run('Question')).final_output == 'Answer'
    assert contexts[0] is not contexts[1]


def test_run_sync_inside_event_loop_fails_cleanly():
    """Async consumers get clear guidance without leaking a coroutine."""
    instance = Assistant('root', registry=registry(resources=False), set_number=18)

    async def run():
        """Exercise the synchronous boundary inside a running loop."""
        with pytest.raises(RuntimeError, match='await run'):
            instance.run_sync('Question')

    asyncio.run(run())


def test_failed_execution_finalizes_pending_activity(monkeypatch):
    """Failed model runs still finalize unfinished tool calls."""
    instance = Assistant('root', registry=registry(resources=False), set_number=18)
    contexts = []

    async def fail(agent, *, context, **kwargs):
        """Simulate failure after a tool starts."""
        contexts.append(context)
        context.activity.calls['pending'] = ToolActivity('pending', 'lookup')
        raise ValueError('Mock failure')

    monkeypatch.setattr('domain.assistants.assistant.Runner.run', fail)
    with pytest.raises(ValueError, match='Mock failure'):
        instance.run_sync('Question')
    assert contexts[0].activity.calls['pending'].status == 'failed'


def test_playbook_handoff_catalogues_and_reads_enforce_frozen_permissions():
    """Captured handoffs expose guide metadata and load bodies only on request."""
    source = registry()
    instance = Assistant.from_capture(capture(source), 'root', set_number=18)
    invocation = asyncio.run(instance.prepare('Specific question'))
    child = invocation.agent.handoffs[0]
    leaf = child.handoffs[0]
    assert 'playbook:allowed' in instructions(child, invocation)
    assert 'playbook:other' not in instructions(child, invocation)
    assert 'PLAYBOOK ALLOWED' not in instructions(child, invocation)
    assert 'playbook:other' in instructions(leaf, invocation)
    assert not read(invocation, invocation.agent, 'playbook:allowed')['found']
    assert not read(invocation, child, 'playbook:other')['found']
    source.install(AssistantRegistry([replace(source.get_spec(name), playbook_names=())
                                      for name in source.list_assistants()]))
    result = read(invocation, child, 'playbook:allowed')
    assert result['content'] == 'PLAYBOOK ALLOWED' and result['complete']
    assert invocation.context.resources.reads['playbook:allowed'].sha256 == result['sha256']


def test_explicit_playbook_access_without_references_or_skills():
    """Specific guides can be granted independently while chat remains restricted."""
    source = registry()
    source.install(AssistantRegistry([
        replace(source.get_spec(name), repository_context=False, skill_names=(), playbook_names=('allowed',))
        for name in source.list_assistants()
    ]))
    invocation = asyncio.run(Assistant('root', registry=source).prepare('Guide question'))
    assert read(invocation, invocation.agent, 'playbook:allowed')['found']
    assert not read(invocation, invocation.agent, 'skill:allowed')['found']
    assert not read(invocation, invocation.agent, 'set18')['found']
    chat_source = registry(root_name='chat')
    chat_source.install(AssistantRegistry([
        replace(chat_source.get_spec(name), playbook_names=('allowed',)) for name in chat_source.list_assistants()
    ]))
    chat = asyncio.run(Assistant('chat', registry=chat_source).prepare('Guide question'))
    assert 'playbook:allowed' not in instructions(chat.agent, chat)
    assert not read(chat, chat.agent, 'playbook:allowed')['found']


def test_historical_captures_do_not_gain_playbook_permissions():
    """Graphs captured before guides existed retain their original access boundary."""
    from domain.assistants.capture import digest
    graph = capture(registry())
    for definition in graph['specs'].values():
        definition.pop('playbook_names')
    graph['hash'] = digest({key: graph[key] for key in ('version', 'specs')})
    invocation = asyncio.run(Assistant.from_capture(graph, 'root').prepare('Question'))
    child = invocation.agent.handoffs[0]
    assert 'playbook:' not in instructions(child, invocation)
    assert not read(invocation, child, 'playbook:allowed')['found']
    assert read(invocation, child, 'skill:allowed')['found']
