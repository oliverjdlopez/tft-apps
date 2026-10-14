"""Parsing, validation, and rendering helpers for the resource library."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from domain.resources.models import ResourceDescriptor, ResourceMetadata, ResourceRead, WispDocument


# ---------------------------------------------------------------------------
# Resource metadata parsing
#
# Headers are scanned without consuming document bodies during discovery.
# Strict YAML maps prevent silent duplicate-key or malformed-metadata recovery.
# ---------------------------------------------------------------------------


class UniqueKeyLoader(yaml.SafeLoader):
    """Parse safe YAML while rejecting ambiguous duplicate mapping keys."""


def unique_mapping(loader: UniqueKeyLoader, node: Any) -> dict:
    """Construct a mapping without silently accepting overwritten metadata.

    Args:
        loader: Safe loader resolving this mapping.
        node: YAML mapping node.

    Returns:
        A mapping with unique keys.
    """
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError(f'Duplicate metadata key: {key}')
        result[key] = loader.construct_object(value_node, deep=True)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def read_header(path: Path) -> dict[str, Any]:
    """Read only a bounded YAML frontmatter block, leaving the body untouched.

    Args:
        path: Approved Markdown source.

    Returns:
        Validated YAML mapping, before resource-specific schema validation.
    """
    with path.open(encoding='utf-8') as stream:
        if stream.readline().strip() != '---':
            raise ValueError(f'Missing resource frontmatter: {path}')
        lines = []
        size = 0
        for line in stream:
            if line.strip() == '---':
                break
            size += len(line)
            if size > 32768:
                raise ValueError(f'Resource header exceeds 32 KiB: {path}')
            lines.append(line)
        else:
            raise ValueError(f'Unterminated resource header: {path}')
    value = yaml.load(''.join(lines), Loader=UniqueKeyLoader)
    if not isinstance(value, dict):
        raise ValueError(f'Resource frontmatter must be an object: {path}')
    return value


def markdown_body(text: str) -> str:
    """Remove frontmatter without reformatting source claims.

    Args:
        text: Complete approved Markdown source.

    Returns:
        Body with original headings, whitespace, and tables retained.
    """
    match = re.match(r'\A---\s*\r?\n.*?\r?\n---[ \t]*\r?\n?', text, re.DOTALL)
    if match is None:
        raise ValueError('Missing or unterminated resource frontmatter')
    body = text[match.end():]
    if not body.strip():
        raise ValueError('Resource body cannot be empty')
    return body


def source_revision(path: Path) -> tuple[int, int]:
    """Identify a local source revision for cache invalidation and lazy reads.

    Args:
        path: Source file whose metadata or content may change.

    Returns:
        Nanosecond modification time and file size.
    """
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def skill_metadata(path: Path, root: Path) -> ResourceMetadata:
    """Adapt portable SKILL.md metadata without adding custom protocol fields.

    Args:
        path: Skill entry point under the configured skill root.
        root: Root used to validate direct-child skill packages.

    Returns:
        A stable skill descriptor shared by discovery and permission checks.
    """
    metadata = read_header(path)
    allowed = {'name', 'description', 'license', 'compatibility', 'metadata', 'allowed-tools'}
    if set(metadata) - allowed:
        raise ValueError(f'Unsupported skill protocol fields: {path}')
    name, description = metadata.get('name'), metadata.get('description')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or len(name) > 64:
        raise ValueError(f'Invalid skill name: {path}')
    if path.parent.parent != root or path.parent.name != name:
        raise ValueError(f'Skill name must match its direct-child package: {path}')
    return ResourceMetadata(id=f'skill:{name}', title=name, description=description, kind='skill')


# ---------------------------------------------------------------------------
# Exact content loading and record views
#
# Typed offer windows drive views. Full source wording remains authoritative
# for restrictions beyond the fields normalized during the corpus migration.
# ---------------------------------------------------------------------------


def duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys before typed records are validated.

    Args:
        pairs: Object entries from the JSON decoder.

    Returns:
        A complete unambiguous object.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def record_views(document: WispDocument) -> tuple[str, ...]:
    """Derive stage membership from typed windows, including all-stage variants.

    Args:
        document: Validated authoritative record population.

    Returns:
        Nonempty stage views in numeric order, followed by all-stage membership.
    """
    stages = {stage for record in document.records for window in record.offer_windows
              for stage in range(window.start[0], window.end[0] + 1)}
    return tuple(f'stage-{stage}' for stage in sorted(stages)) + (
        ('stage-all',) if any(record.all_stages for record in document.records) else ()
    )


def load_content(descriptor: ResourceDescriptor) -> ResourceRead:
    """Load one pinned source and render its complete document or stage view.

    Args:
        descriptor: Approved metadata snapshot with backing source revisions.

    Returns:
        Complete body, source hash, and stable record IDs when applicable.
    """
    if descriptor.path.is_symlink() or descriptor.path.resolve() != descriptor.path:
        raise ValueError('Resource source path changed outside its approved location')
    if descriptor.data_path is not None and (
        descriptor.data_path.is_symlink() or descriptor.data_path.resolve() != descriptor.data_path
    ):
        raise ValueError('Resource data path changed outside its approved location')
    if source_revision(descriptor.path) != descriptor.revision:
        raise ValueError('Resource changed after preparation; start a fresh invocation')
    raw = descriptor.path.read_bytes()
    body = markdown_body(raw.decode('utf-8'))
    record_ids = ()
    metadata = descriptor.metadata
    digest_bytes = raw
    if descriptor.data_path is not None:
        if source_revision(descriptor.data_path) != descriptor.data_revision:
            raise ValueError('Resource records changed after preparation; start a fresh invocation')
        data = descriptor.data_path.read_bytes()
        document = WispDocument.model_validate(json.loads(data, object_pairs_hook=duplicate_json_keys))
        if record_views(document) != metadata.views:
            raise ValueError(f'Declared views disagree with record eligibility: {metadata.id}')
        records = document.records
        if descriptor.view is not None:
            stage = descriptor.view.removeprefix('stage-')
            records = tuple(record for record in records if (
                record.all_stages if stage == 'all' else any(
                    window.start[0] <= int(stage) <= window.end[0] for window in record.offer_windows
                )
            ))
        record_ids = tuple(record.id for record in records)
        body = body.rstrip() + '\n\n' + '\n'.join(
            f'- **{record.name}** [variant: {record.id}] — {record.text}' for record in records
        ) + '\n'
        digest_bytes = raw + b'\0' + data
    # Check again after reads so concurrent authoring cannot produce mixed revisions.
    if source_revision(descriptor.path) != descriptor.revision or (
        descriptor.data_path is not None and source_revision(descriptor.data_path) != descriptor.data_revision
    ):
        raise ValueError('Resource changed during read; start a fresh invocation')
    source_root = Path(__file__).resolve().parents[2] / 'resources'
    source_path = (str(descriptor.path.relative_to(source_root))
                   if descriptor.path.is_relative_to(source_root) else descriptor.path.name)
    return ResourceRead(id=metadata.id + (f'/{descriptor.view}' if descriptor.view else ''),
                        path=source_path, kind=metadata.kind,
                        sha256=hashlib.sha256(digest_bytes).hexdigest(), content=body,
                        record_ids=record_ids)
