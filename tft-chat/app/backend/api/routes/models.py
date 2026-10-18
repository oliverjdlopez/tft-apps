"""Request models for desktop media helpers."""

from pydantic import BaseModel, ConfigDict, Field


class TokenCountRequest(BaseModel):
    """Bound the text accepted for a desktop preview token count."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=10_000_000)
