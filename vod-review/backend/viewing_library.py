"""Read existing videos and completed artifacts without starting processing."""

from contextlib import closing
from pathlib import Path
import math

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

try:
    from . import db
    from .media_store.router import required_store
    from .media_store.utils import resource_errors
except ImportError:  # Support the backend-directory launcher.
    import db
    from media_store.router import required_store
    from media_store.utils import resource_errors

def _seconds(value, default=0):
    """Accept only finite, nonnegative numeric catalogue timestamps."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else default


def _same_range(artifact, video):
    """Avoid attaching source-relative transcripts to a different saved clip."""
    return (artifact.metadata.get("start", 0) == video.metadata.get("start", 0)
            and artifact.metadata.get("end") == video.metadata.get("end"))


def _is_transcript_for(artifact, video):
    """Match an artifact by explicit video identity or exact source coverage."""
    return (artifact.metadata.get("video_reference") == video.reference
            or (artifact.source == video.source and _same_range(artifact, video))
            or (video.metadata.get("video_id")
                and artifact.metadata.get("video_id") == video.metadata["video_id"]))


router = APIRouter(prefix="/api/viewing-library", tags=["viewing-library"])


def _resources(store):
    """Read every catalogue page so older completed media remains visible."""
    offset = 0
    while True:
        page = store.find(limit=1000, offset=offset)
        yield from page
        if len(page) < 1000:
            return
        offset += len(page)


def _index():
    """Join immutable artifacts to owned video records using explicit identities.

    Returns:
        The store and viewing entries, newest first within each source library. Source-only joins require
        matching start/end coverage; filenames are never used to infer relationships.
    """
    store = required_store()
    resources = list(_resources(store))
    transcripts = [r for r in resources if r.kind in {"text", "data"}
                   and (r.metadata.get("type") in ("transcript", "timestamped_transcript")
                        or (r.kind == "text" and "transcript" in r.name.lower()))]
    videos = [r for r in resources if r.kind == "video"]
    entries = []
    claimed = set()
    with closing(db.get_db()) as connection:
        rows = connection.execute("SELECT * FROM videos ORDER BY created_at DESC").fetchall()
        for row in rows:
            # Prefer successful artifacts even when a newer attempt failed/runs.
            task = connection.execute(
                "SELECT id FROM transcription_tasks WHERE video_id=? AND status='completed' "
                "AND transcript IS NOT NULL ORDER BY created_at DESC, rowid DESC LIMIT 1", (row["id"],),
            ).fetchone()
            job = connection.execute(
                "SELECT id FROM jobs WHERE video_id=? AND status='completed' "
                "AND EXISTS (SELECT 1 FROM results WHERE job_id=jobs.id) "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1", (row["id"],),
            ).fetchone()
            source_key = row["source_id"]
            if source_key and not source_key.startswith("twitch:"):
                source_key = "youtube:" + source_key
            related = [r for r in videos if r.metadata.get("video_id") == row["id"]
                       or (row["path"] and Path(row["path"]) == store.root / "resources" / r.id)
                       or (r.source == source_key
                           and r.metadata.get("start", 0) == row["source_start_seconds"]
                           and abs(_seconds(r.metadata.get("duration"), -1) - row["duration"]) < 1)]
            artifacts = [r for r in transcripts if r.metadata.get("video_id") == row["id"]
                         or any(_is_transcript_for(r, v) for v in related)]
            if not task and not job and not artifacts:
                continue
            # A missing local file still has video information; retain the entry
            # so its transcript can be read and playback failure is recoverable.
            local = bool(row["path"] and Path(row["path"]).is_file())
            if not row["path"] and not row["source_id"] and not related:
                continue
            claimed.update(r.reference for r in related)
            entries.append({
                "id": row["id"], "name": row["original_name"],
                "source": row["source_url"] or "Local video", "duration": row["duration"],
                "source_id": row["source_id"], "start": row["source_start_seconds"],
                "local_available": local, "video_id": row["id"],
                "content_url": f'/api/viewing-library/{row["id"]}/content' if local else None,
                "has_transcript": bool(task or artifacts), "has_transitions": bool(job),
                "task_id": task["id"] if task else None,
                "transcript_reference": artifacts[0].reference if artifacts else None,
                "job_id": job["id"] if job else None,
                "review_mode": row["mode"],
            })
    for video in videos:
        if video.reference in claimed:
            continue
        artifacts = [r for r in transcripts if _is_transcript_for(r, video)]
        if not artifacts:
            continue
        entries.append({
            "id": video.reference, "name": video.name, "source": video.source,
            "duration": _seconds(video.metadata.get("duration")), "source_id": None, "start": 0,
            "local_available": True, "video_id": None,
            "content_url": f"/api/shared-media/{video.reference}/content",
            "has_transcript": True, "has_transitions": False,
            "task_id": None, "transcript_reference": artifacts[0].reference, "job_id": None,
        })
    return store, entries


@router.get("")
def list_viewing_media() -> list[dict]:
    """List only video entries with a completed transcript or round results."""
    _, entries = _index()
    return [{k: v for k, v in entry.items() if k not in {"task_id", "job_id", "transcript_reference"}}
            for entry in entries]


@router.get("/{identity}")
def get_viewing_media(identity: str) -> dict:
    """Read saved artifacts and existing playback, never scheduling new work.

    Args:
        identity: An owned video ID or portable catalogue video reference.

    Returns:
        The selected entry, transcript, and completed round timestamps. Artifact
        read failures remain local to the transcript so video stays accessible.
    """
    store, entries = _index()
    entry = next((item for item in entries if item["id"] == identity), None)
    if entry is None:
        raise HTTPException(404, "This video has no saved viewing artifacts")
    transcript = None
    transcript_error = None
    try:
        if entry["task_id"]:
            task = db.get_transcription_task(entry["task_id"], include_segments=True)
            transcript = {key: task[key] for key in ("transcript", "language", "segments")}
        elif entry["transcript_reference"]:
            with resource_errors():
                resource = store.get(entry["transcript_reference"])
                if resource.metadata.get("type") == "timestamped_transcript":
                    payload = store.read_json(resource.reference)
                    if (not isinstance(payload, dict) or not isinstance(payload.get("transcript"), str)
                            or payload.get("schema_version") != 1 or payload.get("time_unit") != "seconds"
                            or payload.get("time_origin") != "media_start"):
                        raise ValueError("Invalid transcript snapshot")
                    segments = payload.get("segments")
                    if segments is not None and (not isinstance(segments, list) or any(
                        not isinstance(segment, dict) or not isinstance(segment.get("text"), str)
                        or _seconds(segment.get("start"), -1) < 0
                        or _seconds(segment.get("end"), -1) < _seconds(segment.get("start"), -1)
                        for segment in segments
                    )):
                        raise ValueError("Invalid transcript timing")
                    if payload.get("language") is not None and not isinstance(payload["language"], str):
                        raise ValueError("Invalid transcript language")
                    transcript = {"transcript": payload["transcript"], "language": payload.get("language"),
                                  "segments": payload.get("segments")}
                else:
                    transcript = {"transcript": store.read_text(resource.reference),
                                  "language": resource.metadata.get("language") if isinstance(resource.metadata.get("language"), str) else None, "segments": None}
    except (HTTPException, KeyError, ValueError, OSError):
        transcript_error = "The saved transcript could not be read. Refresh to try again."
    transitions = []
    if entry["job_id"]:
        with closing(db.get_db()) as connection:
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (entry["job_id"],)).fetchone()
            transitions = db.serialize_job(connection, job)["results"]
    # Use a pre-existing browser-compatible derivative when available. Unlike
    # GET /playback, this check cannot launch ffmpeg or prepare new playback.
    manifest_url = None
    if entry["local_available"] and entry["video_id"]:
        try:
            from .app import playback_is_ready
        except ImportError:
            from app import playback_is_ready
        if entry["review_mode"] == "offline" and playback_is_ready(entry["video_id"]):
            manifest_url = f'/api/videos/{entry["video_id"]}/playback/index.m3u8'
    return {**entry, "transcript": transcript, "transcript_error": transcript_error,
            "transitions": transitions, "manifest_url": manifest_url}


@router.get("/{identity}/content")
def viewing_video_content(identity: str) -> FileResponse:
    """Serve an existing local copy without changing the review playback mode.

    Args:
        identity: Owned video ID from the filtered viewing library.

    Returns:
        Existing video bytes with HTTP range support; no preparation is started.
    """
    _, entries = _index()
    entry = next((item for item in entries if item["id"] == identity), None)
    if entry is None or not entry["video_id"]:
        raise HTTPException(404, "Video not found in the viewing library")
    path = db.physical_video_path(entry["video_id"])
    if path is None or not path.is_file():
        raise HTTPException(410, "The saved video is no longer available")
    return FileResponse(path, media_type=db.get_video_mime_type(entry["video_id"]))
