"""Selection benchmark helpers shared by the evaluation worker."""
from __future__ import annotations
import json
from typing import Any
from domain.providers.context import MAX_CONTEXT_CHARS, MAX_CONTEXT_SNIPPETS, _ContextCandidate, _bound_context_snippets

_MATCH_FIELDS = frozenset(
    {
        "source",
        "path",
        "kind",
        "description",
        "type",
        "title",
        "key",
        "section_path",
        "content",
    }
)

_SOURCE_PAYLOAD_FIELDS = frozenset({"id", "path", "kind", "description"})

_PART_PAYLOAD_FIELDS = frozenset(
    {
        "id",
        "source_id",
        "type",
        "title",
        "key",
        "section_path",
        "catalogue",
    }
)

def candidate_field(candidate: _ContextCandidate, field: str) -> object:
    """Map a gold matcher field to its context-candidate descriptor."""
    snippet = candidate.snippet
    return {
        "source": snippet.context_file,
        "path": snippet.path,
        "kind": candidate.kind,
        "description": candidate.description,
        "type": candidate.part_type,
        "title": candidate.title,
        "key": snippet.key,
        "section_path": snippet.heading,
        "content": snippet.content,
    }[field]

def contains_value(actual: object, expected: object) -> bool:
    """Match every expected descriptor against candidate values case-insensitively."""
    needles = expected if isinstance(expected, list) else [expected]
    values = actual if isinstance(actual, (list, tuple)) else [actual]
    return all(
        any(str(needle).casefold() in str(value).casefold() for value in values)
        for needle in needles
    )

def matches(candidate: _ContextCandidate, expected: dict[str, object]) -> bool:
    """Require all populated gold fields to match the same context candidate."""
    return all(
        not value or contains_value(candidate_field(candidate, field), value)
        for field, value in expected.items()
    )

def coverage(
    candidates: list[_ContextCandidate], expected: list[dict[str, object]]
) -> tuple[int, int]:
    """Count gold expectations satisfied by the selected candidate set."""
    hits = sum(
        any(matches(candidate, item) for candidate in candidates)
        for item in expected
    )
    return hits, len(expected)

def validate_cases(
    cases: list[dict[str, Any]], candidates: list[_ContextCandidate]
) -> None:
    """Validate selector identities and gold expectations before evaluation."""
    case_names: set[str] = set()
    for case in cases:
        name = str(case.get("name", "")).strip()
        query = str(case.get("query", "")).strip()
        if not name or name in case_names:
            raise ValueError(f"case names must be non-empty and unique: {name!r}")
        if not query:
            raise ValueError(f"case {name!r} has no query")
        case_names.add(name)
        required = case.get("required", [])
        forbidden = case.get("forbidden", [])
        if not isinstance(required, list) or not isinstance(forbidden, list):
            raise ValueError(f"case {name!r} gold fields must be lists")
        for expected in [*required, *forbidden]:
            if not isinstance(expected, dict) or not expected:
                raise ValueError(f"case {name!r} contains an empty gold matcher")
            unknown = set(expected) - _MATCH_FIELDS
            if unknown:
                raise ValueError(
                    f"case {name!r} uses unknown match fields: {sorted(unknown)}"
                )
        if case.get("expect_empty") and required:
            raise ValueError(f"empty case {name!r} cannot require context")
        if required and not all(
            any(matches(candidate, expected) for candidate in candidates)
            for expected in required
        ):
            raise ValueError(f"case {name!r} has required gold absent from the corpus")

def validate_payload(prompt: str, *, candidate_count: int) -> None:
    """Enforce the selector payload schema before measuring or calling a model."""
    payload = json.loads(prompt)
    if set(payload) != {"query", "max_selected", "sources", "parts"}:
        raise ValueError("selector payload has unexpected top-level fields")
    if len(payload["parts"]) != candidate_count:
        raise ValueError("selector payload part count does not match candidates")
    if any(set(source) != _SOURCE_PAYLOAD_FIELDS for source in payload["sources"]):
        raise ValueError("selector source payload is not description-centric")
    if any(set(part) != _PART_PAYLOAD_FIELDS for part in payload["parts"]):
        raise ValueError("selector part payload does not describe complete units")

def selected_candidates(
    candidates: list[_ContextCandidate], selected_ids: list[int]
) -> list[_ContextCandidate]:
    """Resolve validated selector IDs back to their context candidates."""
    return [candidates[index] for index in selected_ids]

def local_selection(candidates: list[_ContextCandidate]) -> list[_ContextCandidate]:
    """Apply the runtime snippet and character limits to offline candidates."""
    snippets = _bound_context_snippets(
        [candidate.snippet for candidate in candidates],
        max_snippets=MAX_CONTEXT_SNIPPETS,
        max_chars=MAX_CONTEXT_CHARS,
    )
    selected_keys = {(snippet.path, snippet.key) for snippet in snippets}
    return [
        candidate
        for candidate in candidates
        if (candidate.snippet.path, candidate.snippet.key) in selected_keys
    ]
