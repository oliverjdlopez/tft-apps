"""Parsing, selection, and serialization helpers for prompt resource providers."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agents import Agent
from common.discoverers import discover_unique
from common.parsers import parse_frontmatter
from common.paths import display_path

from domain.providers.constants import (
    MAX_SELECTOR_CANDIDATES,
    MAX_SELECTOR_CHARS,
    ROOT_DIR,
    SKILLS_DIR,
)
from domain.providers.models import (
    ContextCandidate as _ContextCandidate,
    ContextBudgetExceeded,
    ContextFile,
    ContextSnippet,
    SkillDefinition,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context provider helpers
# Source parsing, complete collection preparation, and selector serialization.
# Complete source units are preserved throughout retrieval and fallback.
# ---------------------------------------------------------------------------


def parse_json_context_object(text: str, path: Path) -> dict[str, Any]:
    """Parse one JSON context source and reject duplicate object keys.

    Args:
        text: Raw JSON text read from the source file.
        path: Source path included in validation errors.

    Returns:
        The decoded top-level object.

    Raises:
        ValueError: JSON is malformed, has duplicate keys, or is not an object.
    """

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """Build an object while rejecting ambiguous duplicate keys.

        Args:
            pairs: Ordered key and value pairs from the JSON decoder.

        Returns:
            Decoded object preserving input key order.

        Raises:
            ValueError: A key appears more than once.
        """
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"JSON context file {path} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=object_pairs)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON context file {path}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON context file {path} must contain a top-level object")
    return value


_JSON_SET_DIR_RE = re.compile(r"^set[-_]?([0-9]+(?:\.[0-9]+)?)$", re.IGNORECASE)


def json_context_sets(path: Path, *, relative_to: Path) -> tuple[str, ...]:
    """Infer optional set scope from the nearest enclosing directory.

    Args:
        path: JSON source whose parent directories encode its scope.
        relative_to: Root used to constrain scope discovery.

    Returns:
        A one-element tuple containing the nearest set label, or an empty tuple.
    """
    try:
        relative_path = path.relative_to(relative_to)
    except ValueError:
        relative_path = path
    for directory in reversed(relative_path.parts[:-1]):
        match = _JSON_SET_DIR_RE.match(directory)
        if match:
            return (match.group(1),)
    return ()


def markdown_context_body(text: str) -> str:
    """Remove frontmatter while preserving the Markdown body verbatim.

    Args:
        text: Markdown source text.

    Returns:
        Source text after its leading frontmatter block, if present.
    """
    return re.sub(
        r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)",
        "", text, count=1, flags=re.DOTALL,
    )


def render_json_value(value: Any) -> str:
    """Render one decoded JSON value as a complete prompt injection unit.

    Args:
        value: JSON-compatible value from a context source.

    Returns:
        String values unchanged and other values as compact JSON.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def context_selector_agent() -> Agent[None]:
    """Build the context selector after provider modules finish loading.

    Returns:
        Selector agent configured from the canonical assistant registry.
    """
    from domain.assistants.constants import AssistantName
    from domain.assistants.models import ContextSelection
    from domain.assistants.registry import assistant_registry

    spec = assistant_registry.get_spec(AssistantName.CONTEXT_SELECTOR)
    return Agent(
        name=spec.name,
        instructions=spec.system_prompt,
        model=spec.resolved_model(),
        model_settings=spec.model_settings(),
        output_type=ContextSelection,
    )


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


_STOPWORDS = frozenset(
    {
        "about", "an", "and", "are", "as", "at", "be", "by", "can", "do",
        "does", "for", "from", "has", "have", "how", "if", "in", "into", "is",
        "it", "its", "not", "of", "on", "or", "that", "the", "their", "this",
        "to", "use", "vs", "what", "when", "where", "which", "with", "would",
        "you", "your",
    }
)


_LOW_SIGNAL_TOKENS = frozenset(
    {
        "analysis", "augment", "augments", "backline", "best", "better", "build",
        "carry", "champion", "champions", "comp", "composition", "context", "data",
        "emblem", "emblems", "frontline", "game", "item", "items", "player",
        "players", "report", "role", "roles", "set", "support", "tank", "tft",
        "trait", "traits", "unit", "units",
    }
)


