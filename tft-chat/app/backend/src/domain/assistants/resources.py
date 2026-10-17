"""Prepare resource permissions and expose permitted metadata and exact reads."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from domain.assistants.constants import AssistantName
from domain.assistants.models import AssistantSpec
from domain.resources.library import get_library, read_content
from domain.runtime.models import PreparedResources, ResourceAccess


def prepare_resources(
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
    if timing is not None:
        timing['resource_catalogue_ms'] = round((time.perf_counter() - started) * 1000, 3)
    return PreparedResources(library=library, set_number=set_number, access=access)


def resource_entries(
    resources: PreparedResources, name: str, parent: str | None = None,
) -> list[dict[str, object]]:
    """Describe visible roots or direct children without loading bodies.

    Args:
        resources: Invocation library and frozen per-assistant permissions.
        name: Registered active assistant identity.
        parent: Optional exact ID whose direct children are requested.

    Returns:
        Child IDs and descriptions; unavailable resources reveal no metadata.
    """
    library = resources.library
    if library is None:
        return []
    if parent is not None and not can_read_resource(resources, name, parent):
        return []
    entries = []
    for resource_id, descriptor in library.entries.items():
        actual_parent = descriptor.metadata.id if descriptor.view else descriptor.metadata.parent
        if actual_parent != parent or not can_read_resource(resources, name, resource_id):
            continue
        metadata = descriptor.metadata
        entries.append({'id': resource_id,
                        'name': metadata.title + (f' — {descriptor.view}' if descriptor.view else ''),
                        'description': metadata.description,
                        'kind': 'reference' if descriptor.view else metadata.kind,
                        'patches': metadata.patches})
    return entries


def can_read_resource(resources: PreparedResources, name: str, resource_id: str) -> bool:
    """Check exact catalogue membership, set scope, and inherited skill access.

    Args:
        resources: Invocation-local library and frozen access settings.
        name: Assistant identity supplied by the SDK.
        resource_id: Requested stable resource identity.

    Returns:
        Whether this assistant may read the resource, discovered or otherwise.
    """
    if resources.library is None or resource_id not in resources.library.entries:
        return False
    metadata = resources.library.entries[resource_id].metadata
    access = resources.access.get(name, ResourceAccess())
    if resource_id.startswith('playbook:'):
        return resource_id.split('/')[0].removeprefix('playbook:') in access.playbooks
    if resource_id.startswith('skill:'):
        return resource_id.split('/')[0].removeprefix('skill:') in access.skills
    return access.references and (resources.set_number is None or str(resources.set_number) in metadata.sets)


def read_resource_content(resources: PreparedResources, name: str, resource_id: str) -> dict[str, object]:
    """Return one complete resource with visible children and dependency links.

    Args:
        resources: Invocation library, read provenance, and access settings.
        name: Active assistant supplied by the SDK, never by the model.
        resource_id: Stable resource identity from a directory or reference link.

    Returns:
        Full content and metadata, or an indistinguishable denied/unknown result.
    """
    if not can_read_resource(resources, name, resource_id):
        return {'found': False, 'error': 'Resource unavailable; use a permitted resource ID.'}
    descriptor = resources.library.entries[resource_id]
    try:
        read = read_content(resources.library, resource_id)
    except (ValueError, OSError) as error:
        return {'found': False, 'error': str(error)}
    resources.reads[resource_id] = read
    metadata = descriptor.metadata
    links = {}
    for key in ('requires', 'related'):
        links[key] = tuple(value for value in getattr(metadata, key)
                           if can_read_resource(resources, name, value))
    if descriptor.view not in {None, 'stage-all'} and 'stage-all' in metadata.views:
        links['requires'] += (f'{metadata.id}/stage-all',)
    return {
        'found': True, 'resource_id': resource_id,
        'kind': resource_id.split(':', 1)[0] if resource_id.startswith(('skill:', 'playbook:')) else 'reference',
        'resource_kind': metadata.kind if not descriptor.view else 'view',
        'name': metadata.title, 'path': read.path,
        'heading': descriptor.view or '', 'content': read.content, 'complete': True,
        'sha256': read.sha256, 'record_ids': read.record_ids,
        'sets': metadata.sets, 'patches': metadata.patches,
        'provenance': metadata.provenance,
        'children': resource_entries(resources, name, resource_id), **links,
    }
