"""Load factual references and retain offline historical selection helpers."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from common.discoverers import discover_unique
from common.parsers import (
    first_markdown_heading,
    parse_frontmatter,
    parse_string_list,
)
from common.paths import display_path
from domain.providers.constants import (
    CONTEXT_DIR,
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_SNIPPETS,
    ROOT_DIR,
)
from domain.providers.models import (
    ContextBudgetExceeded,
    ContextFile,
    ContextSnippet,
)
from domain.providers.utils import (
    bound_context_snippets,
    render_context_files,
    rank_context_candidates,
    json_context_sets,
    inherit_collection_descriptions,
    markdown_context_body,
    parse_json_context_object,
)


logger = logging.getLogger(__name__)

def load_context_file(
    path: Path, *, relative_to: Path | None = None
) -> ContextFile:
    """Load one repository-local Markdown file or top-level JSON object.

    Args:
        path: Context source to read.
        relative_to: Root used to produce a stable display path.

    Returns:
        Parsed source metadata and complete source content.

    Raises:
        ValueError: The file has invalid JSON or empty required content.
    """
    text = path.read_text(encoding="utf-8")
    source_path = display_path(path, relative_to=relative_to or ROOT_DIR)

    if path.suffix.casefold() == ".json":
        values = parse_json_context_object(text, path)
        return ContextFile(
            # A path is the JSON source identity because JSON has no metadata
            # block from which a stable logical name could be obtained.
            name=source_path,
            description=f"JSON context from {source_path}",
            body=text,
            path=source_path,
            sets=json_context_sets(path, relative_to=relative_to or ROOT_DIR),
            format="json",
            json_values=tuple(values.items()),
        )

    # Historical offline fixtures consume complete migrated references through
    # this adapter; normal invocations use the metadata-only resource library.
    if text.startswith('---') and '\nid:' in text[:32768]:
        from domain.resources.models import ResourceDescriptor, ResourceMetadata
        from domain.resources.utils import load_content, read_header, source_revision

        metadata = ResourceMetadata.model_validate(read_header(path))
        data_path = path.with_name(metadata.data_file) if metadata.data_file else None
        descriptor = ResourceDescriptor(metadata=metadata, path=path, revision=source_revision(path),
                                        data_path=data_path, data_revision=source_revision(data_path) if data_path else None)
        body = load_content(descriptor).content
        return ContextFile(name=metadata.legacy_name or metadata.id, description=metadata.description,
                           body=body, path=source_path, sets=metadata.sets, kind=metadata.kind)
    parsed = parse_frontmatter(text)
    metadata = parsed.metadata
    body = markdown_context_body(text)
    name = metadata.get("name", path.stem.replace("_", "-")).strip()
    description = metadata.get("description", "").strip() or first_markdown_heading(body)
    if not name:
        raise ValueError(f"Context file at {path} has no name")
    if not body.strip():
        raise ValueError(f"Context file {name!r} has no content")

    return ContextFile(
        name=name,
        description=description,
        body=body,
        path=source_path,
        kind=metadata.get("kind", "reference").strip().casefold() or "reference",
        sets=parse_string_list(metadata.get("sets", ""), casefold=True),
        format="markdown",
    )


def discover_context_files(
    context_dir: Path | None = None,
    *,
    relative_to: Path | None = None,
) -> list[ContextFile]:
    """Discover Markdown and JSON references below a context directory.

    Args:
        context_dir: Directory to scan, defaulting to the bundled corpus.
        relative_to: Root used to produce source display paths.

    Returns:
        Unique context sources with companion routing metadata inherited.
    """
    root = context_dir or CONTEXT_DIR
    source_root = relative_to or (ROOT_DIR if context_dir is None else root)
    sources = discover_unique(
        root,
        ["**/*.md"] if root == CONTEXT_DIR else ["**/*.md", "**/*.json"],
        lambda path: load_context_file(path, relative_to=source_root),
        identity=lambda context_file: context_file.name.casefold(),
        skip_names={"readme.md"},
        on_error=lambda path, exc: logger.warning(
            "ignoring invalid context path=%s error=%s", path, exc
        ),
        on_duplicate=lambda path, context_file: logger.warning(
            "ignoring duplicate context file name=%s path=%s", context_file.name, path
        ),
    )
    return [source for source in inherit_collection_descriptions(sources) if source.kind != 'index']


def select_context_snippets(
    context_files: list[ContextFile],
    query: str,
    *,
    set_number: int | None = None,
    max_snippets: int | None = MAX_CONTEXT_SNIPPETS,
    max_chars: int | None = MAX_CONTEXT_CHARS,
) -> list[ContextSnippet]:
    """Select complete collections locally under explicit caller limits.

    Args:
        context_files: Discovered source catalogue.
        query: Request text used for lexical relevance ranking.
        set_number: Optional set restriction applied before selection.
        max_snippets: Optional maximum number of complete collections.
        max_chars: Optional maximum size of the rendered reference block.

    Returns:
        Complete matching collections in local relevance order.

    Raises:
        ContextBudgetExceeded: Selected collections exceed an explicit limit.
    """
    if (
        (max_snippets is not None and max_snippets <= 0)
        or (max_chars is not None and max_chars <= 0)
        or not context_files or not query.strip()
    ):
        return []
    ranked = rank_context_candidates(
        context_files,
        query,
        set_number=set_number,
    )
    return bound_context_snippets(
        [candidate.snippet for candidate in ranked],
        max_snippets=max_snippets,
        max_chars=max_chars,
    )


__all__ = [
    "CONTEXT_DIR", "MAX_CONTEXT_CHARS", "MAX_CONTEXT_SNIPPETS",
    "ContextFile", "ContextSnippet", "discover_context_files",
    "load_context_file", "render_context_files", "select_context_snippets",
]
