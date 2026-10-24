"""Resolve large audio inputs from a mounted Runpod network volume."""

from pathlib import Path


def resolve_mounted_input(inputs: dict, volume_root: str = "/runpod-volume") -> str:
    """Resolve an application-owned audio upload on the mounted volume.

    Args:
        inputs: Job inputs containing an audio_path and no embedded/URL sources.
        volume_root: Fixed worker mount; overridden only by offline tests.

    Returns:
        The existing mounted file's absolute path.

    Raises:
        ValueError: Sources conflict or the path escapes the upload directory.
        FileNotFoundError: The mounted audio file is absent or is a directory.
    """
    if not isinstance(inputs.get("audio_path"), str) or not inputs["audio_path"] or any(inputs.get(name) for name in ("audio", "audio_base64")):
        raise ValueError("Provide exactly one source: audio_path (mounted audio only)")

    relative = Path(inputs["audio_path"])
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("vod-transcription",):
        raise ValueError("audio_path must be relative and inside vod-transcription/")

    # Resolve symlinks before containment checks so a link cannot expose files
    # elsewhere on the volume or in the worker container.
    root = Path(volume_root).resolve()
    directory = root / "vod-transcription"
    path = (root / relative).resolve()
    if not path.is_relative_to(directory):
        raise ValueError("audio_path escapes vod-transcription/")
    if not path.is_file():
        raise FileNotFoundError("Mounted audio file does not exist")
    return str(path)