def _normalize(value: str) -> str:
    """Normalize text before context fallback matching.

    Args:
        value: Text to case-fold and normalize into word tokens.

    Returns:
        Normalized text with punctuation collapsed to single spaces.
    """
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[.'’]", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _tokens(value: str) -> set[str]:
    """Extract significant words for context fallback ranking.

    Args:
        value: Source or query text to tokenize.

    Returns:
        Tokens after normalization and common-word filtering.
    """
    return {
        token
        for token in _TOKEN_RE.findall(_normalize(value))
        if (len(token) > 1 or token.isdigit()) and token not in _STOPWORDS
    }


def _contains_phrase(query: str, phrase: str) -> bool:
    """Check whether a normalized phrase appears as a complete phrase.

    Args:
        query: Normalized request text.
        phrase: Normalized candidate phrase.

    Returns:
        Whether the phrase occurs with token boundaries in the query.
    """
    return bool(phrase) and f" {phrase} " in f" {query} "


def _label_aliases(label: str) -> tuple[str, ...]:
    """Derive compact aliases for compound labels during local selection.

    Args:
        label: Human-readable source or entry label.

    Returns:
        Recognized abbreviation aliases, if the label has multiple words.
    """
    words = _normalize(label).split()
    aliases: list[str] = []
    if len(words) > 1:
        initial_last = words[0][0] + words[-1]
        if len(initial_last) >= 3:
            aliases.append(initial_last)
    return tuple(aliases)


def _set_key(value: int | str | None) -> str:
    """Normalize set labels before repository context filtering.

    Args:
        value: Numeric or textual set label.

    Returns:
        Normalized label without a leading ``set`` or trailing ``.0``.
    """
    return _normalize(str(value or "")).removeprefix("set ").removesuffix(" 0")


def inherit_collection_descriptions(sources: Sequence[ContextFile]) -> list[ContextFile]:
    """Give JSON companions Markdown routing metadata without merging facts.

    Args:
        sources: Discovered Markdown and JSON sources.

    Returns:
        Sources where same-stem JSON companions inherit description and kind.
    """
    markdown = {
        Path(source.path).with_suffix(""): source
        for source in sources if source.format == "markdown"
    }
    result: list[ContextFile] = []
    for source in sources:
        companion = markdown.get(Path(source.path).with_suffix(""))
        if source.format == "json" and companion is not None:
            source = source.model_copy(update={
                "description": companion.description, "kind": companion.kind,
            })
        result.append(source)
    return result


_WISP_CATEGORY_STEMS = frozenset({
    "wisps-champion", "wisps-combat", "wisps-goldxp", "wisps-item",
    "wisps-misc", "wisps-risky", "wisps-shop",
})
_WISP_WINDOW = re.compile(r"(\d+)-(\d+)\s*[–—-]\s*(\d+)-(\d+)")


def wisp_entry_stages(text: str) -> tuple[int | str, ...]:
    """Find every stage intersecting an entry's explicit offer windows.

    Args:
        text: Complete entry text containing an explicit offer-window label.

    Returns:
        Sorted intersecting stages, ``("all",)`` for an unrestricted band, or
        an empty tuple when the window cannot be interpreted completely.
    """
    match = re.search(r"offer windows\s+([^;\n]+)", text, flags=re.IGNORECASE)
    if match is None:
        return ()
    if match.group(1).strip().casefold() == "all bands (no round-band tag)":
        return ("all",)
    stages: set[int] = set()
    for window in match.group(1).split(","):
        parsed = _WISP_WINDOW.fullmatch(window.strip())
        if parsed is None:
            return ()
        start_stage, start_round, end_stage, end_round = map(int, parsed.groups())
        if start_stage < 1 or start_round < 1 or end_round < 1 or (
            start_stage, start_round
        ) > (end_stage, end_round):
            return ()
        stages.update(range(start_stage, end_stage + 1))
    return tuple(sorted(stages))


def wisp_stage_candidates(source: ContextFile) -> list[_ContextCandidate] | None:
    """Partition a Wisp category into complete, overlapping stage collections.

    General rules stay whole. Multi-stage entries appear in each matching stage;
    their text, conditions, modes, and variant identity remain unchanged. Unknown
    formats return None so the caller preserves the entire original source.

    Args:
        source: Context collection to inspect for known Wisp categories.

    Returns:
        Complete stage candidates, or ``None`` when the source should stay whole.
    """
    if Path(source.path).stem not in _WISP_CATEGORY_STEMS:
        return None
    preamble = ""
    if source.format == "json":
        entries = list(source.json_values)
        if any(not isinstance(value, str) for _, value in entries):
            return None
    else:
        # Split only the known top-level named-entry format, keeping continuation
        # lines in the same entry and retaining the shared factual introduction.
        starts = list(re.finditer(r"(?m)^- \*\*(.+?)\*\*", source.body))
        if not starts:
            return None
        preamble = source.body[:starts[0].start()]
        entries = [
            (match.group(1), source.body[match.start():
                starts[index + 1].start() if index + 1 < len(starts) else len(source.body)])
            for index, match in enumerate(starts)
        ]
    memberships = [wisp_entry_stages(value) for _, value in entries]
    if not entries or any(not stages for stages in memberships):
        return None
    candidates: list[_ContextCandidate] = []
    stage_keys = {stage for stages in memberships for stage in stages}
    ordered_stages: list[int | str] = sorted(stage for stage in stage_keys if isinstance(stage, int))
    if "all" in stage_keys:
        ordered_stages.append("all")
    for stage in ordered_stages:
        selected = [(name, value) for (name, value), stages in zip(entries, memberships)
                    if stage in stages]
        content = (json.dumps(dict(selected), ensure_ascii=False, indent=2)
                   if source.format == "json"
                   else preamble + "".join(value for _, value in selected))
        heading = "All stages" if stage == "all" else f"Stage {stage}"
        candidates.append(_ContextCandidate(
            snippet=ContextSnippet(
                context_file=source.name, path=source.path, heading=heading,
                content=content, line=1, score=0, key=f"stage-{stage}",
            ),
            kind=source.kind,
            description=source.description,
            part_type="json_collection" if source.format == "json" else "markdown_file",
            title=f"{source.name} — {heading}",
        ))
    return candidates


def all_context_candidates(
    context_files: Sequence[ContextFile], *, set_number: int | None
) -> list[_ContextCandidate]:
    """Expose every eligible collection, using explicit stage chunks for Wisps.

    Markdown and JSON companions remain separate sources: their contents may
    diverge, so a matching basename is not sufficient evidence to discard one.

    Args:
        context_files: Discovered context sources to expose.
        set_number: Optional set restriction applied before candidate creation.

    Returns:
        All complete eligible collections offered to the selector.
    """
    requested_set = _set_key(set_number)
    candidates: list[_ContextCandidate] = []
    for source in context_files:
        if requested_set and source.sets and requested_set not in {
            _set_key(value) for value in source.sets
        }:
            continue
        if source.format == "json" and not source.json_values:
            continue
        stage_candidates = wisp_stage_candidates(source)
        if stage_candidates is not None:
            candidates.extend(stage_candidates)
            continue
        candidates.append(_ContextCandidate(
            snippet=ContextSnippet(
                context_file=source.name, path=source.path, heading="",
                content=source.body, line=1, score=0,
            ),
            kind=source.kind, description=source.description,
            part_type="json_collection" if source.format == "json" else "markdown_file",
            title=source.name,
        ))
    return candidates


def rank_context_candidates(
    context_files: Sequence[ContextFile], query: str, *, set_number: int | None,
) -> list[_ContextCandidate]:
    """Order complete units by lexical relevance for fallback selection.

    Args:
        context_files: Candidate source catalogue.
        query: Request text used to calculate lexical relevance.
        set_number: Optional set restriction applied before ranking.

    Returns:
        Matching source candidates ordered by descending relevance.
    """
    normalized_query = _normalize(query)
    query_tokens = _tokens(query)
    ranked: list[_ContextCandidate] = []
    for candidate in all_context_candidates(context_files, set_number=set_number):
        snippet = candidate.snippet
        overlap = query_tokens & (_tokens(candidate.title) | _tokens(snippet.content)
                                  | _tokens(candidate.description) | _tokens(snippet.path))
        score = len(overlap - _LOW_SIGNAL_TOKENS) * 8
        if _contains_phrase(normalized_query, _normalize(candidate.title)):
            score += 100
        # Keep common champion abbreviations useful offline without constructing
        # a separate entity/alias descriptor graph for every candidate.
        names = [candidate.title, *_BOLD_RE.findall(snippet.content)]
        if any(alias in query_tokens for name in names for alias in _label_aliases(name)):
            score += 80
        if score:
            ranked.append(candidate.model_copy(update={
                "snippet": snippet.model_copy(update={"score": score}),
            }))
    return sorted(ranked, key=lambda candidate: (
        -candidate.snippet.score, candidate.snippet.path, candidate.snippet.line,
    ))


def bound_context_snippets(
    snippets: Sequence[ContextSnippet],
    *,
    max_snippets: int | None,
    max_chars: int | None,
) -> list[ContextSnippet]:
    """Return complete collections or explicitly reject caller-supplied limits.

    Defaults impose no application budget. Never silently turn a complete pool
    into a partial pool: callers computing probabilities need its denominator.

    Args:
        snippets: Complete collections selected by a selector or ranker.
        max_snippets: Optional maximum number of selected collections.
        max_chars: Optional maximum length of rendered context.

    Returns:
        The unchanged complete collection list.

    Raises:
        ContextBudgetExceeded: The selected result exceeds an explicit limit.
    """
    selected = list(snippets)
    total_chars = len(render_context_for_budget(selected))
    if ((max_snippets is not None and len(selected) > max_snippets)
            or (max_chars is not None and total_chars > max_chars)):
        raise ContextBudgetExceeded(
            f"Complete context requires {len(selected)} collections and "
            f"{total_chars} characters; requested limits cannot include it."
        )
    return selected


def render_context_for_budget(snippets: Sequence[ContextSnippet]) -> str:
    """Render context for accurate budget accounting, including source labels.

    Args:
        snippets: Complete context collections to measure.

    Returns:
        The same text that will be injected into the assistant prompt.
    """
    from domain.providers.context import render_context_files

    return render_context_files(snippets)


def collection_catalogue_entry(candidate: _ContextCandidate) -> dict[str, object]:
    """Describe a source without letting long bodies crowd out other sources.

    All entry names are retained. Sources without structural headings or entry
    names retain their body as routing evidence rather than disappearing.

    Args:
        candidate: Complete source collection offered to the selector.

    Returns:
        JSON-compatible headings, entry names, and routing evidence.
    """
    body = candidate.snippet.content
    if candidate.part_type == "json_collection":
        entries = list(json.loads(body))
        headings: list[str] = []
    else:
        entries = list(dict.fromkeys(_BOLD_RE.findall(body)))
        headings = re.findall(r"^#{1,6}\s+(.+)$", body, flags=re.MULTILINE)
    return {
        "headings": headings, "entries": entries,
        "stage": candidate.snippet.heading if candidate.snippet.key and candidate.snippet.key.startswith("stage-") else None,
        "unstructured_reference": body if (not entries or
            candidate.description.startswith("JSON context from ")) else "",
    }


def context_selector_prompt(
    query: str, candidates: Sequence[_ContextCandidate], *, max_selected: int | None
) -> str:
    """Serialize source descriptors and complete options for the selector.

    Args:
        query: Request text that the selector must satisfy.
        candidates: Complete collections available for selection.
        max_selected: Optional maximum number of collections to select.

    Returns:
        JSON prompt payload containing source and part descriptors.
    """
    sources: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        source_id = candidate.snippet.context_file
        sources.setdefault(
            source_id,
            {
                "id": source_id,
                "path": candidate.snippet.path,
                "kind": candidate.kind,
                "description": candidate.description,
            },
        )

    return json.dumps(
        {
            "query": query,
            "max_selected": max_selected,
            "sources": list(sources.values()),
            "parts": [
                {
                    "id": index,
                    "source_id": candidate.snippet.context_file,
                    "type": candidate.part_type,
                    "title": candidate.title,
                    "key": candidate.snippet.key,
                    "section_path": candidate.snippet.heading,
                    "catalogue": collection_catalogue_entry(candidate),
                }
                for index, candidate in enumerate(candidates)
            ],
        },
        ensure_ascii=False,
    )


def shortlist_context_candidates(
    context_files: Sequence[ContextFile],
    query: str,
    *,
    set_number: int | None,
    max_selected: int | None,
    max_candidates: int | None = MAX_SELECTOR_CANDIDATES,
    max_chars: int | None = MAX_SELECTOR_CHARS,
) -> list[_ContextCandidate]:
    """Offer the complete source catalogue without lexical prefiltering.

    The legacy name remains for evaluation callers. Explicit limits fail
    visibly instead of removing options before the selector can inspect them.

    Args:
        context_files: Full discovered source catalogue.
        query: Request text supplied to the selector.
        set_number: Optional set restriction.
        max_selected: Optional selector output limit.
        max_candidates: Optional catalogue size limit.
        max_chars: Optional serialized prompt size limit.

    Returns:
        All eligible candidates, without lexical prefiltering.

    Raises:
        ContextBudgetExceeded: An explicit limit cannot hold the full catalogue.
    """
    candidates = all_context_candidates(context_files, set_number=set_number)
    if ((max_candidates is not None and len(candidates) > max_candidates)
            or (max_chars is not None and len(context_selector_prompt(
                query, candidates, max_selected=max_selected)) > max_chars)):
        raise ContextBudgetExceeded("Requested limit cannot include the complete context catalogue")
    return candidates


def selected_context_ids(
    output: str | CandidateIdSelection | ContextSelection,
    *,
    candidate_count: int,
    max_selected: int | None,
) -> list[int]:
    """Decode, validate, and deduplicate selector candidate IDs.

    Args:
        output: Selector output as a structured model or encoded text.
        candidate_count: Number of valid candidate positions.
        max_selected: Optional maximum permitted selection count.

    Returns:
        Valid unique candidate indices in selector order.

    Raises:
        ContextBudgetExceeded: The selector exceeded an explicit selection cap.
    """
    from domain.assistants.models import CandidateIdSelection, ContextSelection

    if isinstance(output, ContextSelection):
        decoded: object = [
            candidate_id
            for selection in output.selections
            for candidate_id in selection.part_ids
        ]
    elif isinstance(output, CandidateIdSelection):
        decoded: object = output.selected_ids
    else:
        text = output.strip()
        if text.startswith("```"):
            text = re.sub(r"\A```(?:json)?\s*|\s*```\Z", "", text, flags=re.I)
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            decoded = [part for part in re.split(r"[,\s]+", text) if part]
    if isinstance(decoded, dict):
        if isinstance(decoded.get("selections"), list):
            grouped_ids: list[object] = []
            for selection in decoded["selections"]:
                if not isinstance(selection, dict):
                    continue
                part_ids = selection.get(
                    "part_ids", selection.get("candidate_ids", [])
                )
                if isinstance(part_ids, list):
                    grouped_ids.extend(part_ids)
            decoded = grouped_ids
        else:
            decoded = decoded.get("selected_ids", decoded.get("ids", []))
    if not isinstance(decoded, list):
        return []

    selected: list[int] = []
    for value in decoded:
        try:
            candidate_id = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= candidate_id < candidate_count and candidate_id not in selected:
            selected.append(candidate_id)
        if max_selected is not None and len(selected) > max_selected:
            raise ContextBudgetExceeded("Selected collections exceed the explicit context limit")
    return selected


# ---------------------------------------------------------------------------
# Skill provider helpers
# Skill files are loaded as complete workflows and selected by request intent.
# Selector setup imports assistant registry modules lazily to avoid cycles.
# ---------------------------------------------------------------------------

_SKILL_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SKILL_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SKILL_DESCRIPTION_EXCLUSION_RE = re.compile(
    r"\b(?:do not use|not for|excludes?)\b", re.I
)
EXPLICIT_SKILL_RE = re.compile(
    r"(?:\A|\s)(?:skill:|/skill\s+)([a-z0-9][a-z0-9_-]*)", re.I
)
_SKILL_STOPWORDS = frozenset(
    {
        "about", "analysis", "analyze", "and", "are", "current", "data",
        "for", "from", "how", "into", "that", "the", "this", "tft", "use",
        "what", "when", "where", "which", "with", "would", "you",
    }
)


def skill_selector_agent() -> Agent[None]:
    """Build the skill selector after provider modules finish loading.

    Returns:
        Selector agent configured from the canonical assistant registry.
    """
    from domain.assistants.constants import AssistantName
    from domain.assistants.models import CandidateIdSelection
    from domain.assistants.registry import assistant_registry

    spec = assistant_registry.get_spec(AssistantName.SKILL_SELECTOR)
    return Agent(
        name=spec.name,
        instructions=spec.system_prompt,
        model=spec.resolved_model(),
        model_settings=spec.model_settings(),
        output_type=CandidateIdSelection,
    )


def load_skill(path: Path, *, relative_to: Path | None = None) -> SkillDefinition:
    """Load and validate one repository-local ``SKILL.md`` file.

    Args:
        path: Skill file to read and validate.
        relative_to: Root used to produce the source display path.

    Returns:
        Parsed skill metadata and complete workflow instructions.

    Raises:
        ValueError: Required protocol metadata or skill content is invalid.
    """
    text = path.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    metadata = parsed.metadata
    body = parsed.body

    name = metadata.get("name", path.parent.name).strip()
    description = metadata.get("description", "").strip()
    if not name:
        raise ValueError(f"Skill at {path} has no name")
    if not description:
        raise ValueError(f"Skill {name!r} has no description")
    if len(name) > 64 or not _SKILL_NAME_RE.fullmatch(name):
        raise ValueError(f"Skill name {name!r} does not follow the Agent Skills format")
    if name != path.parent.name:
        raise ValueError(
            f"Skill name {name!r} must match its parent directory {path.parent.name!r}"
        )
    if len(description) > 1_024:
        raise ValueError(f"Skill {name!r} description exceeds 1024 characters")
    if not body.strip():
        raise ValueError(f"Skill {name!r} has no instructions")

    return SkillDefinition(
        name=name,
        description=description,
        body=body.strip(),
        path=display_path(path, relative_to=relative_to or ROOT_DIR),
    )


def discover_skills(
    skills_dir: Path | None = None,
    *,
    relative_to: Path | None = None,
) -> list[SkillDefinition]:
    """Discover unique direct-child skill files below a repository root.

    Args:
        skills_dir: Directory containing skill subdirectories.
        relative_to: Root used to produce source display paths.

    Returns:
        Valid unique skills, with invalid files logged and skipped.
    """
    root = skills_dir or SKILLS_DIR
    source_root = relative_to or (ROOT_DIR if skills_dir is None else root)
    return discover_unique(
        root,
        ["*/SKILL.md"],
        lambda path: load_skill(path, relative_to=source_root),
        identity=lambda skill: skill.name.casefold(),
        on_error=lambda path, exc: logger.warning(
            "ignoring invalid local skill path=%s error=%s", path, exc
        ),
        on_duplicate=lambda path, skill: logger.warning(
            "ignoring duplicate local skill name=%s path=%s", skill.name, path
        ),
    )


def skill_tokens(value: str) -> set[str]:
    """Extract meaningful words for deterministic skill matching.

    Args:
        value: Skill name, description, or request text.

    Returns:
        Lowercase words longer than two characters, excluding common terms.
    """
    return {
        token
        for token in _SKILL_TOKEN_RE.findall(value.casefold())
        if len(token) > 2 and token not in _SKILL_STOPWORDS
    }


def score_skill(skill: SkillDefinition, query: str, query_tokens: set[str]) -> int:
    """Score one skill against a normalized request for local fallback.

    Args:
        skill: Candidate skill being evaluated.
        query: Case-folded request text.
        query_tokens: Significant request tokens computed once for the ranking.

    Returns:
        Integer relevance score, with stronger weight for skill-name matches.
    """
    name_as_phrase = re.sub(r"[-_]", " ", skill.name.casefold())
    name_tokens = skill_tokens(name_as_phrase)
    positive_description = _SKILL_DESCRIPTION_EXCLUSION_RE.split(
        skill.description, maxsplit=1
    )[0]
    description_tokens = skill_tokens(positive_description)

    score = 0
    if name_as_phrase and name_as_phrase in query:
        score += 12
    score += 5 * len(query_tokens & name_tokens)
    score += 2 * len(query_tokens & description_tokens)
    return score


def render_skills(skills: Sequence[SkillDefinition]) -> str:
    """Render complete selected workflows as supplemental instructions.

    Args:
        skills: Selected repository skills to inject.

    Returns:
        Delimited assistant instructions, or an empty string when no skills were
        selected.
    """
    selected = list(skills)
    if not selected:
        return ""

    parts = [
        "## Local skills selected for this turn",
        "Follow the relevant instructions below. They supplement the base assistant instructions.",
    ]
    for skill in selected:
        parts.extend(
            [
                "",
                f"### Skill: {skill.name}",
                "",
                f"Description: {skill.description}",
                "",
                "<skill_instructions>",
                skill.body,
                "</skill_instructions>",
            ]
        )
    return "\n".join(parts)


def skill_selector_prompt(
    query: str, skills: Sequence[SkillDefinition], *, max_selected: int
) -> str:
    """Serialize candidate IDs and descriptions for model-based selection.

    Args:
        query: Request text the selector must satisfy.
        skills: Allowed candidate skills.
        max_selected: Maximum number of skills the selector may return.

    Returns:
        JSON prompt payload containing the query and candidate descriptors.
    """
    return json.dumps(
        {
            "query": query,
            "max_selected": max_selected,
            "candidates": [
                {
                    "id": index,
                    "name": skill.name,
                    "description": skill.description,
                }
                for index, skill in enumerate(skills)
            ],
        },
        ensure_ascii=False,
    )


def selected_skill_ids(
    output: str | CandidateIdSelection,
    *,
    candidate_count: int,
    max_selected: int,
) -> list[int]:
    """Decode and validate bounded candidate IDs from selector output.

    Args:
        output: Structured selector result or its textual representation.
        candidate_count: Number of available candidate positions.
        max_selected: Maximum number of candidate IDs to return.

    Returns:
        Valid unique candidate indices in selector order.
    """
    from domain.assistants.models import CandidateIdSelection

    if isinstance(output, CandidateIdSelection):
        decoded: object = output.selected_ids
    else:
        text = output.strip()
        if text.startswith("```"):
            text = re.sub(r"\A```(?:json)?\s*|\s*```\Z", "", text, flags=re.I)
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            decoded = [part for part in re.split(r"[,\s]+", text) if part]
    if isinstance(decoded, dict):
        decoded = decoded.get("selected_ids", decoded.get("ids", []))
    if not isinstance(decoded, list):
        return []

    selected: list[int] = []
    for value in decoded:
        try:
            candidate_id = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= candidate_id < candidate_count and candidate_id not in selected:
            selected.append(candidate_id)
        if len(selected) >= max_selected:
            break
    return selected


# Legacy helper names remain importable for evaluation adapters that patch or
# inspect the selector pipeline; their implementations are defined above.
_selector_agent = context_selector_agent
_all_context_candidates = all_context_candidates
_rank_context_candidates = rank_context_candidates
_bound_context_snippets = bound_context_snippets
_context_selector_prompt = context_selector_prompt
_shortlist_context_candidates = shortlist_context_candidates
_selected_context_ids = selected_context_ids
