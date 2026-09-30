"""Small parsers shared by file-backed configuration and content loaders."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)\Z",
    re.DOTALL,
)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")


@dataclass(frozen=True)
class ParsedMarkdown:
    """Markdown body and the simple scalar frontmatter that preceded it."""

    metadata: dict[str, str]
    body: str


def unquote(value: str) -> str:
    """Strip whitespace and one matching pair of single or double quotes."""

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_frontmatter(
    text: str,
    *,
    casefold_keys: bool = True,
) -> ParsedMarkdown:
    """Parse the repository's flat ``key: value`` Markdown frontmatter."""

    match = _FRONTMATTER_RE.match(text)
    if not match:
        return ParsedMarkdown(metadata={}, body=text)

    raw_metadata, body = match.groups()
    metadata: dict[str, str] = {}
    for line in raw_metadata.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition(":")
        if not separator:
            continue
        normalized_key = key.strip().casefold() if casefold_keys else key.strip()
        metadata[normalized_key] = unquote(value)
    return ParsedMarkdown(metadata=metadata, body=body)


def first_markdown_heading(text: str) -> str:
    """Return the first ATX heading's text, or an empty string."""

    for line in text.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match:
            return match.group(1).strip()
    return ""


def parse_string_list(
    value: Any,
    *,
    field: str = "value",
    casefold: bool = False,
) -> tuple[str, ...]:
    """Parse a comma-delimited string or string sequence into a tuple."""

    if value is None:
        return ()
    if isinstance(value, str):
        raw_items = value.strip().removeprefix("[").removesuffix("]").split(",")
    elif isinstance(value, list | tuple):
        raw_items = value
    else:
        raise ValueError(f"{field} must be a string or list of strings")

    parsed: list[str] = []
    for item in raw_items:
        if not isinstance(item, str):
            raise ValueError(f"{field} must only contain strings")
        entry = unquote(item).strip()
        if entry:
            parsed.append(entry.casefold() if casefold else entry)
    return tuple(parsed)


__all__ = [
    "ParsedMarkdown",
    "first_markdown_heading",
    "parse_frontmatter",
    "parse_string_list",
    "unquote",
]
