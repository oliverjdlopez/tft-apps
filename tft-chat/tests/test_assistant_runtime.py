"""Verify progressive reads, dynamic policy, and captured-run isolation."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agents import Agent, RunContextWrapper
from agents.tool_context import ToolContext

from domain.assistants import Assistant, BaseAssistant, ChatAssistant, AssistantRegistry
from domain.assistants.models import AssistantSpec
from domain.assistants.resources import resource_entries
from domain.resources.library import build_library
from domain.runtime.models import ToolActivity
from domain.tools import get_tool
from devtools.assistants import assistant_from_capture, capture, digest, record_invocation


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
                    'kind': kind, 'parent': parent, 'sets': [scope], 'patches': ['18.1']}
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
    monkeypatch.setattr('domain.assistants.resources.get_library', lambda: build_library(references, skills, playbooks))

    async def forbidden(*args, **kwargs):
        """Fail if preparation or a resource read invokes another model."""
        pytest.fail('Resource preparation/read made a model call')

    monkeypatch.setattr('domain.assistants.base.Runner.run', forbidden)
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
    return AssistantRegistry([root, child, leaf])


def instructions(agent, invocation):
    """Render through the SDK, including its callback signature handling."""
    return asyncio.run(agent.get_system_prompt(RunContextWrapper(invocation.context)))


def read(invocation, agent, resource_id):
    """Invoke the registered SDK tool with real typed context and agent identity."""
    payload = json.dumps({'resource_id': resource_id})
    ctx = ToolContext(context=invocation.context, agent=agent, tool_name='read_resource',
                      tool_call_id='read', tool_arguments=payload)
    return asyncio.run(get_tool('read_resource').on_invoke_tool(ctx, payload))



def test_registry_metadata_is_precomputed_and_execution_lists_are_independent(monkeypatch):
    """Execution reuses resolved tools without sharing mutable agent tool lists."""
    source = registry()

    def unexpected_resolution(*args, **kwargs):
        """Reject tool resolution after registry construction."""
        pytest.fail("Execution resolved tools again")

    monkeypatch.setattr('domain.assistants.registry.resolve_tools', unexpected_resolution)
    first = Assistant('root', registry=source, set_number=18).agent
    second = Assistant('root', registry=source, set_number=18).agent
    assert source.reachable_assistant_names['root'] == ('root', 'child', 'leaf')
    assert source.reachable_tool_names['root'] == ('read_resource',)
    assert tuple(tool.name for tool in first.tools) == source.tool_names['root']
    first.tools.clear()
    assert second.tools
    assert source.tools['root']
    with pytest.raises(TypeError):
        source.tool_names['root'] = ()

@pytest.mark.parametrize("changes, error, message", [
    ({"handoff_names": ("root",)}, ValueError, "handoff cycle"),
    ({"handoff_names": ("missing",)}, KeyError, "Unknown handoff assistant"),
    ({"tool_names": ("missing",)}, KeyError, "Unknown TFT tool"),
])
def test_constructor_rejects_invalid_execution_graph(changes, error, message):
    """Bad handoffs and tools fail at construction, before preparing a request."""
    spec = replace(registry(resources=False).get_spec("root"), **changes)
    with pytest.raises(error, match=message):
        Assistant("root", registry=AssistantRegistry([spec]), set_number=18)


def test_preparation_exposes_metadata_without_bodies_or_selection():
    """Every handoff sees a permitted catalogue without any initial injection."""
    messages = [{'role': 'user', 'content': 'Tell me about Riven'},
                {'role': 'assistant', 'content': 'A bruiser'},
                {'role': 'user', 'content': 'What about her items?'}]
    timing = {}
    invocation = asyncio.run(Assistant('root', registry=registry(), set_number=18).prepare(
        messages, system='PREFIX', timing=timing))
    recording = record_invocation(invocation)
    assert invocation.input[-1]['content'] == 'TASK\n\n## Input\n\nWhat about her items?'
    assert messages[-1]['content'] == 'What about her items?'
    root, child = invocation.agent, invocation.agent.handoffs[0]
    leaf = child.handoffs[0]
    for agent in (root, child, leaf):
        text = instructions(agent, invocation)
        assert "- `set18`" in text
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
    assert recording.instructions['root'] == instructions(root, invocation)


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
    source = AssistantRegistry([
        replace(source.get_spec('root'), repository_context=False, skill_names=('allowed',)),
        replace(source.get_spec('child'), repository_context=False, skill_names=(), playbook_names=()),
        source.get_spec('leaf'),
    ])
    invocation = asyncio.run(Assistant('root', registry=source, set_number=18).prepare('Question'))
    assert read(invocation, invocation.agent, 'skill:allowed')['found']
    assert not read(invocation, invocation.agent, 'set18/units/roster')['found']
    assert resource_entries(invocation.context.resources, 'child') == []


def test_capture_and_run_state_are_isolated():
    """Registry reloads and subsequent reads cannot mutate existing policy or state."""
    source = registry()
    graph = capture(source)
    instance = assistant_from_capture(
        graph, 'root', set_number=18,
        prompt_candidates={'child': 'CANDIDATE'},
    )
    first = asyncio.run(instance.prepare('Question'))
    source = AssistantRegistry([
        replace(source.get_spec(name), system_prompt='CHANGED', skill_names=())
        for name in list(source.assistant_names)
    ])
    second_instance = assistant_from_capture(
        graph, 'root', set_number=18, prompt_candidates={'child': 'CANDIDATE'},
    )
    second = asyncio.run(second_instance.prepare('Another question'))
    child = first.agent.handoffs[0]
    assert instructions(child, first).startswith('CANDIDATE')
    assert read(first, child, 'skill:allowed')['found']
    assert not second.context.resources.reads
    assert first.agent is instance.agent
    assert second.agent is second_instance.agent
    assert first.agent is not second.agent
    assert first.context.evidence is not second.context.evidence
    assert first.context.activity is not second.context.activity
    assert child.model == graph['specs']['child']['resolved_model']


def test_explicit_empty_captured_prompt_keeps_only_metadata():
    """An empty prompt replacement must not restore the captured durable prompt."""
    invocation = asyncio.run(assistant_from_capture(
        capture(registry()), 'root', set_number=18,
        prompt_candidates={'child': ''},
    ).prepare('Question'))
    text = instructions(invocation.agent.handoffs[0], invocation)
    assert text.startswith('## Available resources') and 'CHILD' not in text and 'PRIVATE' not in text


def test_tool_access_is_required_in_addition_to_resource_flags():
    """A saved graph with no read tool does not gain resource access implicitly."""
    source = registry()
    source = AssistantRegistry([
        replace(source.get_spec(name), tool_group_keys=())
        for name in list(source.assistant_names)
    ])
    invocation = asyncio.run(Assistant('root', registry=source, set_number=18).prepare('Question'))
    assert instructions(invocation.agent, invocation) == 'ROOT'
    assert not read(invocation, invocation.agent, 'set18/units/roster')['found']


def test_sync_and_async_entry_points_supply_same_contract(monkeypatch):
    """Each API calls the matching SDK entry point with the same prepared contract."""
    from agents import RunConfig

    instance = Assistant('root', registry=registry(resources=False), set_number=18)
    contexts, entrypoints = [], []
    config = RunConfig(workflow_name='fixture')

    def inspect(agent, *, input, context, hooks, max_turns, run_config):
        """Inspect execution without external generation."""
        contexts.append(context)
        assert input == 'TASK\n\n## Input\n\nQuestion' and callable(agent.instructions)
        assert max_turns == 4 and run_config is config
        assert context.runtime.system == 'PREFIX'
        return SimpleNamespace(final_output='Answer')

    async def run(*args, **kwargs):
        """Observe asynchronous SDK dispatch."""
        entrypoints.append('async')
        return inspect(*args, **kwargs)

    def run_sync(*args, **kwargs):
        """Observe synchronous SDK dispatch."""
        entrypoints.append('sync')
        return inspect(*args, **kwargs)

    monkeypatch.setattr('domain.assistants.base.Runner.run', run)
    monkeypatch.setattr('domain.assistants.base.Runner.run_sync', run_sync)
    options = dict(max_turns=4, run_config=config, system='PREFIX')
    assert instance.run_sync('Question', **options).final_output == 'Answer'
    assert asyncio.run(instance.run('Question', **options)).final_output == 'Answer'
    assert entrypoints == ['sync', 'async']
    assert contexts[0] is not contexts[1]


def test_run_sync_inside_event_loop_fails_cleanly():
    """Async consumers get clear guidance without leaking a coroutine."""
    instance = Assistant('root', registry=registry(resources=False), set_number=18)

    async def run():
        """Exercise the synchronous boundary inside a running loop."""
        with pytest.raises(RuntimeError, match='await run'):
            instance.run_sync('Question')

    asyncio.run(run())


@pytest.mark.parametrize('sync', [True, False])
def test_failed_execution_finalizes_pending_activity(monkeypatch, sync):
    """Failed runs finalize unfinished tool calls through either SDK entry point."""
    instance = Assistant('root', registry=registry(resources=False), set_number=18)
    contexts = []

    def fail(agent, *, context, **kwargs):
        """Simulate failure after a tool starts."""
        contexts.append(context)
        context.activity.calls['pending'] = ToolActivity('pending', 'lookup')
        raise ValueError('Mock failure')

    async def fail_async(*args, **kwargs):
        """Use the same failure through the asynchronous SDK boundary."""
        return fail(*args, **kwargs)

    monkeypatch.setattr('domain.assistants.base.Runner.run', fail_async)
    monkeypatch.setattr('domain.assistants.base.Runner.run_sync', fail)
    with pytest.raises(ValueError, match='Mock failure'):
        if sync:
            instance.run_sync('Question')
        else:
            asyncio.run(instance.run('Question'))
    assert contexts[0].activity.calls['pending'].status == 'failed'


@pytest.mark.parametrize('error', [KeyboardInterrupt, asyncio.CancelledError])
def test_sync_interruption_finalizes_pending_activity(monkeypatch, error):
    """Interrupted synchronous runs mark unfinished calls as cancelled."""
    instance = Assistant('root', registry=registry(resources=False), set_number=18)
    contexts = []

    def interrupt(agent, *, context, **kwargs):
        """Interrupt after a tool starts without invoking a model."""
        contexts.append(context)
        context.activity.calls['pending'] = ToolActivity('pending', 'lookup')
        raise error()

    monkeypatch.setattr('domain.assistants.base.Runner.run_sync', interrupt)
    with pytest.raises(error):
        instance.run_sync('Question')
    assert contexts[0].activity.calls['pending'].status == 'cancelled'


def test_sync_execution_preserves_sdk_default_event_loop(monkeypatch):
    """Real SDK sync dispatch reuses an existing loop across multiple calls."""
    from agents.run import DEFAULT_AGENT_RUNNER

    loops = []

    async def execute(agent, input, **kwargs):
        """Observe the loop selected by the SDK without executing a model."""
        loops.append(asyncio.get_running_loop())
        return SimpleNamespace(final_output='Answer')

    monkeypatch.setattr(DEFAULT_AGENT_RUNNER, 'run', execute)
    try:
        previous = asyncio.get_event_loop()
    except RuntimeError:
        previous = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        instance = Assistant('root', registry=registry(), set_number=18)
        assert instance.run_sync('First').final_output == 'Answer'
        assert instance.run_sync('Second').final_output == 'Answer'
        assert loops == [loop, loop]
        assert asyncio.get_event_loop() is loop and not loop.is_closed()
    finally:
        loop.close()
        asyncio.set_event_loop(previous)


def test_playbook_handoff_catalogues_and_reads_enforce_frozen_permissions():
    """Captured handoffs expose guide metadata and load bodies only on request."""
    source = registry()
    instance = assistant_from_capture(capture(source), 'root', set_number=18)
    invocation = asyncio.run(instance.prepare('Specific question'))
    child = invocation.agent.handoffs[0]
    leaf = child.handoffs[0]
    assert 'playbook:allowed' in instructions(child, invocation)
    assert 'playbook:other' not in instructions(child, invocation)
    assert 'PLAYBOOK ALLOWED' not in instructions(child, invocation)
    assert 'playbook:other' in instructions(leaf, invocation)
    assert not read(invocation, invocation.agent, 'playbook:allowed')['found']
    assert not read(invocation, child, 'playbook:other')['found']
    source = AssistantRegistry([
        replace(source.get_spec(name), playbook_names=())
        for name in list(source.assistant_names)
    ])
    result = read(invocation, child, 'playbook:allowed')
    assert result['content'] == 'PLAYBOOK ALLOWED' and result['complete']
    assert invocation.context.resources.reads['playbook:allowed'].sha256 == result['sha256']


def test_explicit_playbook_access_without_references_or_skills():
    """Specific guides can be granted independently while chat remains restricted."""
    source = registry()
    source = AssistantRegistry([
        replace(source.get_spec(name), repository_context=False, skill_names=(), playbook_names=('allowed',))
        for name in list(source.assistant_names)
    ])
    invocation = asyncio.run(Assistant('root', registry=source).prepare('Guide question'))
    assert read(invocation, invocation.agent, 'playbook:allowed')['found']
    assert not read(invocation, invocation.agent, 'skill:allowed')['found']
    assert not read(invocation, invocation.agent, 'set18')['found']
    chat_source = registry(root_name='chat')
    chat_source = AssistantRegistry([
        replace(chat_source.get_spec(name), playbook_names=('allowed',)) for name in list(chat_source.assistant_names)
    ])
    chat = asyncio.run(Assistant('chat', registry=chat_source).prepare('Guide question'))
    assert 'playbook:allowed' not in instructions(chat.agent, chat)
    assert not read(chat, chat.agent, 'playbook:allowed')['found']


def test_historical_captures_do_not_gain_playbook_permissions():
    """Graphs captured before guides existed retain their original access boundary."""
    graph = capture(registry())
    for definition in graph['specs'].values():
        definition.pop('playbook_names')
    graph['hash'] = digest({key: graph[key] for key in ('version', 'specs')})
    invocation = asyncio.run(assistant_from_capture(graph, 'root').prepare('Question'))
    child = invocation.agent.handoffs[0]
    assert 'playbook:' not in instructions(child, invocation)
    assert not read(invocation, child, 'playbook:allowed')['found']
    assert read(invocation, child, 'skill:allowed')['found']


@pytest.mark.parametrize("field, value", [
    ("skill_names", "allowed"),
    ("repository_context", "false"),
])
def test_captured_values_pass_through_model_invariants(field, value):
    """Capture restoration cannot coerce malformed permissions into valid ones."""
    graph = capture(registry())
    graph['specs']['root'][field] = value
    graph['hash'] = digest({key: graph[key] for key in ('version', 'specs')})
    with pytest.raises(ValueError, match=field):
        assistant_from_capture(graph, 'root', set_number=18)


def test_chat_class_owns_readable_prompt_and_fallback_identity():
    """Chat rendering remains bound to its instance when the SDK renames a fallback."""
    instance = Assistant('chat', registry=registry(root_name='chat'), set_number=18)
    assert isinstance(instance, ChatAssistant)
    invocation = asyncio.run(instance.prepare('Question', system='PREFIX', timing={}))
    prompt = instructions(invocation.agent, invocation)
    assert prompt.startswith('PREFIX\n\nROOT')
    assert '## Available TFT references' in prompt
    assert '- `set18` — set18 (index; patches: 18.1): Discover resources' in prompt
    assert '"id":' not in prompt and 'progressive disclosure' not in prompt
    assert 'Wisp stage views' not in prompt and 'PRIVATE' not in prompt
    assert 'skill:' not in prompt and 'playbook:' not in prompt
    child_prompt = instructions(invocation.agent.handoffs[0], invocation)
    assert '## Available resources' in child_prompt
    assert 'PREFIX' not in child_prompt
    assert 'instruction_assembly_ms' in invocation.context.timing
    fallback = Agent(name='chat_tft_final_response', instructions=invocation.agent.instructions)
    assert instructions(fallback, invocation) == prompt


def test_handoff_uses_registered_subclass_and_root_only_output_type(monkeypatch):
    """The same class dispatch applies to every graph node without sharing behavior."""
    from domain.assistants.assistant import ASSISTANT_CLASSES

    class CustomAssistant(BaseAssistant):
        """Demonstrate a complete high-level prompt override."""

        def render_prompt(self, context):
            """Render a custom prompt from the node's own spec and prepared resources."""
            ids = [entry['id'] for entry in resource_entries(context.resources, self.name)]
            return self.spec.system_prompt + ' CUSTOM: ' + ', '.join(ids)

    monkeypatch.setitem(ASSISTANT_CLASSES, 'child', CustomAssistant)
    instance = Assistant('root', registry=registry(), output_type=str, set_number=18)
    assert type(instance) is BaseAssistant
    invocation = asyncio.run(instance.prepare('Question', system='PREFIX'))
    child = invocation.agent.handoffs[0]
    assert isinstance(child.instructions.__self__, CustomAssistant)
    assert 'CHILD CUSTOM: set18' in instructions(child, invocation)
    assert 'PREFIX' not in instructions(child, invocation)
    assert 'CUSTOM' not in instructions(invocation.agent, invocation)
    assert 'CUSTOM' not in instructions(child.handoffs[0], invocation)
    assert invocation.agent.output_type is str
    assert child.output_type is None and child.handoffs[0].output_type is None


def test_chat_subclass_dispatches_inside_captured_handoffs():
    """Captured prompt replacement and subclass rendering compose for a non-root chat."""
    source = registry()
    source = AssistantRegistry([
        replace(source.get_spec('root'), handoff_names=('chat',)),
        replace(source.get_spec('child'), name='chat'),
        source.get_spec('leaf'),
    ])
    instance = assistant_from_capture(capture(source), 'root', set_number=18,
                                      prompt_candidates={'chat': 'CAPTURED CHAT'})
    invocation = asyncio.run(instance.prepare('Question', system='PREFIX'))
    chat = invocation.agent.handoffs[0]
    assert isinstance(chat.instructions.__self__, ChatAssistant)
    text = instructions(chat, invocation)
    assert text.startswith('CAPTURED CHAT')
    assert '## Available TFT references' in text and 'PREFIX' not in text
    assert 'skill:' not in text and 'playbook:' not in text
