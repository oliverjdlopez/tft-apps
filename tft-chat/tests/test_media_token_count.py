"""Cover explicit tokenizer labeling and bounded desktop text counts."""

from app.backend.api.routes import media
from pydantic import ValidationError
import pytest


def test_token_count_returns_o200k_encoding_count(monkeypatch) -> None:
    """Count text through the named encoding without network/cache access."""
    class Encoding:
        """Provide a deterministic tokenizer double for the route contract."""

        def encode(self, text: str, *, disallowed_special: tuple) -> list[int]:
            """Represent this test's exact sample using three known tokens."""
            assert text == "Hello 世界"
            assert disallowed_special == ()
            return [1, 2, 3]

    monkeypatch.setattr(media, "_encoding", Encoding())
    assert media.token_count(media.TokenCountRequest(text="Hello 世界")) == {
        "token_count": 3,
        "tokenizer": "o200k_base",
    }


def test_token_count_request_enforces_preview_limit() -> None:
    """Reject oversized text at request validation before tokenization."""
    with pytest.raises(ValidationError):
        media.TokenCountRequest(text="x" * 10_000_001)
