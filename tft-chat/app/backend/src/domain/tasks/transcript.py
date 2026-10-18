"""Distill source text through the registered transcript task."""

from __future__ import annotations

from domain.assistants import Assistant
from domain.runtime.execution import run_sync
from domain.assistants.constants import AssistantName
from .utils import reject_refusal


TRANSCRIPTION_TASK_NAME = "transcription_pipeline"
TRANSCRIPTION_TASK_DESCRIPTION = (
    "Distill transcripts or other text into source-grounded ChatTFT references."
)


def run_transcription_pipeline(input_text: str = "") -> str:
    """Distill one source body with a single assistant invocation.

    Args:
        input_text: Source text with any available metadata or transcript locators.

    Returns:
        Compact Markdown reference notes grounded in the supplied source.
    """
    result = run_sync(Assistant.from_name(AssistantName.DISTILL_TRANSCRIPT), input_text, surface="task")
    reject_refusal(result)
    if not isinstance(result.final_output, str) or not result.final_output.strip():
        raise ValueError("Missing Markdown output from transcript distillation")
    return result.final_output


__all__ = [
    "TRANSCRIPTION_TASK_DESCRIPTION",
    "TRANSCRIPTION_TASK_NAME",
    "run_transcription_pipeline",
]
