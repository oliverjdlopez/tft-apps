"""Construct source snapshots and resolve evidence without model-generated timing."""
import hashlib
import json
import math
from functools import lru_cache

import tiktoken
from fastapi import HTTPException

from .models import KeyMoments


def transcript_hash(source: dict) -> str:
    """Hash original text, language, and raw segments, distinguishing null and []."""
    payload = {key: source.get(key) for key in ("transcript", "language", "segments")}
    try:
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "Malformed stored transcript data") from exc
    return hashlib.sha256(canonical.encode()).hexdigest()


def public_segments(segments: list | None) -> list | None:
    """Assign IDs from original array indices without changing stored publication data."""
    if segments is None:
        return None
    if not isinstance(segments, list) or any(not isinstance(s, dict) for s in segments):
        raise HTTPException(422, "Malformed stored transcript segments")
    return [{**s, "id": f"s{i:06d}"} for i, s in enumerate(segments)]


@lru_cache(maxsize=1)
def encoding():
    """Keep the named BPE encoding warm for application input-budget checks."""
    return tiktoken.get_encoding("o200k_base")


def assemble_input(source: dict, title: str, timed: bool) -> str:
    """Validate prerequisites and serialize a bounded, unmodified source snapshot."""
    if source["status"] != "completed":
        raise HTTPException(409, "Speech recognition must finish first")
    if not isinstance(source.get("transcript"), str) or not source["transcript"].strip():
        raise HTTPException(422, "No speech was detected")
    metadata = {"transcription_task_id": source["task_id"], "title": title, "language": source["language"]}
    if timed:
        if source.get("segments") is None:
            raise HTTPException(409, "Timing is unavailable. Explicitly retranscribe the video or reimport the audio source.")
        segments = public_segments(source["segments"])
        previous = -1.0
        if not segments:
            raise HTTPException(422, "No timed speech was detected")
        for segment in segments:
            start, end = segment.get("start"), segment.get("end")
            if (isinstance(start, bool) or isinstance(end, bool)
                    or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                    or not math.isfinite(start) or not math.isfinite(end)
                    or start < 0 or end < start or start < previous
                    or not isinstance(segment.get("text"), str)):
                raise HTTPException(422, "Malformed transcript timing")
            previous = start
        if not any(segment["text"].strip() for segment in segments):
            raise HTTPException(422, "No timed speech was detected")
        body = json.dumps({"schema_version": 1, "source": metadata, "time_unit": "seconds", "time_origin": "media_start", "segments": segments}, ensure_ascii=False, allow_nan=False)
    else:
        body = f"Source metadata:\n{json.dumps(metadata, ensure_ascii=False)}\n\nSource text:\n{source['transcript']}"
    if len(body.encode()) > 10 * 1024 * 1024:
        raise HTTPException(422, "Source exceeds the 10 MB input ceiling")
    if len(encoding().encode(body, disallowed_special=())) > 64_000:
        raise HTTPException(422, "Source exceeds the 64,000 estimated token input budget (o200k_base)")
    return body


def resolve_output(result: object, source: dict, timed: bool) -> str | dict:
    """Reject invalid upstream output as a whole; derive times and exact source excerpts."""
    if not timed:
        if not isinstance(result, str) or not result.strip():
            raise ValueError("Missing Markdown output")
        return result
    parsed = KeyMoments.model_validate(result)
    segments = public_segments(source["segments"])
    positions = {s["id"]: i for i, s in enumerate(segments)}
    output = parsed.model_dump()
    for moment in output["moments"]:
        for evidence in moment["evidence"]:
            first = positions.get(evidence["start_segment_id"])
            last = positions.get(evidence["end_segment_id"])
            if first is None or last is None or first > last:
                raise ValueError("Unknown or reversed evidence segment range")
            selection = segments[first:last + 1]
            evidence.update(start_seconds=selection[0]["start"], end_seconds=max(s["end"] for s in selection), excerpt="".join(s["text"] for s in selection))
        moment["evidence"].sort(key=lambda e: positions[e["start_segment_id"]])
    output["moments"].sort(key=lambda m: positions[m["evidence"][0]["start_segment_id"]])
    return output


def source_title(source: dict) -> str:
    """Recover a display title without exposing any internal media path."""
    from contextlib import closing
    try:
        from .. import db
    except ImportError:
        import db
    if source.get("video_id"):
        try:
            return db.get_video(source["video_id"])["original_name"]
        except HTTPException:
            pass
    with closing(db.get_db()) as connection:
        row = connection.execute("SELECT url FROM download_tasks WHERE transcription_task_id=? ORDER BY created_at DESC LIMIT 1", (source["task_id"],)).fetchone()
    return row["url"] if row and row["url"] else "Audio transcript"
