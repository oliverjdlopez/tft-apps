"""Formatting helpers for the saved-evaluation document exporter."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


def atomic_write(path: Path, data: bytes) -> None:
    """Replace an export atomically without importing the assistant runtime."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def heading(value: Any) -> str:
    """Escape saved labels so they remain a single Markdown heading."""
    text = str(value).replace("\n", " ").replace("\r", " ")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", text)


def content(value: Any) -> str:
    """Preserve textual inputs and answers, and fence structured JSON safely."""
    if isinstance(value, str):
        return value
    text = json.dumps(value, ensure_ascii=False, indent=2)
    # A JSON string can itself contain a fence; choose one it cannot close.
    longest = max((len(match) for match in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}json\n{text}\n{fence}"


def dataset_name(bundle: dict) -> str:
    """Use the frozen dataset name, falling back to legacy local suite names."""
    return bundle.get("dataset_name") or bundle["suite"]["name"]


def document_stem(name: str) -> str:
    """Create a bounded filename that distinguishes colliding dataset labels."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:80] or "dataset"
    digest = hashlib.sha256(name.encode()).hexdigest()[:10]
    return f"{slug}-{digest}"


def block_resource(url: str) -> dict:
    """Prevent saved Markdown images from reading files or contacting services."""
    raise ValueError("External resources are disabled in evaluation PDFs")


def image_label(tokens, index, options, env) -> str:
    """Render image alt text in PDFs without fetching its referenced resource."""
    from html import escape

    return '<span class="image-label">[Image: ' + escape(tokens[index].content) + "]</span>"
