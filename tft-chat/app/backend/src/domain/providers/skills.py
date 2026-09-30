"""Discover, select, and render repository-local assistant playbooks."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from agents import Runner
from core.config import load_config
from domain.providers.constants import MAX_SELECTED_SKILLS, ROOT_DIR, SKILLS_DIR
from domain.providers.models import SkillDefinition, SkillProvider
from domain.providers.utils import (
    EXPLICIT_SKILL_RE,
    discover_skills,
    load_skill,
    render_skills,
    score_skill,
    selected_skill_ids,
    skill_selector_agent,
    skill_selector_prompt,
    skill_tokens,
)

logger = logging.getLogger(__name__)

# Preserve imports used by evaluation adapters and selector test seams. The
# helper implementations themselves are centralized in ``utils.py``.
_discover_skills = discover_skills
_load_skill = load_skill
_render_skills = render_skills
_selector_agent = skill_selector_agent


class RepositorySkillProvider(SkillProvider):
    """Provide task-relevant skills from repository ``SKILL.md`` files."""

    def __init__(
        self,
        skills_dir: Path = SKILLS_DIR,
        *,
        relative_to: Path | None = None,
    ) -> None:
        """Configure skill discovery and load the available definitions.

        Args:
            skills_dir: Directory containing skill subdirectories.
            relative_to: Optional root used to display skill source paths.
        """
        self._skills_dir = skills_dir
        self._relative_to = relative_to or (
            ROOT_DIR if skills_dir == SKILLS_DIR else skills_dir
        )
        self._skills = self.discover()

    def load(self, path: Path, *, relative_to: Path | None = None) -> SkillDefinition:
        """Load and validate one skill file.

        Args:
            path: Skill file to load.
            relative_to: Optional display-path root override.

        Returns:
            Validated skill definition.
        """
        return _load_skill(path, relative_to=relative_to or self._relative_to)

    def discover(self) -> list[SkillDefinition]:
        """Return unique valid skills in the configured directory.

        Returns:
            Discovered repository skill definitions.
        """
        return _discover_skills(self._skills_dir, relative_to=self._relative_to)

    def select(
        self,
        query: str,
        *,
        max_skills: int = MAX_SELECTED_SKILLS,
        allowed_names: Sequence[str] | None = None,
    ) -> list[SkillDefinition]:
        """Select relevant skills from the caller's allowed candidate set.

        Args:
            query: Request text used to select skills.
            max_skills: Maximum number of workflows to return.
            allowed_names: Optional name allowlist; ``None`` allows all skills.

        Returns:
            Relevant allowed skills, ordered by selection priority.
        """
        if max_skills <= 0 or not query.strip():
            return []
        allowed = None if allowed_names is None else set(allowed_names)
        skills = [
            skill for skill in self._skills if allowed is None or skill.name in allowed
        ]
        explicit = EXPLICIT_SKILL_RE.search(query)
        if explicit:
            requested = explicit.group(1).casefold()
            return [skill for skill in skills if skill.name.casefold() == requested][:1]
        try:
            if load_config().secrets.openai_api_key:
                result = Runner.run_sync(
                    _selector_agent(),
                    skill_selector_prompt(query, skills, max_selected=max_skills),
                    max_turns=1,
                )
                return [
                    skills[index]
                    for index in selected_skill_ids(
                        result.final_output,
                        candidate_count=len(skills),
                        max_selected=max_skills,
                    )
                ]
        except Exception:  # pragma: no cover - provider must remain available offline
            logger.exception("skill selector failed; using local selection")
        return select_skills(skills, query, max_skills=max_skills)

    def render(self, skills: Sequence[SkillDefinition]) -> str:
        """Render selected skills as supplemental assistant instructions.

        Args:
            skills: Complete skill workflows selected for the request.

        Returns:
            Delimited instructions for the assistant prompt.
        """
        return _render_skills(skills)

    async def aselect(
        self,
        query: str,
        *,
        max_skills: int = MAX_SELECTED_SKILLS,
        allowed_names: Sequence[str] | None = None,
    ) -> list[SkillDefinition]:
        """Select skills asynchronously from the caller's allowed candidates.

        Args:
            query: Request text used to select skills.
            max_skills: Maximum number of workflows to return.
            allowed_names: Optional name allowlist; ``None`` allows all skills.

        Returns:
            Relevant allowed skills, ordered by selection priority.
        """
        if max_skills <= 0 or not query.strip():
            return []
        allowed = None if allowed_names is None else set(allowed_names)
        skills = [
            skill for skill in self._skills if allowed is None or skill.name in allowed
        ]
        explicit = EXPLICIT_SKILL_RE.search(query)
        if explicit:
            requested = explicit.group(1).casefold()
            return [skill for skill in skills if skill.name.casefold() == requested][:1]
        try:
            if load_config().secrets.openai_api_key:
                result = await Runner.run(
                    _selector_agent(),
                    skill_selector_prompt(query, skills, max_selected=max_skills),
                    max_turns=1,
                )
                return [
                    skills[index]
                    for index in selected_skill_ids(
                        result.final_output,
                        candidate_count=len(skills),
                        max_selected=max_skills,
                    )
                ]
        except Exception:  # pragma: no cover - provider must remain available offline
            logger.exception("skill selector failed; using local selection")
        return select_skills(skills, query, max_skills=max_skills)

    def select_and_render(
        self,
        query: str,
        *,
        max_skills: int = MAX_SELECTED_SKILLS,
    ) -> str:
        """Select skills and return their formatted assistant instructions.

        Args:
            query: Request text used to select skills.
            max_skills: Maximum number of workflows to return.

        Returns:
            Rendered selected skills, or an empty string when none match.
        """
        return self.render(self.select(query, max_skills=max_skills))


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


DEFAULT_SKILL_PROVIDER = RepositorySkillProvider()


__all__ = [
    "DEFAULT_SKILL_PROVIDER",
    "MAX_SELECTED_SKILLS",
    "SKILLS_DIR",
    "RepositorySkillProvider",
    "SkillDefinition",
    "SkillProvider",
    "_discover_skills",
    "_load_skill",
    "_render_skills",
    "select_skills",
]
