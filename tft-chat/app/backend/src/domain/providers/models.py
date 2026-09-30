"""Shared data models and provider protocols for repository prompt resources."""

from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel

from common.protocols import Provider
from domain.providers.constants import (
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_SNIPPETS,
    MAX_SELECTED_SKILLS,
)


class ContextBudgetExceeded(ValueError):
    """Signal that an explicit budget would omit complete selected context.

    This exception is raised by context selection and rendering helpers whenever
    a caller-provided limit cannot hold every selected collection.
    """


class ContextFile(BaseModel):
    """One repository-local Markdown or JSON context source loaded for routing.

    Attributes:
        name: Stable identity used by selectors and rendered references.
        description: Semantic guidance used to route requests to this source.
        body: Complete source text, with Markdown frontmatter removed.
        path: Repository-relative display path for the original source.
        kind: Source category exposed to the context selector.
        sets: Set labels for which the source is eligible.
        format: Source encoding, either Markdown or JSON.
        json_values: Parsed top-level JSON entries retained as complete values.
    """

    name: str
    description: str
    body: str
    path: str
    kind: str = "reference"
    sets: tuple[str, ...] = ()
    format: str = "markdown"
    json_values: tuple[tuple[str, Any], ...] = ()


class ContextSnippet(BaseModel):
    """One complete source collection or stage chunk selected for a request.

    Attributes:
        context_file: Stable source identity displayed to the assistant.
        path: Repository-relative source path.
        heading: Optional heading identifying a derived stage chunk.
        content: Complete selected reference content.
        line: Source line associated with the selected content.
        score: Local lexical relevance score, or zero for model selection.
        key: Optional stable key for a derived collection such as a stage chunk.
    """

    context_file: str
    path: str
    heading: str = ""
    content: str
    line: int
    score: int
    key: str | None = None


class ContextCandidate(BaseModel):
    """A complete context unit and descriptors offered to the selector.

    Attributes:
        snippet: Full content that can be selected and injected.
        kind: Source category used in routing.
        description: Semantic summary used to distinguish source collections.
        part_type: Serialization format presented to the selector.
        title: Human-readable collection name used for ranking and display.
    """

    snippet: ContextSnippet
    kind: str
    description: str
    part_type: str
    title: str


class SkillDefinition(BaseModel):
    """One complete repository-local skill available to an assistant.

    Attributes:
        name: Protocol-compatible skill identity matching its directory.
        description: Routing guidance from the skill frontmatter.
        body: Complete workflow instructions injected when selected.
        path: Repository-relative path to the source skill file.
    """

    name: str
    description: str
    body: str
    path: str


class ContextProvider(Provider[ContextFile, ContextSnippet], Protocol):
    """Lifecycle contract for selecting and rendering factual context."""

    def select(
        self,
        query: str,
        *,
        set_number: int | None = None,
        max_snippets: int | None = MAX_CONTEXT_SNIPPETS,
        max_chars: int | None = MAX_CONTEXT_CHARS,
    ) -> list[ContextSnippet]:
        """Select complete reference collections synchronously.

        Args:
            query: Request text used to select context.
            set_number: Optional set restriction.
            max_snippets: Optional maximum collection count.
            max_chars: Optional maximum rendered context length.

        Returns:
            Selected complete context collections.
        """
        ...

    async def aselect(
        self,
        query: str,
        *,
        set_number: int | None = None,
        max_snippets: int | None = MAX_CONTEXT_SNIPPETS,
        max_chars: int | None = MAX_CONTEXT_CHARS,
    ) -> list[ContextSnippet]:
        """Select complete reference collections asynchronously.

        Args:
            query: Request text used to select context.
            set_number: Optional set restriction.
            max_snippets: Optional maximum collection count.
            max_chars: Optional maximum rendered context length.

        Returns:
            Selected complete context collections.
        """
        ...

    def render(self, context_files: Sequence[ContextSnippet]) -> str:
        """Render selected context as an assistant-facing reference block.

        Args:
            context_files: Complete selected context collections.

        Returns:
            Formatted reference text.
        """
        ...

    def select_and_render(
        self,
        query: str,
        *,
        set_number: int | None = None,
        max_snippets: int | None = MAX_CONTEXT_SNIPPETS,
        max_chars: int | None = MAX_CONTEXT_CHARS,
    ) -> str:
        """Select context and render it as one reference block.

        Args:
            query: Request text used to select context.
            set_number: Optional set restriction.
            max_snippets: Optional maximum collection count.
            max_chars: Optional maximum rendered context length.

        Returns:
            Formatted selected context.
        """
        ...


class SkillProvider(Provider[SkillDefinition, SkillDefinition], Protocol):
    """Lifecycle contract for selecting and rendering assistant playbooks."""

    def select(
        self,
        query: str,
        *,
        max_skills: int = MAX_SELECTED_SKILLS,
        allowed_names: Sequence[str] | None = None,
    ) -> list[SkillDefinition]:
        """Select allowed skills synchronously for a request.

        Args:
            query: Request text used to select skills.
            max_skills: Maximum number of workflows to return.
            allowed_names: Optional skill-name allowlist.

        Returns:
            Selected complete skill definitions.
        """
        ...

    async def aselect(
        self,
        query: str,
        *,
        max_skills: int = MAX_SELECTED_SKILLS,
        allowed_names: Sequence[str] | None = None,
    ) -> list[SkillDefinition]:
        """Select allowed skills asynchronously for a request.

        Args:
            query: Request text used to select skills.
            max_skills: Maximum number of workflows to return.
            allowed_names: Optional skill-name allowlist.

        Returns:
            Selected complete skill definitions.
        """
        ...

    def render(self, skills: Sequence[SkillDefinition]) -> str:
        """Render selected skills as supplemental assistant instructions.

        Args:
            skills: Complete selected skill workflows.

        Returns:
            Formatted supplemental instructions.
        """
        ...

    def select_and_render(
        self,
        query: str,
        *,
        max_skills: int = MAX_SELECTED_SKILLS,
    ) -> str:
        """Select skills and render their instructions.

        Args:
            query: Request text used to select skills.
            max_skills: Maximum number of workflows to return.

        Returns:
            Formatted selected skills.
        """
        ...


__all__ = ["ContextCandidate", "ContextFile", "ContextProvider", "ContextSnippet", "SkillDefinition", "SkillProvider"]
