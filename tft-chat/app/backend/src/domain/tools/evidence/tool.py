"""Let responding assistants select an initial view of backend-owned evidence."""

from typing import Any
from agents import function_tool
from agents.tool_context import ToolContext
from domain.types import AssistantToolGroup
from .models import DisplaySpec
from .utils import resolve_evidence_store, resolve_presentation


@function_tool(strict_mode=True)
async def present_evidence(
    ctx: ToolContext[Any], request: DisplaySpec
) -> dict[str, object]:
    """Choose a static table, distribution, or interactive table by evidence reference.

    Use only evidence references returned during this invocation. Values, units,
    row identity, and source context are resolved on the backend, not supplied
    by the assistant. Comparison summary tables must show cohort and boards;
    grouped cohort tables must show every grouping dimension and distinct_boards.
    Leave table options empty for a distribution.
    """
    store = resolve_evidence_store(ctx.context)
    if store is None:
        return {
            "error": "Evidence presentation is unavailable on this execution surface; "
            "use concise prose or a compact Markdown table with verified values."
        }
    try:
        presentation = resolve_presentation(store, request, ctx.tool_call_id)
    except ValueError as error:
        return {"error": str(error)}
    return {"presented": True, "presentation_id": presentation.id}


EVIDENCE_TOOL_GROUP = AssistantToolGroup(
    key="evidence",
    label="Evidence displays",
    description="Choose bounded views of retrieved evidence.",
    tools=(present_evidence,),
)
