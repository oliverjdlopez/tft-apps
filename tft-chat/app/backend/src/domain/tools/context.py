"""Exact resource reads for assistant-driven progressive disclosure."""

from __future__ import annotations

import asyncio

from typing import Annotated, Any

from agents import function_tool
from agents.tool_context import ToolContext
from pydantic import Field

from domain.assistants.models import AssistantSpec
from domain.resources.library import read_content, resource_entries
from domain.resources.models import ResourceLibrary, ResourceRead
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
    # Access follows the active instance's spec, never its display name or cache.
    spec = getattr(ctx.agent, 'spec', None)
    if not isinstance(ctx.context, AssistantRunContext) or not isinstance(spec, AssistantSpec):
        return {"found": False, "error": "Resource reads require an assistant invocation."}
    return await asyncio.to_thread(
        read_resource_content, ctx.context.resources, resource_id,
        spec=spec, reads=ctx.context.activity.resource_reads,
    )


def read_resource_content(
    library: ResourceLibrary, resource_id: str,
    *, spec: AssistantSpec, reads: dict[str, ResourceRead] | None = None,
) -> dict[str, object]:
    """Return one complete resource with its catalogue children and links.

    Args:
        library: Shared repository library supplied by the invocation.
        resource_id: Stable resource identity from a directory or reference link.
        spec: Active assistant definition controlling reads and returned metadata.
        reads: Optional caller-owned record of successfully returned resources.

    Returns:
        Full content and metadata, or an unavailable result for an absent ID.
    """
    if resource_id not in library.entries or not spec.allows_resource(resource_id):
        return {'found': False, 'error': 'Resource unavailable; use a catalogue resource ID.'}
    descriptor = library.entries[resource_id]
    try:
        read = read_content(library, resource_id)
    except (ValueError, OSError) as error:
        return {'found': False, 'error': str(error)}
    if reads is not None:
        reads[resource_id] = read
    metadata = descriptor.metadata
    links = {}
    for key in ('requires', 'related'):
        links[key] = tuple(value for value in getattr(metadata, key)
                           if value in library.entries and spec.allows_resource(value))
    if (descriptor.view not in {None, 'stage-all'}
            and f'{metadata.id}/stage-all' in library.entries
            and spec.allows_resource(f'{metadata.id}/stage-all')):
        links['requires'] += (f'{metadata.id}/stage-all',)
    return {
        'found': True, 'resource_id': resource_id,
        'kind': resource_id.split(':', 1)[0] if resource_id.startswith(('skill:', 'playbook:')) else 'reference',
        'resource_kind': metadata.kind if not descriptor.view else 'view',
        'name': metadata.title, 'path': read.path,
        'heading': descriptor.view or '', 'content': read.content, 'complete': True,
        'sha256': read.sha256, 'record_ids': read.record_ids,
        'patches': metadata.patches,
        'provenance': metadata.provenance,
        'children': [entry for entry in resource_entries(library, resource_id)
                     if spec.allows_resource(entry['id'])], **links,
    }

CONTEXT_TOOL_GROUP = AssistantToolGroup(
    key='context', label='Resource Reading',
    description='Read permitted curated TFT references, skills, and playbooks by exact catalogue ID.',
    tools=(read_resource,),
)

__all__ = ['CONTEXT_TOOL_GROUP', 'read_resource']
