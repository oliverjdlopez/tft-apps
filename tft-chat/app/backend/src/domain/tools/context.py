"""Complete collection access to curated repository reference context."""

from __future__ import annotations

from typing import Annotated

from agents import function_tool
from pydantic import BaseModel, ConfigDict, Field

from core.config import load_config
from domain.types import AssistantToolGroup


class AdditionalContextRequest(BaseModel):
    """A focused request for factual TFT reference material."""

    model_config = ConfigDict(extra="forbid")

    query: Annotated[
        str,
        Field(
            min_length=2,
            max_length=500,
            description=(
                "TFT question or collection to retrieve from curated reference "
                "sources, including full eligible pools, categories, units, traits, items, or mechanics."
            ),
        ),
    ]


def _context_provider():
    """Import the provider lazily to avoid the assistant/context import cycle."""
    from domain.providers.context import DEFAULT_CONTEXT_PROVIDER

    return DEFAULT_CONTEXT_PROVIDER


@function_tool(strict_mode=True)
async def request_additional_context(
    request: AdditionalContextRequest,
) -> dict[str, object]:
    """Retrieve complete relevant collections from curated TFT references.

    Use when the current conversation lacks a static gameplay fact needed to
    answer the user. Describe all factual needs, including the full comparison pool for odds or
    counts. Selected collections, including stage-specific Wisp groups, are returned
    in full for the configured set,
    without application truncation. This does not establish that the curated
    references document every game fact; never treat missing facts as absent
    from the game. Arbitrary local files are never accessible.
    """
    query = request.query.strip()
    provider = _context_provider()
    snippets = await provider.aselect(
        query,
        set_number=load_config().chat.set_number,
    )
    return {
        "query": query,
        "sources": [
            {
                "name": snippet.context_file,
                "path": snippet.path,
                "heading": snippet.heading,
            }
            for snippet in snippets
        ],
        "context": provider.render(snippets),
        "found": bool(snippets),
        "complete_selected_collections": True,
        "collection_count": len(snippets),
    }


CONTEXT_TOOL_GROUP = AssistantToolGroup(
    key="context",
    label="Reference Context",
    description="Complete curated TFT reference collections for the configured set.",
    tools=(request_additional_context,),
)


__all__ = [
    "AdditionalContextRequest",
    "CONTEXT_TOOL_GROUP",
    "request_additional_context",
]
