"""Build validated metadata snapshots and load resource bodies on demand."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import RLock

from domain.resources.models import ResourceDescriptor, ResourceLibrary, ResourceMetadata, ResourceRead
from domain.resources.utils import instruction_metadata, load_content, read_header, source_revision

RESOURCE_ROOT = Path(__file__).resolve().parents[2] / 'resources'
REFERENCE_ROOT = RESOURCE_ROOT / 'references'
SKILL_ROOT = RESOURCE_ROOT / 'skills'
PLAYBOOK_ROOT = RESOURCE_ROOT / 'playbooks'
_CACHE: dict[tuple, ResourceLibrary] = {}
_CACHE_LOCK = RLock()


def build_library(reference_root: Path = REFERENCE_ROOT, skill_root: Path = SKILL_ROOT,
                  playbook_root: Path = PLAYBOOK_ROOT) -> ResourceLibrary:
    """Validate the complete metadata graph without consuming resource bodies.

    Args:
        reference_root: Approved root of reference Markdown and backing records.
        skill_root: Approved root of portable skill packages and supporting files.
        playbook_root: Approved root of specific guide packages and supporting files.

    Returns:
        An independently validated library with an initially empty body cache.
    """
    library = ResourceLibrary()
    stores = ((reference_root, None), (skill_root, 'skill'), (playbook_root, 'playbook'))
    roots = tuple(root.resolve() for root, _ in stores)
    declared_data = set()
    paths = [(root, kind, path) for root, kind in stores for path in sorted(root.rglob('*.md'))]
    for root, kind, path in paths:
        if path.is_symlink() or not any(path.resolve().is_relative_to(root) for root in roots):
            raise ValueError(f'Resource escapes approved roots: {path}')
        revision = source_revision(path)
        entrypoint = f'{kind.upper()}.md' if kind else None
        metadata = (instruction_metadata(path, root, kind) if path.name == entrypoint
                    else ResourceMetadata.model_validate(read_header(path)))
        namespace = metadata.id.split(':', 1)[0]
        if (kind is None and namespace in {'skill', 'playbook'}) or (kind and namespace != kind):
            raise ValueError(f'Resource namespace does not match its storage: {path}')
        if kind and metadata.kind == kind and path.name != entrypoint:
            raise ValueError(f'Instruction entry point must be {entrypoint}: {path}')
        if metadata.id in library.entries:
            raise ValueError(f'Duplicate resource ID: {metadata.id}')
        data_path = path.with_name(metadata.data_file) if metadata.data_file else None
        if data_path is not None:
            if data_path.is_symlink() or not data_path.resolve().is_relative_to(reference_root.resolve()):
                raise ValueError(f'Records escape approved root: {data_path}')
            if data_path in declared_data:
                raise ValueError(f'Record source has multiple owners: {data_path}')
            declared_data.add(data_path)
        if source_revision(path) != revision:
            raise ValueError(f'Resource metadata changed during discovery: {path}')
        descriptor = ResourceDescriptor(metadata=metadata, path=path.resolve(),
                                        revision=revision, data_path=data_path.resolve() if data_path else None,
                                        data_revision=source_revision(data_path) if data_path else None)
        library.entries[metadata.id] = descriptor
    # Undeclared data would silently disappear from discovery; reject it explicitly.
    if set(reference_root.rglob('*.json')) != declared_data:
        raise ValueError('Reference JSON must have exactly one declared record owner')
    for resource_id, descriptor in tuple(library.entries.items()):
        metadata = descriptor.metadata
        links = ((metadata.parent,) if metadata.parent else ()) + metadata.requires + metadata.related
        for link in links:
            if link not in library.entries:
                raise ValueError(f'Broken resource link: {resource_id} -> {link}')
            if link == resource_id:
                raise ValueError(f'Self-referencing resource link: {resource_id}')
        if metadata.parent:
            parent = library.entries[metadata.parent].metadata
            if metadata.id.startswith(('skill:', 'playbook:')):
                owner = metadata.id.split('/')[0]
                if not metadata.parent.startswith(owner) or not resource_id.startswith(metadata.parent + '/'):
                    raise ValueError(f'Instruction child must inherit its package: {resource_id}')
            elif not resource_id.startswith(metadata.parent + '/') or metadata.sets != parent.sets:
                raise ValueError(f'Child must inherit parent identity and set scope: {resource_id}')
        elif metadata.kind not in {'index', 'skill', 'playbook'}:
            raise ValueError(f'Leaf resource needs a parent: {resource_id}')
        for view in metadata.views:
            view_id = f'{resource_id}/{view}'
            if view_id in library.entries:
                raise ValueError(f'Duplicate derived resource ID: {view_id}')
            library.entries[view_id] = replace(descriptor, view=view)
    for resource_id in library.entries:
        visited = set()
        current = resource_id
        while current is not None:
            if current in visited:
                raise ValueError(f'Cyclic resource parents: {resource_id}')
            visited.add(current)
            descriptor = library.entries[current]
            current = descriptor.metadata.id if descriptor.view else descriptor.metadata.parent
    # Required dependencies are directional; related-resource links may be mutual.
    for resource_id in library.entries:
        pending = [(resource_id, ())]
        while pending:
            current, ancestors = pending.pop()
            if current in ancestors:
                raise ValueError(f'Cyclic required resource dependencies: {resource_id}')
            pending.extend((required, (*ancestors, current))
                           for required in library.entries[current].metadata.requires)
    library.roots = tuple(resource_id for resource_id, descriptor in library.entries.items()
                          if descriptor.metadata.parent is None and descriptor.view is None)
    return library


def get_library(reference_root: Path = REFERENCE_ROOT, skill_root: Path = SKILL_ROOT,
                  playbook_root: Path = PLAYBOOK_ROOT) -> ResourceLibrary:
    """Reuse metadata and body caches until an authored source revision changes.

    Args:
        reference_root: Reference source root.
        skill_root: Skill package root.
        playbook_root: Playbook package root.

    Returns:
        A validated snapshot; old invocations retain their prior snapshot.
    """
    paths = [path for root in (reference_root, skill_root, playbook_root) for path in sorted(root.rglob('*'))]
    signature = (str(reference_root), str(skill_root), str(playbook_root), tuple(
        (str(path), source_revision(path)) for path in paths if path.is_file()
    ))
    with _CACHE_LOCK:
        if signature not in _CACHE:
            library = build_library(reference_root, skill_root, playbook_root)
            # Existing invocations retain their object; avoid unbounded global history.
            _CACHE.clear()
            _CACHE[signature] = library
        return _CACHE[signature]


def resource_entries(
    library: ResourceLibrary | None, parent: str | None = None,
) -> list[dict[str, object]]:
    """Describe catalogue roots or direct children without loading bodies.

    Args:
        library: Resource catalogue supplied by the caller.
        parent: Optional exact ID whose direct children are requested.

    Returns:
        Child IDs and descriptions from the supplied catalogue.
    """
    if library is None:
        return []
    if parent is not None and parent not in library.entries:
        return []
    entries = []
    for resource_id, descriptor in library.entries.items():
        actual_parent = descriptor.metadata.id if descriptor.view else descriptor.metadata.parent
        if actual_parent != parent:
            continue
        metadata = descriptor.metadata
        entries.append({'id': resource_id,
                        'name': metadata.title + (f' — {descriptor.view}' if descriptor.view else ''),
                        'description': metadata.description,
                        'kind': 'reference' if descriptor.view else metadata.kind,
                        'patches': metadata.patches})
    return entries


def read_content(library: ResourceLibrary, resource_id: str) -> ResourceRead:
    """Read one approved source revision and cache its complete rendered content.

    Args:
        library: Validated snapshot already selected by invocation preparation.
        resource_id: Exact known ID, independent of filesystem paths.

    Returns:
        Complete source or derived-view contents with revision provenance.
    """
    # A shared cache may contain bodies outside this catalogue. Resolve membership
    # before consulting it so a library view remains an exact set of readable IDs.
    descriptor = library.entries[resource_id]
    # Cache access is serialized because parallel SDK reads can run on threads.
    with _CACHE_LOCK:
        if resource_id not in library.body_cache:
            library.body_cache[resource_id] = load_content(descriptor)
        return library.body_cache[resource_id]


def validate_library(reference_root: Path = REFERENCE_ROOT, skill_root: Path = SKILL_ROOT,
                  playbook_root: Path = PLAYBOOK_ROOT) -> ResourceLibrary:
    """Validate metadata, every complete body, and every declared structured view.

    Args:
        reference_root: Reference source root.
        skill_root: Skill package root.
        playbook_root: Playbook package root.

    Returns:
        Fully checked library suitable for an offline validation receipt.
    """
    library = build_library(reference_root, skill_root, playbook_root)
    record_owners = {}
    for resource_id, descriptor in library.entries.items():
        read = read_content(library, resource_id)
        if descriptor.view is None:
            for record_id in read.record_ids:
                if record_id in record_owners:
                    raise ValueError(f'Record identity has multiple authoritative owners: {record_id}')
                record_owners[record_id] = resource_id
    return library
