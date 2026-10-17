"""Exact resource reads for assistant-driven progressive disclosure."""

from __future__ import annotations

import asyncio

from typing import Annotated, Any

from agents import function_tool
from agents.tool_context import ToolContext
from pydantic import Field

from domain.assistants.resources import read_resource_content
from domain.runtime.models import AssistantRunContext
from domain.types import AssistantToolGroup


@function_tool(strict_mode=True)
async def read_resource(
    ctx: ToolContext[Any],
    resource_id: Annotated[str, Field(min_length=1, max_length=512)],
) -> dict[str, object]:
    """Read an index, reference, record view, skill, or playbook by stable resource ID.

    Args:
        ctx: SDK tool context identifying the active assistant and invocation.
        resource_id: Exact ID from Available resources; arbitrary paths are denied.

    Returns:
        Full reference facts or workflow instructions, child IDs, and required links.
        Reading an index reveals the next level of permitted resources. Read
        all required populations for counts/comparisons; source completeness does
        not establish complete coverage of game facts. Unknown or denied IDs
        return an unavailable result. No selectors or model calls are involved.
    """
    if not isinstance(ctx.context, AssistantRunContext) or ctx.agent is None:
        return {"found": False, "error": "Resource reads require an assistant invocation."}
    return await asyncio.to_thread(read_resource_content, ctx.context.resources, ctx.agent.name, resource_id)


CONTEXT_TOOL_GROUP = AssistantToolGroup(
    key='context', label='Resource Reading',
    description='Read permitted curated TFT references, skills, and playbooks by exact catalogue ID.',
    tools=(read_resource,),
)

__all__ = ['CONTEXT_TOOL_GROUP', 'read_resource']
