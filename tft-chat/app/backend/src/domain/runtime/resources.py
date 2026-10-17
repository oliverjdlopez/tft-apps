"""Gather the resource catalogue and freeze graph access for an invocation."""

from collections.abc import Mapping

from domain.assistants.constants import AssistantName
from domain.assistants.models import AssistantSpec
from domain.resources.library import get_library
from domain.runtime.models import PreparedResources, ResourceAccess


def prepare_resources(
    *, specs: Mapping[str, AssistantSpec], set_number: int | None,
) -> PreparedResources:
    """Load a local catalogue; each assistant decides what to read during its run.

    Args:
        specs: Frozen specifications for this invocation graph.
        set_number: TFT set used to restrict reference availability.

    Returns:
        Available resources and per-assistant permissions, with no initial reads.
    """
    eligible = any(
        spec.repository_context or (
            spec.name != AssistantName.CHAT and (spec.skill_names or spec.playbook_names)
        )
        for spec in specs.values()
    )
    library = get_library() if eligible else None
    available = {"skills": [], "playbooks": []}
    if library is not None:
        for resource_id, descriptor in library.entries.items():
            if descriptor.metadata.kind in {"skill", "playbook"}:
                available[descriptor.metadata.kind + "s"].append(resource_id.split(":", 1)[1])

    access = {}
    for name, spec in specs.items():
        # A resource flag must never grant a tool capability to a saved graph.
        can_read = (
            spec.include_all_tools or "context" in spec.tool_group_keys
            or "read_resource" in spec.tool_names
        )
        permitted = {}
        for kind, configured in (("skills", spec.skill_names), ("playbooks", spec.playbook_names)):
            # None allows every discovered entry; () denies this category.
            eligible = (
                can_read and spec.name != AssistantName.CHAT
                and (spec.repository_context or bool(configured))
            )
            permitted[kind] = tuple(
                value for value in available[kind]
                if eligible and (configured is None or value in configured)
            )
        access[name] = ResourceAccess(
            references=can_read and spec.repository_context, **permitted,
        )
    return PreparedResources(library=library, set_number=set_number, access=access)


