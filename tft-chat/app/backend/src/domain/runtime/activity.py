"""Record SDK execution lifecycle without emitting browser stream events."""

from __future__ import annotations

import time
from typing import Any

from agents import Agent, RunHooks, RunContextWrapper
from agents.tool import Tool
from agents.tool_context import ToolContext

from .models import AssistantRunContext, ToolActivity
from .utils import decode_tool_arguments


class ActivityRunHooks(RunHooks[AssistantRunContext]):
    """Record local tool execution and handoffs on the invocation's context."""

    async def on_tool_start(
        self,
        context: RunContextWrapper[AssistantRunContext],
        agent: Agent[AssistantRunContext],
        tool: Tool,
    ) -> None:
        """Start a call using its SDK identity rather than a shared current tool."""
        if not isinstance(context, ToolContext):
            return
        state = context.context.activity
        call_id = context.tool_call_id
        call = state.calls.get(call_id)
        if call is None:
            call = ToolActivity(call_id=call_id, name=context.tool_name)
            state.calls[call_id] = call
        call.agent_name = agent.name
        call.arguments = decode_tool_arguments(context.tool_arguments)
        call.started_at = time.perf_counter()

    async def on_tool_end(
        self,
        context: RunContextWrapper[AssistantRunContext],
        agent: Agent[AssistantRunContext],
        tool: Tool,
        result: Any,
    ) -> None:
        """Complete only this call, preserving failures recorded by wrappers."""
        if not isinstance(context, ToolContext):
            return
        call = context.context.activity.calls.get(context.tool_call_id)
        if call is not None and call.status == "running":
            call.ended_at = time.perf_counter()
            call.status = "completed"

    async def on_handoff(
        self,
        context: RunContextWrapper[AssistantRunContext],
        from_agent: Agent[AssistantRunContext],
        to_agent: Agent[AssistantRunContext],
    ) -> None:
        """Record the source and destination without sending a browser event."""
        context.context.activity.handoffs.append((from_agent.name, to_agent.name))


def finalize_activity(context: AssistantRunContext, *, cancelled: bool) -> None:
    """Close unfinished calls after a failed or interrupted SDK run.

    Args:
        context: Invocation whose outstanding calls need terminal states.
        cancelled: Whether the consumer or runner cancelled the invocation.
    """
    ended_at = time.perf_counter()
    for call in context.activity.calls.values():
        if call.status == "running":
            call.ended_at = ended_at
            call.status = "cancelled" if cancelled else "failed"
