"""Bound transcript inputs and validate references below the HTTP layer."""
from functools import lru_cache

import tiktoken

from .models import KeyMomentsInput, KeyMomentsOutput

MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_INPUT_TOKENS = 64_000
TOKENIZER = "o200k_base"


@lru_cache(maxsize=1)
def encoding():
    """Reuse the application's named source-text tokenizer."""
    return tiktoken.get_encoding(TOKENIZER)


def validate_input_budget(text: str) -> None:
    """Reject empty or oversized input before constructing or calling an agent."""
    if not text.strip():
        raise ValueError("Source input is empty")
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Source exceeds the 10 MB input ceiling")
    if len(encoding().encode(text, disallowed_special=())) > MAX_INPUT_TOKENS:
        raise ValueError("Source exceeds the 64,000 estimated token input budget (o200k_base)")


def validate_references(source: KeyMomentsInput, output: KeyMomentsOutput) -> KeyMomentsOutput:
    """Fail the entire output on invalid references and return chronological moments."""
    positions = {segment.id: index for index, segment in enumerate(source.segments)}
    for moment in output.moments:
        for evidence in moment.evidence:
            if evidence.start_segment_id not in positions or evidence.end_segment_id not in positions:
                raise ValueError("Unknown evidence segment ID")
            if positions[evidence.start_segment_id] > positions[evidence.end_segment_id]:
                raise ValueError("Evidence range endpoints are reversed")
        moment.evidence.sort(key=lambda r: positions[r.start_segment_id])
    output.moments.sort(key=lambda m: positions[m.evidence[0].start_segment_id])
    return output


def reject_refusal(result) -> None:
    """Treat provider refusals as failures instead of returning successful source notes."""
    for response in getattr(result, "raw_responses", []):
        for item in getattr(response, "output", []):
            for content in getattr(item, "content", []):
                if getattr(content, "type", None) == "refusal":
                    raise ValueError("The model refused this transcript task")
