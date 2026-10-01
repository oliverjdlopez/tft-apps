"""Keep transcription configuration separate from the vendored media protocol."""

from .media_store import MediaStore


def configured_media_store() -> MediaStore | None:
    """Select the suite catalogue or an explicitly disabled local downloader."""
    return MediaStore.from_env()
