"""Protect the Agent subclass boundary and runtime-owned SDK lifecycle."""

import asyncio
from contextlib import aclosing
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from agents import Agent, RunConfig, RunContextWrapper
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI

from domain.assistants import Assistant, AssistantRegistry, AssistantSpec, ChatAssistant
from domain.runtime.execution import create_context, run, run_streamed, stream_events
from domain.runtime.models import ToolActivity


def spec(name='fixture', **changes):
    """Create a source-only definition with no external-tool needs."""
    return AssistantSpec(name=name, description='Fixture', handoff_description='Fixture',
                         system_prompt='SYSTEM', task_prompt='', path='fixture/system.md', **changes)


def test_construction_and_cloning_do_not_gather_runtime_context(monkeypatch):
    """Creating agents requires no catalogue, evidence, or invocation state."""
    def forbidden(*args, **kwargs):
        """Reject accidental context gathering during construction."""
        pytest.fail('Agent construction gathered runtime context')

    monkeypatch.setattr('domain.runtime.execution.select_resource_catalogues', forbidden)
    monkeypatch.setattr('domain.assistants.utils.get_library', forbidden)
    root = spec('chat', handoff_names=('child',))
    assistant = Assistant.from_name('chat', registry=AssistantRegistry([root, spec('child')]))
    assert isinstance(assistant, Agent) and isinstance(assistant, ChatAssistant)
    assert type(assistant.handoffs[0]) is Assistant
    assert not any(hasattr(assistant, name) for name in ('agent', 'resources', 'run', 'run_sync', 'surface', 'set_number'))
    clone = assistant.clone(name='fallback', tools=[], handoffs=[])
    assert isinstance(clone, ChatAssistant) and clone.spec is assistant.spec
    assert clone.instructions.__self__ is clone
    assert assistant.instructions.__self__ is assistant


def test_clone_renders_its_own_spec_and_preserves_explicit_overrides():
    """SDK replacement retains metadata while renderer ownership follows the clone."""
    original = Assistant.from_spec(spec('chat'))
    context = create_context(original, system='PREFIX')
    clone = original.clone(name='fallback', spec=replace(original.spec, system_prompt='REVISED'))
    wrapper = RunContextWrapper(context)
    assert clone.instructions(wrapper, clone) == 'PREFIX\n\nREVISED'
    assert original.instructions(wrapper, original) == 'PREFIX\n\nSYSTEM'
    assert clone.clone(instructions='EXPLICIT').instructions == 'EXPLICIT'
    assert clone.clone(instructions=None).clone().instructions is None

    def custom(wrapper, agent):
        """Represent an explicit SDK instruction override."""
        return agent.name

    assert clone.clone(instructions=custom).instructions is custom
    assert clone.clone(instructions=custom).clone().instructions is custom
    assert clone.clone(model='mock-replacement').model == 'mock-replacement'
    with pytest.raises(TypeError, match='tools'):
        clone.clone(tools='invalid')


def test_from_spec_requires_the_declared_handoffs():
    """Explicit node construction cannot silently drop the declared handoffs."""
    with pytest.raises(ValueError, match='Handoffs must match'):
        Assistant.from_spec(spec(handoff_names=('child',)))


@pytest.mark.parametrize('streaming', [False, True])
def test_real_sdk_executes_assistant_subclass_without_external_requests(streaming):
    """Run the real SDK against an in-process OpenAI-compatible application."""
    from evals.langfuse.tests.mock_model import app

    async def execute():
        """Use ASGI transport so every model request stays in this process."""
        async with AsyncOpenAI(
            api_key='offline', base_url='http://offline/v1',
            http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
        ) as client:
            model = OpenAIResponsesModel(model='mock', openai_client=client)
            assistant = Assistant.from_spec(spec(), model=model)
            config = RunConfig(tracing_disabled=True)
            if streaming:
                async with run_streamed(assistant, 'Question', run_config=config) as result:
                    async with aclosing(stream_events(result)) as events:
                        observed = [event async for event in events]
                assert observed and result.is_complete
            else:
                result = await run(assistant, 'Question', run_config=config)
            assert result.final_output == 'Mock application reply.'
            assert result.last_agent is assistant
            assert result.context_wrapper.context.runtime.root_assistant == 'fixture'

    asyncio.run(execute())


@pytest.mark.parametrize('interruption', ['close', 'cancel', 'error', 'unconsumed'])
def test_stream_cleanup_cancels_before_closing_sdk_iterator(monkeypatch, interruption):
    """Early consumer exit must settle background work before iterator close."""
    state = []

    class Result:
        """Model SDK closure waiting for background execution."""

        is_complete = False

        def __init__(self):
            """Expose the SDK's public background task cancellation signal."""
            self.run_loop_task = SimpleNamespace(cancelled=lambda: self.is_complete)

        def cancel(self, mode):
            """Release background work before aclose can finish."""
            state.append('cancel')
            self.is_complete = True

        async def stream_events(self):
            """Check cancellation ordering during iterator closure."""
            if self.is_complete:
                state.append('drained')
                return
            try:
                yield SimpleNamespace(type='raw_response_event')
            finally:
                assert self.is_complete, 'SDK iterator closed before background cancellation'
                state.append('closed')

    result = Result()
    monkeypatch.setattr('domain.runtime.execution.Runner.run_streamed', lambda *a, **k: result)
    assistant = Assistant.from_spec(spec())
    context = create_context(assistant)
    context.activity.calls['pending'] = ToolActivity('pending', 'lookup')

    async def execute():
        """Exercise early exits through runtime's public streaming boundary."""
        async with run_streamed(assistant, 'Question', context=context):
            if interruption == 'unconsumed':
                return
            async with aclosing(stream_events(result)) as events:
                async for _ in events:
                    if interruption == 'cancel':
                        raise asyncio.CancelledError()
                    if interruption == 'error':
                        raise ValueError('consumer failed')
                    break

    expected = {'cancel': asyncio.CancelledError, 'error': ValueError}.get(interruption)
    if expected:
        with pytest.raises(expected):
            asyncio.run(execute())
    else:
        asyncio.run(execute())
    assert state[0] == 'cancel' and 'drained' in state
    assert result.is_complete
    expected_status = 'failed' if interruption == 'error' else 'cancelled'
    assert context.activity.calls['pending'].status == expected_status
