"""Prepare resource discovery without selecting prompt material or calling models."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from domain.assistants.specs import AssistantSpec
from domain.assistants.utils import can_receive_instruction_resources
from domain.resources.library import get_library
from domain.runtime.models import PreparedResources, ResourceAccess


async def prepare_resources(
    *, specs: Mapping[str, AssistantSpec], set_number: int | None,
    timing: dict[str, Any] | None = None,
) -> PreparedResources:
    """Load a local catalogue; each assistant decides what to read during its run.

    Args:
        specs: Frozen specifications for this invocation graph.
        set_number: TFT set used to restrict reference availability.
        timing: Optional request record receiving catalogue loading duration.

    Returns:
        Available resources and per-assistant permissions, with no initial reads.
    """
    started = time.perf_counter()
    # Filesystem discovery belongs off the event loop; it never makes model calls.
    eligible = any(
        spec.repository_context
        or can_receive_instruction_resources(spec, spec.skill_names)
        or can_receive_instruction_resources(spec, spec.playbook_names)
        for spec in specs.values()
    )
    library = await asyncio.to_thread(get_library) if eligible else None
    skills = tuple(resource_id.removeprefix('skill:') for resource_id, descriptor in library.entries.items()
                   if descriptor.metadata.kind == 'skill') if library else ()
    playbooks = tuple(resource_id.removeprefix('playbook:') for resource_id, descriptor in library.entries.items()
                      if descriptor.metadata.kind == 'playbook') if library else ()
    access = {}
    for name, spec in specs.items():
        # Tool access and resource policy must both permit reads. A resource flag
        # alone must not grant a new model-facing capability to a saved graph.
        can_read = spec.include_all_tools or 'context' in spec.tool_group_keys or 'read_resource' in spec.tool_names
        access[name] = ResourceAccess(
            references=can_read and spec.repository_context,
            skills=tuple(
                skill for skill in skills
                if can_read
                and can_receive_instruction_resources(spec, spec.skill_names)
                and (spec.skill_names is None or skill in spec.skill_names)
            ),
            playbooks=tuple(
                playbook for playbook in playbooks
                if can_read
                and can_receive_instruction_resources(spec, spec.playbook_names)
                and (spec.playbook_names is None or playbook in spec.playbook_names)
            ),
        )
    if timing is not None:
        timing['resource_catalogue_ms'] = round((time.perf_counter() - started) * 1000, 3)
    return PreparedResources(library=library, set_number=set_number, access=access)



__all__ = ['prepare_resources']
