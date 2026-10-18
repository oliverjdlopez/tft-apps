"""Prepare application context and execute configured SDK assistants."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from agents import RunConfig, Runner, RunResult, RunResultStreaming

from domain.runtime.activity import ActivityRunHooks, finalize_activity
from domain.runtime.models import AssistantRunContext, RuntimeSettings
from domain.runtime.utils import cancel_streamed_result, invocation_input
from domain.tools.evidence.models import EvidenceStore

if TYPE_CHECKING:
    from domain.assistants import Assistant


Input = str | Sequence[Mapping[str, str]]


def create_context(
    assistant: Assistant, *,
    surface: str = 'assistant', request_id: str | None = None,
    system: str | None = None, timing: dict[str, Any] | None = None,
) -> AssistantRunContext:
    """Gather resources and create fresh mutable state for one invocation.

    Args:
        assistant: Configured root whose graph defines resource permissions.
        surface: Execution provenance such as chat, task, or eval.
        request_id: Caller identity; omission generates a unique identifier.
        system: Optional caller prefix rendered only by the root assistant.
        timing: Optional caller-owned timing record.

    Returns:
        Context shared by all handoffs, with independent evidence and reads.
    """
    return AssistantRunContext(
        runtime=RuntimeSettings(
            request_id=request_id or uuid4().hex,
            root_assistant=assistant.spec.name, surface=surface, system=system,
        ),
        resources=assistant.load_resource_library(),
        evidence=EvidenceStore(), timing=timing,
    )


async def run(
    assistant: Assistant, input: Input, *, context: AssistantRunContext | None = None,
    max_turns: int = 10, run_config: RunConfig | None = None, **context_options: Any,
) -> RunResult:
    """Execute asynchronously with fresh context unless the caller supplies it.

    Args:
        assistant: Configured SDK assistant to execute.
        input: User text or conversation history; runtime applies the task wrapper.
        context: Optional context prepared for recording or shared execution.
        max_turns: SDK turn limit.
        run_config: SDK execution and tracing options.
        **context_options: Arguments to create_context; only used without context.

    Returns:
        The unwrapped SDK result, including its invocation context.
    """
    if context is not None and context_options:
        raise ValueError('Context options cannot accompany an existing context')
    if context is None:
        context = await asyncio.to_thread(create_context, assistant, **context_options)
    cancelled = False
    try:
        return await Runner.run(
            assistant, input=invocation_input(input, assistant.spec.task_prompt),
            context=context, hooks=ActivityRunHooks(), max_turns=max_turns, run_config=run_config,
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        cancelled = True
        raise
    finally:
        finalize_activity(context, cancelled=cancelled)


def run_sync(
    assistant: Assistant, input: Input, *, context: AssistantRunContext | None = None,
    max_turns: int = 10, run_config: RunConfig | None = None, **context_options: Any,
) -> RunResult:
    """Execute through the SDK's synchronous runner and finalize activity.

    Args:
        assistant: Configured SDK assistant to execute.
        input: User text or conversation history to wrap for the root task.
        context: Optional prebuilt invocation context.
        max_turns: SDK turn limit.
        run_config: SDK execution and tracing options.
        **context_options: Arguments to create_context; only used without context.

    Returns:
        The unwrapped SDK result.

    Raises:
        RuntimeError: If called within an active event loop; await run instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError('run_sync cannot run inside an event loop; await run()')
    if context is not None and context_options:
        raise ValueError('Context options cannot accompany an existing context')
    if context is None:
        context = create_context(assistant, **context_options)
    cancelled = False
    try:
        return Runner.run_sync(
            assistant, input=invocation_input(input, assistant.spec.task_prompt),
            context=context, hooks=ActivityRunHooks(), max_turns=max_turns, run_config=run_config,
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        cancelled = True
        raise
    finally:
        finalize_activity(context, cancelled=cancelled)


@asynccontextmanager
async def run_streamed(
    assistant: Assistant, input: Any, *, context: AssistantRunContext | None = None,
    max_turns: int = 10, run_config: RunConfig | None = None,
    input_prepared: bool = False, **context_options: Any,
) -> AsyncIterator[RunResultStreaming]:
    """Own streamed execution and cleanup while the caller consumes SDK events.

    Args:
        assistant: Configured SDK assistant, including a tool-free fallback clone.
        input: User input or already assembled SDK items for a continuation.
        context: Optional context shared across a primary and fallback attempt.
        max_turns: SDK turn limit for this attempt.
        run_config: SDK execution and tracing options.
        input_prepared: Preserve assembled input, including replay/tool items.
        **context_options: Arguments to create_context; only used without context.

    Yields:
        The SDK streaming result for transport-specific event consumption.
    """
    if context is not None and context_options:
        raise ValueError('Context options cannot accompany an existing context')
    if context is None:
        context = await asyncio.to_thread(create_context, assistant, **context_options)
    result = None
    cancelled = False
    try:
        result = Runner.run_streamed(
            assistant,
            input=input if input_prepared else invocation_input(input, assistant.spec.task_prompt),
            context=context, hooks=ActivityRunHooks(), max_turns=max_turns, run_config=run_config,
        )
        yield result
        # SDK cancellation also sets is_complete. The public task distinguishes
        # a cancelled run from one whose model finished normally.
        task = getattr(result, 'run_loop_task', None)
        cancelled = not getattr(result, 'is_complete', True) or bool(task and task.cancelled())
    except (asyncio.CancelledError, GeneratorExit, KeyboardInterrupt):
        cancelled = True
        raise
    finally:
        try:
            if result is not None and not getattr(result, 'is_complete', False):
                await cancel_streamed_result(result, None)
        finally:
            finalize_activity(context, cancelled=cancelled)


async def stream_events(result: RunResultStreaming) -> AsyncIterator[Any]:
    """Consume SDK events and cancel before closing an interrupted iterator.

    The SDK iterator waits for its background run when closed. Cancellation must
    happen first, otherwise a disconnected browser can wait on a running model.

    Args:
        result: Result yielded by run_streamed.

    Yields:
        Unmodified SDK events for a transport adapter.
    """
    events = result.stream_events()
    try:
        async for event in events:
            yield event
    except BaseException:
        await cancel_streamed_result(result, events)
        raise
    finally:
        close = getattr(events, 'aclose', None)
        if close is not None:
            await close()
