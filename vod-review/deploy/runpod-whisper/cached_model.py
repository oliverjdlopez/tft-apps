"""Locate Runpod's host-staged Hugging Face model without network downloads."""

from pathlib import Path
import re


def resolve_snapshot_path(model_id: str, cache_root: str = "/runpod-volume/huggingface-cache/hub") -> Path:
    """Resolve a complete CTranslate2 model snapshot from Runpod's cache.

    Args:
        model_id: Hugging Face repository selected in the endpoint Model field.
        cache_root: Documented Runpod cache root, overridden by offline tests.

    Returns:
        A local directory containing weights, configuration, and tokenizer files.

    Raises:
        ValueError: The repository identifier is invalid.
        RuntimeError: The selected cached model is absent, ambiguous, or incomplete.
    """
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", model_id) or any(part in {".", ".."} for part in model_id.split("/")):
        raise ValueError("MODEL_NAME must be a Hugging Face repository in owner/name format")
    model_root = Path(cache_root) / f"models--{model_id.replace('/', '--')}"
    snapshots = model_root / "snapshots"
    reference = model_root / "refs/main"
    if reference.is_file():
        revision = reference.read_text().strip()
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
            raise RuntimeError(f"Invalid cached model revision for {model_id}")
        snapshot = snapshots / revision
    else:
        # Without refs/main, a single snapshot is unambiguous. Do not silently
        # select an arbitrary revision if multiple cached versions are present.
        candidates = [path for path in snapshots.iterdir() if path.is_dir()] if snapshots.is_dir() else []
        if len(candidates) != 1:
            raise RuntimeError(f"Cached model not found or ambiguous: {model_id}; configure the endpoint Model field")
        snapshot = candidates[0]
    # Some official conversions (including medium) omit the preprocessor file.
    # faster-whisper uses its built-in feature-extractor defaults in that case.
    # Keep tokenizer.json required to avoid its network-capable fallback.
    required = ("model.bin", "config.json", "tokenizer.json")
    missing = [name for name in required if not (snapshot / name).is_file()]
    if missing:
        raise RuntimeError(f"Cached model incomplete for {model_id}: {', '.join(missing)}; no runtime download will be attempted")
    return snapshot
