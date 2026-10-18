"""Identify critical passages through the existing typed Agents SDK runtime."""
from domain.assistants import Assistant
from domain.assistants.constants import AssistantName
from domain.runtime.execution import run_sync

from .models import KeyMomentsInput, KeyMomentsOutput
from .utils import reject_refusal, validate_input_budget, validate_references


def run_key_moments(input_text: str) -> dict:
    """Validate original source, execute once, and reject ungrounded references."""
    validate_input_budget(input_text)
    source = KeyMomentsInput.model_validate_json(input_text)
    result = run_sync(
        Assistant.from_name(AssistantName.FIND_KEY_MOMENTS, output_type=KeyMomentsOutput),
        input_text, surface="task",
    )
    reject_refusal(result)
    if not isinstance(result.final_output, KeyMomentsOutput):
        raise ValueError("Missing structured key-moment output or model refusal")
    return validate_references(source, result.final_output).model_dump()
