"""Data models for repository references, read catalogues, and skills."""

from typing import Any

from pydantic import BaseModel

class ContextBudgetExceeded(ValueError):
    """Signal that an explicit budget would omit complete selected context.

    This exception is raised by context selection and rendering helpers whenever
    a caller-provided limit cannot hold every selected collection.
    """


class ContextFile(BaseModel):
    """One repository-local Markdown or JSON context source loaded for routing.

    Attributes:
        name: Stable identity used in catalogues and read results.
        description: Semantic guidance used to route requests to this source.
        body: Complete source text, with Markdown frontmatter removed.
        path: Repository-relative display path for the original source.
        kind: Source category available to catalogue construction.
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
    """A complete reference collection and its discovery metadata.

    Attributes:
        snippet: Full content returned by an exact catalogue read.
        kind: Source category used in routing.
        description: Semantic summary used to distinguish source collections.
        part_type: Collection serialization format.
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
        body: Complete workflow instructions returned by an exact read.
        path: Repository-relative path to the source skill file.
    """

    name: str
    description: str
    body: str
    path: str
