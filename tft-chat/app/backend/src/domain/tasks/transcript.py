"""Distill source text through the registered transcript task."""

from __future__ import annotations

from domain.assistants import Assistant
from domain.assistants.constants import AssistantName


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
    result = Assistant(AssistantName.DISTILL_TRANSCRIPT, surface="task").run_sync(input_text)
    return str(result.final_output)


__all__ = [
    "TRANSCRIPTION_TASK_DESCRIPTION",
    "TRANSCRIPTION_TASK_NAME",
    "run_transcription_pipeline",
]
