"""Provide ChatTFT-only helpers for the desktop media browser."""

import tiktoken
from fastapi import APIRouter
from .models import TokenCountRequest


router = APIRouter(prefix="/api/media", tags=["media"])
TOKENIZER = "o200k_base"
_encoding = None


def count_text_tokens(text: str) -> int:
    """Count text with the named OpenAI BPE encoding, excluding chat framing."""
    global _encoding

    # Keep the encoding warm after its first use; tokenizer files are cached by tiktoken.
    if _encoding is None:
        _encoding = tiktoken.get_encoding(TOKENIZER)
    return len(_encoding.encode(text, disallowed_special=()))


@router.post("/token-count")
def token_count(body: TokenCountRequest) -> dict[str, int | str]:
    """Return an explicit tokenizer count for the supplied text."""
    return {"token_count": count_text_tokens(body.text), "tokenizer": TOKENIZER}
