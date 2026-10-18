"""Verify progressive reads, dynamic policy, and captured-run isolation."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agents import Agent, RunContextWrapper
from agents.tool_context import ToolContext

from domain.assistants import Assistant, ChatAssistant, AssistantRegistry
from domain.assistants.models import AssistantSpec
from domain.resources.library import resource_entries
from domain.resources.library import build_library
from domain.runtime.models import ToolActivity
from domain.runtime import execution
from domain.tools import get_tool
from dev.assistants import assistant_from_capture, capture, digest, record_invocation


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
    ]:
        path = references / (resource_id.replace('/', '-') + '.md')
        metadata = {'id': resource_id, 'title': resource_id, 'description': 'Discover resources',
                    'kind': kind, 'parent': parent, 'patches': ['18.1']}
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
    monkeypatch.setattr('domain.runtime.execution.get_library', lambda: build_library(references, skills, playbooks))

    async def forbidden(*args, **kwargs):
        """Fail if preparation or a resource read invokes another model."""
        pytest.fail('Resource preparation/read made a model call')

    monkeypatch.setattr('domain.runtime.execution.Runner.run', forbidden)
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


def run_offline(assistant, input, *, system=None, timing=None):
    """Capture actual runner arguments through normal execution without a model."""
    def capture_run(agent, **kwargs):
        """Return the execution state for prompt and tool assertions."""
        kwargs['context'].timing = timing
        return SimpleNamespace(agent=agent, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr('domain.runtime.execution.Runner.run_sync', capture_run)
        return execution.run_sync(assistant, input, system=system)


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
    first = Assistant.from_name('root', registry=source)
    second = Assistant.from_name('root', registry=source)
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
        Assistant.from_name("root", registry=AssistantRegistry([spec]))


def test_execution_exposes_metadata_without_bodies_or_selection():
    """Every handoff sees a permitted catalogue without any initial injection."""
    messages = [{'role': 'user', 'content': 'Tell me about Riven'},
                {'role': 'assistant', 'content': 'A bruiser'},
                {'role': 'user', 'content': 'What about her items?'}]
    timing = {}
    invocation = run_offline(Assistant.from_name('root', registry=registry()), messages, system='PREFIX', timing=timing)
    recording = record_invocation(invocation.agent)
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
    assert not invocation.context.activity.resource_reads
    assert 'context_selection_ms' not in timing and 'skill_selection_ms' not in timing
    assert recording.instructions['root'] == instructions(root, invocation)


def test_reads_return_complete_contents_and_track_only_actual_reads():
    """A read produces tool output without adding resource bodies to instructions."""
    invocation = run_offline(Assistant.from_name('root', registry=registry()), 'Question')
    child = invocation.agent.handoffs[0]
    before = instructions(child, invocation)
    reference = read(invocation, child, 'set18/units/roster')
    skill = read(invocation, child, 'skill:allowed')
    assert reference['complete'] and 'PRIVATE REFERENCE' in reference['content']
    assert skill['content'] == 'PRIVATE ALLOWED' and skill['kind'] == 'skill'
    assert instructions(child, invocation) == before
    read(invocation, child, 'skill:allowed')
    assert len(invocation.context.activity.resource_reads) == 2
    assert set(invocation.context.activity.resource_reads) == {'set18/units/roster', 'skill:allowed'}


def test_shared_library_cache_does_not_grant_handoff_access():
    """A sibling's cached body remains inaccessible under the active assistant's spec."""
    invocation = run_offline(Assistant.from_name('root', registry=registry()), 'Question')
    child = invocation.agent.handoffs[0]
    leaf = child.handoffs[0]
    library = invocation.context.resources
    assert 'skill:other' in library.entries
    assert not child.spec.allows_resource('skill:other')
    assert leaf.spec.allows_resource('skill:other')
    assert read(invocation, leaf, 'skill:other')['found']
    assert 'skill:other' in library.body_cache
    assert not read(invocation, child, 'skill:other')['found']
    assert read(invocation, child.clone(name='renamed'), 'set18')['found']
    assert not read(invocation, Agent(name=child.name), 'set18')['found']


@pytest.mark.parametrize('resource_id', ['skill:other',
                                         '../private.ini', 'reference:/etc/passwd', 'missing'])
def test_read_denies_unknown_paths_and_disallowed_skills(resource_id):
    """Exact catalogue membership enforces references and skills alike."""
    invocation = run_offline(Assistant.from_name('root', registry=registry()), 'Question')
    result = read(invocation, invocation.agent.handoffs[0], resource_id)
    assert result['found'] is False and 'content' not in result
    assert not invocation.context.activity.resource_reads


def test_chat_and_transcript_boundaries():
    """Chat denies skills; transcript instructions omit the available repository library."""
    invocation = run_offline(Assistant.from_name('chat', registry=registry(root_name='chat')), 'Question')
    assert 'skill:allowed' not in instructions(invocation.agent, invocation)
    assert read(invocation, invocation.agent, 'skill:allowed')['found'] is False
    transcript = run_offline(Assistant.from_name('root', registry=registry(resources=False)), 'Transcript')
    assert instructions(transcript.agent, transcript) == 'ROOT'
    assert transcript.context.resources.entries
    assert not read(transcript, transcript.agent, 'set18')['found']
    assert not transcript.context.activity.resource_reads


def test_context_disabled_and_empty_allowlists_deny_reads():
    """Explicit workflow permission can stand alone; empty access stays closed."""
    source = registry()
    source = AssistantRegistry([
        replace(source.get_spec('root'), repository_context=False, skill_names=('allowed',)),
        replace(source.get_spec('child'), repository_context=False, skill_names=(), playbook_names=()),
        source.get_spec('leaf'),
    ])
    invocation = run_offline(Assistant.from_name('root', registry=source), 'Question')
    assert read(invocation, invocation.agent, 'skill:allowed')['found']
    assert not read(invocation, invocation.agent, 'set18/units/roster')['found']
    child = invocation.agent.handoffs[0]
    assert all(not child.spec.allows_resource(entry['id'])
               for entry in resource_entries(invocation.context.resources))


def test_clone_uses_its_own_permissions_with_the_same_context():
    """A clone cannot inherit access through its name or a previously cached body."""
    invocation = run_offline(Assistant.from_name('root', registry=registry()), 'Question')
    child = invocation.agent.handoffs[0]
    assert read(invocation, child, 'skill:allowed')['found']
    restricted = child.clone(spec=replace(
        child.spec, repository_context=False, skill_names=(), playbook_names=('other',),
    ))
    prompt = instructions(restricted, invocation)
    assert 'playbook:other' in prompt
    assert 'skill:allowed' not in prompt and '`set18`' not in prompt
    assert not read(invocation, restricted, 'skill:allowed')['found']
    assert not read(invocation, restricted, 'set18')['found']
    assert read(invocation, restricted, 'playbook:other')['found']
    assert read(invocation, child, 'skill:allowed')['found']
    assert not read(invocation, child, 'playbook:other')['found']


def test_resource_free_root_delegates_to_handoff_with_its_own_access():
    """A parent's empty policy cannot suppress or acquire its child's permissions."""
    source = registry()
    root = replace(source.get_spec('root'), repository_context=False,
                   tool_group_keys=(), skill_names=(), playbook_names=())
    graph = AssistantRegistry([root, source.get_spec('child'), source.get_spec('leaf')])
    invocation = run_offline(Assistant.from_name('root', registry=graph), 'Question')
    assert invocation.context.resources is not None
    assert not invocation.context.resources.body_cache
    assert instructions(invocation.agent, invocation) == 'ROOT'
    assert not read(invocation, invocation.agent, 'set18')['found']
    assert read(invocation, invocation.agent.handoffs[0], 'set18')['found']


def test_capture_and_run_state_are_isolated():
    """Registry reloads and subsequent reads cannot mutate existing policy or state."""
    source = registry()
    graph = capture(source)
    instance = assistant_from_capture(
        graph, 'root',
        prompt_candidates={'child': 'CANDIDATE'},
    )
    first = run_offline(instance, 'Question')
    source = AssistantRegistry([
        replace(source.get_spec(name), system_prompt='CHANGED', skill_names=())
        for name in list(source.assistant_names)
    ])
    second_instance = assistant_from_capture(
        graph, 'root',  prompt_candidates={'child': 'CANDIDATE'},
    )
    second = run_offline(second_instance, 'Another question')
    child = first.agent.handoffs[0]
    assert instructions(child, first).startswith('CANDIDATE')
    assert read(first, child, 'skill:allowed')['found']
    assert not second.context.activity.resource_reads
    assert first.agent is instance
    assert second.agent is second_instance
    assert first.agent is not second.agent
    assert first.context.evidence is not second.context.evidence
    assert first.context.activity is not second.context.activity
    assert child.model == graph['specs']['child']['resolved_model']


def test_graph_shares_catalogue_and_repeated_runs_isolate_state(monkeypatch):
    """Load graph resources once while giving each execution independent state."""
    from domain.runtime import execution as resource_module

    library = resource_module.get_library()
    loads = []

    def load():
        """Count catalogue requests without replacing real permission behavior."""
        loads.append(True)
        return library

    monkeypatch.setattr(resource_module, 'get_library', load)
    instance = Assistant.from_name('root', registry=registry())
    first = run_offline(instance, 'First')
    child = instance.handoffs[0]
    assert not hasattr(instance, "resources")
    assert read(first, child, 'skill:allowed')['found']
    first.context.activity.calls['pending'] = ToolActivity('pending', 'lookup')
    second = run_offline(instance, 'Second')
    assert loads == [True, True]
    assert first.context.resources is second.context.resources is library
    assert first.context.activity.resource_reads is not second.context.activity.resource_reads
    assert library.body_cache['skill:allowed'] is first.context.activity.resource_reads['skill:allowed']
    assert not second.context.activity.resource_reads
    assert not second.context.activity.calls
    assert first.context.evidence is not second.context.evidence
    assert first.context.runtime.request_id != second.context.runtime.request_id
    assert read(second, child, 'skill:allowed')['found']
    assert second.context.activity.resource_reads['skill:allowed'] is library.body_cache['skill:allowed']


def test_explicit_empty_captured_prompt_keeps_only_metadata():
    """An empty prompt replacement must not restore the captured durable prompt."""
    invocation = run_offline(assistant_from_capture(
        capture(registry()), 'root',
        prompt_candidates={'child': ''},
    ), 'Question')
    text = instructions(invocation.agent.handoffs[0], invocation)
    assert text.startswith('## Available resources') and 'CHILD' not in text and 'PRIVATE' not in text


def test_tool_access_is_required_in_addition_to_resource_flags():
    """A saved graph with no read tool does not gain resource access implicitly."""
    source = registry()
    source = AssistantRegistry([
        replace(source.get_spec(name), tool_group_keys=())
        for name in list(source.assistant_names)
    ])
    invocation = run_offline(Assistant.from_name('root', registry=source), 'Question')
    assert instructions(invocation.agent, invocation) == 'ROOT'
    assert not read(invocation, invocation.agent, 'set18/units/roster')['found']


def test_sync_and_async_entry_points_supply_same_contract(monkeypatch):
    """Each API calls the matching SDK entry point with the same prepared contract."""
    from agents import RunConfig

    instance = Assistant.from_name('root', registry=registry(resources=False))
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

    monkeypatch.setattr('domain.runtime.execution.Runner.run', run)
    monkeypatch.setattr('domain.runtime.execution.Runner.run_sync', run_sync)
    options = dict(max_turns=4, run_config=config, system='PREFIX')
    assert execution.run_sync(instance, 'Question', **options).final_output == 'Answer'
    assert asyncio.run(execution.run(instance, 'Question', **options)).final_output == 'Answer'
    assert entrypoints == ['sync', 'async']
    assert contexts[0] is not contexts[1]


def test_run_sync_inside_event_loop_fails_cleanly():
    """Async consumers get clear guidance without leaking a coroutine."""
    instance = Assistant.from_name('root', registry=registry(resources=False))

    async def run():
        """Exercise the synchronous boundary inside a running loop."""
        with pytest.raises(RuntimeError, match='await run'):
            execution.run_sync(instance, 'Question')

    asyncio.run(run())


@pytest.mark.parametrize('sync', [True, False])
def test_failed_execution_finalizes_pending_activity(monkeypatch, sync):
    """Failed runs finalize unfinished tool calls through either SDK entry point."""
    instance = Assistant.from_name('root', registry=registry(resources=False))
    contexts = []

    def fail(agent, *, context, **kwargs):
        """Simulate failure after a tool starts."""
        contexts.append(context)
        context.activity.calls['pending'] = ToolActivity('pending', 'lookup')
        raise ValueError('Mock failure')

    async def fail_async(*args, **kwargs):
        """Use the same failure through the asynchronous SDK boundary."""
        return fail(*args, **kwargs)

    monkeypatch.setattr('domain.runtime.execution.Runner.run', fail_async)
    monkeypatch.setattr('domain.runtime.execution.Runner.run_sync', fail)
    with pytest.raises(ValueError, match='Mock failure'):
        if sync:
            execution.run_sync(instance, 'Question')
        else:
            asyncio.run(execution.run(instance, 'Question'))
    assert contexts[0].activity.calls['pending'].status == 'failed'


@pytest.mark.parametrize('error', [KeyboardInterrupt, asyncio.CancelledError])
def test_sync_interruption_finalizes_pending_activity(monkeypatch, error):
    """Interrupted synchronous runs mark unfinished calls as cancelled."""
    instance = Assistant.from_name('root', registry=registry(resources=False))
    contexts = []

    def interrupt(agent, *, context, **kwargs):
        """Interrupt after a tool starts without invoking a model."""
        contexts.append(context)
        context.activity.calls['pending'] = ToolActivity('pending', 'lookup')
        raise error()

    monkeypatch.setattr('domain.runtime.execution.Runner.run_sync', interrupt)
    with pytest.raises(error):
        execution.run_sync(instance, 'Question')
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
        instance = Assistant.from_name('root', registry=registry())
        assert execution.run_sync(instance, 'First').final_output == 'Answer'
        assert execution.run_sync(instance, 'Second').final_output == 'Answer'
        assert loops == [loop, loop]
        assert asyncio.get_event_loop() is loop and not loop.is_closed()
    finally:
        loop.close()
        asyncio.set_event_loop(previous)


def test_playbook_handoff_catalogues_and_reads_enforce_frozen_permissions():
    """Captured handoffs expose guide metadata and load bodies only on request."""
    source = registry()
    instance = assistant_from_capture(capture(source), 'root')
    invocation = run_offline(instance, 'Specific question')
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
    assert invocation.context.activity.resource_reads['playbook:allowed'].sha256 == result['sha256']


def test_explicit_playbook_access_without_references_or_skills():
    """Specific guides can be granted independently, including by a custom chat spec."""
    source = registry()
    source = AssistantRegistry([
        replace(source.get_spec(name), repository_context=False, skill_names=(), playbook_names=('allowed',))
        for name in list(source.assistant_names)
    ])
    invocation = run_offline(Assistant.from_name('root', registry=source), 'Guide question')
    assert read(invocation, invocation.agent, 'playbook:allowed')['found']
    assert not read(invocation, invocation.agent, 'skill:allowed')['found']
    assert not read(invocation, invocation.agent, 'set18')['found']
    chat_source = registry(root_name='chat')
    chat_source = AssistantRegistry([
        replace(chat_source.get_spec(name), playbook_names=('allowed',)) for name in list(chat_source.assistant_names)
    ])
    chat = run_offline(Assistant.from_name('chat', registry=chat_source), 'Guide question')
    assert 'playbook:allowed' in instructions(chat.agent, chat)
    assert read(chat, chat.agent, 'playbook:allowed')['found']


@pytest.mark.parametrize('version,exposed', [(1, False), (2, True)])
def test_captured_chat_exposure_preserves_its_policy_version(version, exposed):
    """Old graphs retain the implicit restriction; new graphs honor explicit specs."""
    source = registry(root_name='chat', root_skill_names=('allowed',))
    graph = capture(source)
    graph['version'] = version
    graph['hash'] = digest({key: graph[key] for key in ('version', 'specs')})
    invocation = run_offline(assistant_from_capture(graph, 'chat'), 'Question')
    assert read(invocation, invocation.agent, 'skill:allowed')['found'] is exposed
    assert graph['specs']['chat']['skill_names'] == ['allowed']


def test_historical_captures_do_not_gain_playbook_permissions():
    """Graphs captured before guides existed retain their original access boundary."""
    graph = capture(registry())
    for definition in graph['specs'].values():
        definition.pop('playbook_names')
    graph['hash'] = digest({key: graph[key] for key in ('version', 'specs')})
    invocation = run_offline(assistant_from_capture(graph, 'root'), 'Question')
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
        assistant_from_capture(graph, 'root')


def test_chat_class_owns_readable_prompt_and_fallback_identity():
    """Chat rendering remains bound to its instance when the SDK renames a fallback."""
    instance = Assistant.from_name('chat', registry=registry(root_name='chat'))
    assert isinstance(instance, ChatAssistant)
    invocation = run_offline(instance, 'Question', system='PREFIX', timing={})
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

    class CustomAssistant(Assistant):
        """Demonstrate a complete high-level prompt override."""

        def render_instructions(self, wrapper, agent):
            """Render a custom prompt from the node's own spec and prepared resources."""
            context = wrapper.context
            ids = [entry['id'] for entry in resource_entries(context.resources)
                   if self.spec.allows_resource(entry['id'])]
            return self.spec.system_prompt + ' CUSTOM: ' + ', '.join(ids)

    monkeypatch.setitem(ASSISTANT_CLASSES, 'child', CustomAssistant)
    instance = Assistant.from_name('root', registry=registry(), output_type=str)
    assert type(instance) is Assistant
    invocation = run_offline(instance, 'Question', system='PREFIX')
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
        replace(source.get_spec('child'), name='chat', skill_names=(), playbook_names=()),
        source.get_spec('leaf'),
    ])
    instance = assistant_from_capture(capture(source), 'root',
                                      prompt_candidates={'chat': 'CAPTURED CHAT'})
    invocation = run_offline(instance, 'Question', system='PREFIX')
    chat = invocation.agent.handoffs[0]
    assert isinstance(chat.instructions.__self__, ChatAssistant)
    text = instructions(chat, invocation)
    assert text.startswith('CAPTURED CHAT')
    assert '## Available TFT references' in text and 'PREFIX' not in text
    assert 'skill:' not in text and 'playbook:' not in text
