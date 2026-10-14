"""Load repository skills and retain offline historical selection helpers."""

from __future__ import annotations


from domain.providers.constants import MAX_SELECTED_SKILLS, SKILLS_DIR
from domain.providers.models import SkillDefinition
from domain.providers.utils import (
    EXPLICIT_SKILL_RE,
    discover_skills,
    load_skill,
    render_skills,
    score_skill,
    selected_skill_ids,
    skill_selector_prompt,
    skill_tokens,
)

# Historical evaluation adapters retain these loading/serialization imports.
# Runtime assistant preparation uses discovery and exact catalogue reads.
_discover_skills = discover_skills
_load_skill = load_skill
_render_skills = render_skills


def select_skills(
    skills: list[SkillDefinition],
    query: str,
    *,
    max_skills: int = MAX_SELECTED_SKILLS,
) -> list[SkillDefinition]:
    """Select skills deterministically using explicit names and token overlap.

    Args:
        skills: Candidate skill definitions.
        query: Request text used to find applicable workflows.
        max_skills: Maximum number of workflows to return.

    Returns:
        Explicitly requested skill or the highest-scoring relevant candidates.
    """
    if max_skills <= 0 or not skills or not query.strip():
        return []

    explicit = EXPLICIT_SKILL_RE.search(query)
    if explicit:
        requested = explicit.group(1).casefold()
        return [skill for skill in skills if skill.name.casefold() == requested][:1]

    normalized_query = query.casefold()
    query_tokens = skill_tokens(normalized_query)
    ranked = [
        (score, skill)
        for skill in skills
        if (score := score_skill(skill, normalized_query, query_tokens)) >= 2
    ]
    ranked.sort(key=lambda item: (-item[0], item[1].name.casefold()))
    return [skill for _score_value, skill in ranked[:max_skills]]


__all__ = ["SkillDefinition", "discover_skills", "load_skill", "render_skills", "select_skills"]
