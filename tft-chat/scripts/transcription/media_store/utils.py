"""Portable catalog operations; keep protocol v1 identical in both repositories."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .models import MediaRequest


def configured_root() -> Path | None:
    """Resolve suite-owned storage for standalone and desktop processes.

    Returns:
        The absolute configured directory, defaulting to the suite's media
        directory. An explicitly empty TFT_MEDIA_DIR disables shared storage.

    Raises:
        ValueError: If an explicit storage path is relative.
    """
    app_root = next(parent for parent in Path(__file__).resolve().parents
                    if (parent / "pyproject.toml").is_file())
    value = os.environ.get("TFT_MEDIA_DIR", str(app_root.parent / "media")).strip()
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise ValueError("TFT_MEDIA_DIR must be an absolute path shared by both apps")
    return root.resolve()


def source_key(url: str) -> str:
    """Normalize supported stable video URLs without a remote metadata request."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Expected a Twitch or YouTube HTTP(S) URL")
    parts = parsed.path.strip("/").split("/")
    if host == "youtu.be" and parts[0]:
        return "youtube:" + parts[0]
    if host == "youtube.com" or host.endswith(".youtube.com"):
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if not video_id and len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
            video_id = parts[1]
        if video_id:
            return "youtube:" + video_id
    if host == "twitch.tv" or host.endswith(".twitch.tv"):
        if len(parts) == 2 and parts[0] == "videos" and parts[1].isdigit():
            return "twitch:" + parts[1]
        if host == "clips.twitch.tv" and parts[0]:
            return "twitch-clip:" + parts[0]
        if len(parts) == 3 and parts[1] == "clip":
            return "twitch-clip:" + parts[2]
    # Channel/live URLs can change identity. Never cache them under a stable URL.
    raise ValueError("Shared media requires a stable YouTube video or Twitch VOD/clip URL")


def validate_request(request: MediaRequest) -> None:
    """Reject invalid timeline and media requests before touching the catalog."""
    if request.kind not in {"audio", "video"}:
        raise ValueError("Media kind must be audio or video")
    if not math.isfinite(request.start) or request.start < 0:
        raise ValueError("Media start must be finite and nonnegative")
    if request.end is not None and (not math.isfinite(request.end) or request.end <= request.start):
        raise ValueError("Media end must be finite and after start")
    if request.height is not None and request.height <= 0:
        raise ValueError("Media height must be positive")


def probe(path: Path) -> dict:
    """Read actual streams so an audio file can never satisfy a video request."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    duration = float(info.get("format", {}).get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Media must have a positive finite duration")
    return {
        "duration": duration,
        "audio": any(s.get("codec_type") == "audio" for s in streams),
        "video": bool(videos),
        "height": int(videos[0].get("height", 0)) if videos else 0,
        "width": int(videos[0].get("width", 0)) if videos else 0,
        "playable": bool(videos) and videos[0].get("codec_name") == "h264" and path.suffix.lower() == ".mp4",
    }


def compatible(row: dict, request: MediaRequest) -> bool:
    """Check coverage and quality, allowing video audio to serve transcription."""
    if not row[request.kind] or row["start"] > request.start:
        return False
    if request.end is None:
        if row["end"] is not None:
            return False
    elif row["end"] is not None and row["end"] < request.end:
        return False
    if request.kind == "audio" and request.profile == "audio":
        return True
    if row["profile"] == request.profile:
        return True
    return request.height is not None and row["height"] >= request.height


def lock_name(key: str) -> str:
    """Hash remote IDs before using them as local lock filenames."""
    return hashlib.sha256(key.encode()).hexdigest() + ".lock"


def derive(source: Path, destination: Path, row: dict, request: MediaRequest) -> None:
    """Cut cached media locally with timestamps rebased to the requested start."""
    command = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-ss", str(request.start - row["start"])]
    if request.end is not None:
        command += ["-t", str(request.end - request.start)]
    if request.kind == "audio":
        command += ["-map", "0:a:0", "-vn", "-c:a", "aac"]
    else:
        command += ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac"]
        if request.height is not None and row["height"] > request.height:
            command += ["-vf", f"scale=-2:{request.height}"]
    command += ["-movflags", "+faststart", str(destination)]
    subprocess.run(command, check=True, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Shared resource operations
# Content integrity and catalog decoding
# Used by the modality-independent resource store
# ---------------------------------------------------------------------------


def resource_digest(path: Path) -> str:
    """Hash artifacts incrementally so large data files fit bounded memory."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def resource_from_row(value: str):
    """Decode catalog metadata and validate IDs before constructing disk paths."""
    from .models import Resource

    resource = Resource(**json.loads(value))
    if len(resource.id) != 32 or any(c not in "0123456789abcdef" for c in resource.id):
        raise ValueError("Invalid catalog resource ID")
    return resource


def resource_payload(resource) -> dict:
    """Expose provenance and portable references without host filesystem paths."""
    return {**asdict(resource), "reference": resource.reference,
            "content_url": f"/api/shared-media/{resource.reference}/content"}


@contextmanager
def resource_errors():
    """Translate catalogue failures into consistent responses in both backends."""
    from fastapi import HTTPException

    try:
        yield
    except KeyError:
        raise HTTPException(404, "Unknown shared resource") from None
    except FileNotFoundError:
        raise HTTPException(410, "Shared resource file is missing") from None
    except ValueError:
        raise HTTPException(409, "Shared resource is invalid or failed its integrity check") from None


def copy_resource(source: Path, destination: Path, root: Path) -> None:
    """Link immutable catalogue media, copying caller-owned files for isolation.

    Args:
        source: Completed file being published.
        destination: New temporary resource path.
        root: Catalogue root shared by both applications.
    """
    if source.resolve().parent == root / "media" and not source.is_symlink():
        # Both names belong to this catalogue and are immutable. This avoids
        # storing a second multi-gigabyte copy when indexing a URL download.
        os.link(source, destination)
    else:
        import shutil

        shutil.copyfile(source, destination)
