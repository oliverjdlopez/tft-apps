"""Build validated metadata snapshots and load resource bodies on demand."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import RLock

from domain.resources.models import ResourceDescriptor, ResourceLibrary, ResourceMetadata, ResourceRead
from domain.resources.utils import load_content, read_header, skill_metadata, source_revision

RESOURCE_ROOT = Path(__file__).resolve().parents[2] / 'resources'
REFERENCE_ROOT = RESOURCE_ROOT / 'references'
SKILL_ROOT = RESOURCE_ROOT / 'skills'
_CACHE: dict[tuple, ResourceLibrary] = {}
_CACHE_LOCK = RLock()


def build_library(reference_root: Path = REFERENCE_ROOT, skill_root: Path = SKILL_ROOT) -> ResourceLibrary:
    """Validate the complete metadata graph without consuming resource bodies.

    Args:
        reference_root: Approved root of reference Markdown and backing records.
        skill_root: Approved root of portable skill packages and supporting files.

    Returns:
        An independently validated library with an initially empty body cache.
    """
    library = ResourceLibrary()
    roots = (reference_root.resolve(), skill_root.resolve())
    declared_data = set()
    paths = sorted(reference_root.rglob('*.md')) + sorted(skill_root.rglob('*.md'))
    for path in paths:
        if path.is_symlink() or not any(path.resolve().is_relative_to(root) for root in roots):
            raise ValueError(f'Resource escapes approved roots: {path}')
        revision = source_revision(path)
        metadata = (skill_metadata(path, skill_root) if path.name == 'SKILL.md'
                    else ResourceMetadata.model_validate(read_header(path)))
        if path.is_relative_to(reference_root) and metadata.id.startswith('skill:'):
            raise ValueError(f'Skill metadata cannot live in reference storage: {path}')
        if path.is_relative_to(skill_root) and not metadata.id.startswith('skill:'):
            raise ValueError(f'Reference metadata cannot live in skill storage: {path}')
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
            if metadata.id.startswith('skill:'):
                owner = metadata.id.split('/')[0]
                if not metadata.parent.startswith(owner) or not resource_id.startswith(metadata.parent + '/'):
                    raise ValueError(f'Skill child must inherit its package: {resource_id}')
            elif not resource_id.startswith(metadata.parent + '/') or metadata.sets != parent.sets:
                raise ValueError(f'Child must inherit parent identity and set scope: {resource_id}')
        elif metadata.kind not in {'index', 'skill'}:
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


def get_library(reference_root: Path = REFERENCE_ROOT, skill_root: Path = SKILL_ROOT) -> ResourceLibrary:
    """Reuse metadata and body caches until an authored source revision changes.

    Args:
        reference_root: Reference source root.
        skill_root: Skill package root.

    Returns:
        A validated snapshot; old invocations retain their prior snapshot.
    """
    paths = sorted(reference_root.rglob('*')) + sorted(skill_root.rglob('*'))
    signature = (str(reference_root), str(skill_root), tuple(
        (str(path), source_revision(path)) for path in paths if path.is_file()
    ))
    with _CACHE_LOCK:
        if signature not in _CACHE:
            library = build_library(reference_root, skill_root)
            # Existing invocations retain their object; avoid unbounded global history.
            _CACHE.clear()
            _CACHE[signature] = library
        return _CACHE[signature]


def read_content(library: ResourceLibrary, resource_id: str) -> ResourceRead:
    """Read one approved source revision and cache its complete rendered content.

    Args:
        library: Validated snapshot already selected by invocation preparation.
        resource_id: Exact known ID, independent of filesystem paths.

    Returns:
        Complete source or derived-view contents with revision provenance.
    """
    # Cache access is serialized because parallel SDK reads can run on threads.
    with _CACHE_LOCK:
        if resource_id not in library.body_cache:
            library.body_cache[resource_id] = load_content(library.entries[resource_id])
        return library.body_cache[resource_id]


def validate_library(reference_root: Path = REFERENCE_ROOT, skill_root: Path = SKILL_ROOT) -> ResourceLibrary:
    """Validate metadata, every complete body, and every declared structured view.

    Args:
        reference_root: Reference source root.
        skill_root: Skill package root.

    Returns:
        Fully checked library suitable for an offline validation receipt.
    """
    library = build_library(reference_root, skill_root)
    record_owners = {}
    for resource_id, descriptor in library.entries.items():
        read = read_content(library, resource_id)
        if descriptor.view is None:
            for record_id in read.record_ids:
                if record_id in record_owners:
                    raise ValueError(f'Record identity has multiple authoritative owners: {record_id}')
                record_owners[record_id] = resource_id
    return library
