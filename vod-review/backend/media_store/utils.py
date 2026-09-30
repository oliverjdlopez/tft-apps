"""Portable catalog operations; keep protocol v1 identical in both repositories."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .models import MediaRequest


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
