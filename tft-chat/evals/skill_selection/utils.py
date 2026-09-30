"""Selection benchmark helpers shared by the evaluation worker."""
from __future__ import annotations
import logging
from typing import Any
from domain.providers.skills import MAX_SELECTED_SKILLS, SkillDefinition

logger = logging.getLogger(__name__)

def names(skills: list[SkillDefinition]) -> list[str]:
    """Return discovered skill names for expectation normalization."""
    return [skill.name for skill in skills]

def ignore_unknown_skill_references(
    cases: list[dict[str, Any]], skills: list[SkillDefinition]
) -> list[dict[str, Any]]:
    """Remove unavailable skill expectations while retaining a diagnostic."""
    skill_names = set(names(skills))
    normalized_cases: list[dict[str, Any]] = []
    for case in cases:
        normalized = dict(case)
        required = case.get("required", [])
        forbidden = case.get("forbidden", [])
        if not isinstance(required, list) or not isinstance(forbidden, list):
            normalized_cases.append(normalized)
            continue

        unknown = (set(required) | set(forbidden)) - skill_names
        if unknown:
            logger.warning(
                "skill-selection case %r references unavailable skills; "
                "ignoring them: %s",
                case.get("name", ""),
                sorted(unknown),
            )
        normalized["required"] = [name for name in required if name in skill_names]
        normalized["forbidden"] = [name for name in forbidden if name in skill_names]
        normalized_cases.append(normalized)
    return normalized_cases

def validate_cases(
    cases: list[dict[str, Any]], skills: list[SkillDefinition]
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

        required = set(case.get("required", []))
        forbidden = set(case.get("forbidden", []))
        if required & forbidden:
            raise ValueError(f"case {name!r} requires and forbids the same skill")
        max_skills = int(case.get("max_skills", MAX_SELECTED_SKILLS))
        if not 1 <= max_skills <= MAX_SELECTED_SKILLS:
            raise ValueError(
                f"case {name!r} max_skills must be between 1 and "
                f"{MAX_SELECTED_SKILLS}"
            )
        if len(required) > max_skills:
            raise ValueError(
                f"case {name!r} requires more skills than its selection limit"
            )
        if case.get("expect_empty") and required:
            raise ValueError(f"empty case {name!r} cannot require skills")

def selection_metrics(
    selected: list[SkillDefinition], case: dict[str, Any]
) -> dict[str, Any]:
    """Measure required, forbidden and exact skill selection contracts."""
    selected_names = names(selected)
    selected_set = set(selected_names)
    required = set(case.get("required", []))
    forbidden = set(case.get("forbidden", []))
    required_hits = len(selected_set & required)
    forbidden_hits = len(selected_set & forbidden)
    exact_match = selected_set == required
    passed = (
        required_hits == len(required)
        and forbidden_hits == 0
        and (not case.get("expect_empty") or not selected_names)
        and (not case.get("exact") or exact_match)
    )
    return {
        "selected": selected_names,
        "selected_count": len(selected_names),
        "required_hits": required_hits,
        "required_count": len(required),
        "forbidden_hits": forbidden_hits,
        "exact_match": exact_match,
        "passed": passed,
    }
