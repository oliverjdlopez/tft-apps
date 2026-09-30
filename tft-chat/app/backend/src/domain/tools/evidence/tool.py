"""Let the final responder select an initial view of backend-owned evidence."""

from typing import Any
from agents import function_tool
from agents.tool_context import ToolContext
from domain.types import AssistantToolGroup
from .models import DisplaySpec, EvidenceStore
from .utils import resolve_presentation


@function_tool(strict_mode=True)
async def present_evidence(
    ctx: ToolContext[Any], request: DisplaySpec
) -> dict[str, object]:
    """Choose a static table, distribution, or interactive table by evidence reference.

    Use only evidence references returned during this invocation. Values, units,
    row identity, and source context are resolved on the backend, not supplied
    by the assistant. Leave table options empty for a distribution.
    """
    if not isinstance(ctx.context, EvidenceStore):
        return {
            "error": "Evidence presentation is unavailable on this execution surface; answer in prose."
        }
    try:
        presentation = resolve_presentation(ctx.context, request, ctx.tool_call_id)
    except ValueError as error:
        return {"error": str(error)}
    return {"presented": True, "presentation_id": presentation.id}


EVIDENCE_TOOL_GROUP = AssistantToolGroup(
    key="evidence",
    label="Evidence displays",
    description="Choose bounded views of retrieved evidence.",
    tools=(present_evidence,),
)
