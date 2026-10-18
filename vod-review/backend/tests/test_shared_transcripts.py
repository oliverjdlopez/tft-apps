"""Verify completed recognition reaches shared storage without live inference."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from backend import app, db, shared_transcripts
from backend.media_store.resources import ResourceStore


@pytest.fixture
def local_transcripts(tmp_path, monkeypatch):
    """Keep transcript tasks and shared resources away from user runtime state."""
    for name, value in {"DATA_DIR": tmp_path / "vod", "VIDEO_DIR": tmp_path / "vod/videos",
                        "DOWNLOAD_DIR": tmp_path / "vod/downloads",
                        "DB_PATH": tmp_path / "vod/vod.sqlite3"}.items():
        monkeypatch.setattr(db, name, value)
    monkeypatch.setenv("TFT_MEDIA_DIR", str(tmp_path / "shared"))
    db.init_db()
    return ResourceStore(tmp_path / "shared")


def test_transcription_completion_publishes_exact_readable_text(local_transcripts, monkeypatch):
    """The real completion path publishes text that the media API can list/read."""
    text = "  First round. Café ☕\nNext round.  "
    segments = [{"start": 1.25, "end": 3.75, "text": text}]
    db.create_transcription_task("recognition", "/fixture/vod.mp4")
    monkeypatch.setattr(app, "_transcribe_audio_file", lambda _path, progress_callback=None: app.AudioTranscription(transcript=text, language="en", segments=segments))
    asyncio.run(app._run_transcription_task("recognition"))
    assert db.get_transcription_task("recognition")["status"] == "completed"
    client = TestClient(app.app)
    response = client.get("/api/shared-media", params={"kind": "text"})
    assert response.status_code == 200
    resource, = response.json()
    assert resource["metadata"]["transcription_task_id"] == "recognition"
    assert resource["metadata"]["language"] == "en"
    assert resource["content_type"] == "text/plain; charset=utf-8"
    content = client.get(resource["content_url"])
    assert content.status_code == 200
    assert content.content == text.encode("utf-8")
    timed, = local_transcripts.find(kind="data")
    assert timed.name == "transcript-recognition.json"
    assert timed.metadata["text_reference"] == resource["reference"]
    assert local_transcripts.read_json(timed.reference) == {
        "schema_version": 1, "transcription_task_id": "recognition", "video_id": None,
        "language": "en", "text_reference": resource["reference"], "transcript": text,
        "time_unit": "seconds", "time_origin": "media_start", "segments": segments,
    }
    assert client.get("/api/transcriptions/recognition").json() == {
        "task_id": "recognition", "video_id": None, "status": "completed",
        "progress": 100.0, "transcript": text, "language": "en", "error": None,
    }


def test_whisper_segment_generator_preserves_timing_and_reports_progress(monkeypatch):
    """Consume Whisper's lazy segments once without losing offsets or text order."""
    calls = []

    class FakeWhisperModel:
        """Supply lazy speech segments without loading a GPU or downloading models."""

        def __init__(self, *args, **kwargs):
            """Accept production model configuration without initializing inference."""

        def transcribe(self, path, **kwargs):
            """Keep a silence gap to catch reconstructed or rebased timestamps."""
            calls.append((path, kwargs))
            segments = iter([
                SimpleNamespace(start=1.25, end=2.5, text=" First."),
                SimpleNamespace(start=9.0, end=10.75, text=" Café ☕."),
            ])
            return segments, SimpleNamespace(language="en", duration=20.0)

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    progress = []
    result = app._transcribe_audio_file("/fixture/audio.m4a", progress.append)
    assert result.transcript == "First. Café ☕."
    assert result.language == "en"
    assert [segment.model_dump() for segment in result.segments] == [
        {"start": 1.25, "end": 2.5, "text": " First."},
        {"start": 9.0, "end": 10.75, "text": " Café ☕."},
    ]
    assert calls == [("/fixture/audio.m4a", {"beam_size": 5, "vad_filter": True})]
    assert progress == pytest.approx([12.5, 53.75, 99.0])


def test_transcription_task_persists_monotonic_progress(local_transcripts, monkeypatch):
    """Persist recognition updates for status polling and clamp completion to saved output."""
    db.create_transcription_task("progress", "/fixture/audio.m4a")

    def recognize(_path, progress_callback):
        progress_callback(40)
        progress_callback(20)
        return app.AudioTranscription(transcript="Speech", language="en")

    async def direct_to_thread(function, *args):
        return function(*args)

    monkeypatch.setattr(app, "_transcribe_audio_file", recognize)
    monkeypatch.setattr(app.asyncio, "to_thread", direct_to_thread)
    monkeypatch.setattr(app, "publish_completed_transcripts", lambda _task_id: None)
    asyncio.run(app._run_transcription_task("progress"))
    task = db.get_transcription_task("progress")
    assert task["progress"] == 100
    assert task["status"] == "completed"


def test_existing_completed_transcripts_recover_once_on_startup(local_transcripts, monkeypatch):
    """Backend startup shares older results, without inference or duplicate IDs."""
    db.create_transcription_task("older", "/missing/original.mp4")
    db.update_transcription_task("older", status="completed", transcript="Existing result", language="en")
    monkeypatch.setattr(app, "WORKERS", object())
    monkeypatch.setattr(app, "configure_performance_logging", lambda: None)
    app.startup()
    first, = local_transcripts.find(kind="text")
    app.startup()
    assert local_transcripts.find(kind="text") == [first]
    assert local_transcripts.read_text(first.reference) == "Existing result"
    assert local_transcripts.find(kind="data") == []


def test_legacy_database_migration_preserves_text_without_inventing_timing(local_transcripts):
    """Add nullable timing storage to existing tasks safely across repeated startup."""
    db.create_transcription_task("older", "/missing/original.mp4")
    db.update_transcription_task("older", status="completed", transcript="Old speech")
    connection = db.get_db()
    connection.execute("ALTER TABLE transcription_tasks DROP COLUMN segments_json")
    connection.commit()
    connection.close()
    db.init_db()
    db.init_db()
    task = db.get_transcription_task("older", include_segments=True)
    assert task["transcript"] == "Old speech"
    assert task["segments"] is None
    assert shared_transcripts.publish_completed_transcripts() == 1
    assert local_transcripts.find(kind="data") == []


def test_timing_publication_failure_is_recoverable_without_recognition(local_transcripts, monkeypatch):
    """Retry a failed JSON publication from persisted timing while retaining text."""
    segments = [{"start": 4.5, "end": 6.25, "text": " Recoverable."}]
    db.create_transcription_task("timed", "/fixture/vod.mp4")
    monkeypatch.setattr(app, "_transcribe_audio_file", lambda _path, progress_callback=None: app.AudioTranscription(
        transcript="Recoverable.", language="en", segments=segments,
    ))
    publish = ResourceStore.publish

    def unavailable_json(self, *args, **kwargs):
        """Fail only the JSON sidecar after the text snapshot has been saved."""
        if kwargs["kind"] == "data":
            raise OSError("fixture JSON storage unavailable")
        return publish(self, *args, **kwargs)

    monkeypatch.setattr(ResourceStore, "publish", unavailable_json)
    asyncio.run(app._run_transcription_task("timed"))
    assert db.get_transcription_task("timed")["status"] == "completed"
    assert db.get_transcription_task("timed", include_segments=True)["segments"] == segments
    first_text, = local_transcripts.find(kind="text")
    assert local_transcripts.find(kind="data") == []
    monkeypatch.setattr(ResourceStore, "publish", publish)
    db.init_db()
    with ThreadPoolExecutor(max_workers=4) as workers:
        assert list(workers.map(shared_transcripts.publish_completed_transcripts, ["timed"] * 4)) == [1] * 4
    timed, = local_transcripts.find(kind="data")
    assert local_transcripts.find(kind="text") == [first_text]
    assert local_transcripts.read_json(timed.reference)["segments"] == segments
    # A changed timestamp creates new JSON even when the plain text is identical.
    segments[0]["end"] = 6.75
    db.update_transcription_task("timed", segments=segments)
    shared_transcripts.publish_transcript("timed")
    changed = local_transcripts.find(kind="data")[0]
    assert changed.reference != timed.reference
    assert local_transcripts.read_json(timed.reference)["segments"][0]["end"] == 6.25
    local_transcripts.resolve(changed.reference).write_bytes(b"corrupt")
    shared_transcripts.publish_transcript("timed")
    repaired = local_transcripts.find(kind="data")[0]
    assert repaired.reference != changed.reference
    assert local_transcripts.read_json(repaired.reference)["segments"] == segments
    assert local_transcripts.find(kind="text") == [first_text]


def test_silent_transcription_shares_empty_timing(local_transcripts):
    """Timed silence produces an empty segment list rather than legacy NULL."""
    db.create_transcription_task("silence", "/fixture/audio.m4a")
    db.update_transcription_task("silence", status="completed", transcript="", segments=[])
    shared_transcripts.publish_transcript("silence")
    timed, = local_transcripts.find(kind="data")
    assert local_transcripts.read_json(timed.reference)["segments"] == []


def test_disabled_or_unavailable_sharing_preserves_completed_tasks(local_transcripts, monkeypatch, caplog):
    """Storage errors never discard or relabel already recognized text."""
    db.create_transcription_task("complete", "/fixture/audio.m4a")
    monkeypatch.setattr(app, "_transcribe_audio_file", lambda _path, progress_callback=None: app.AudioTranscription(transcript="Saved transcript", language="en"))

    def unavailable(*args, **kwargs):
        """Simulate a failed catalogue publication after successful recognition."""
        raise OSError("fixture storage unavailable")

    monkeypatch.setattr(ResourceStore, "publish", unavailable)
    asyncio.run(app._run_transcription_task("complete"))
    assert db.get_transcription_task("complete")["status"] == "completed"
    assert db.get_transcription_task("complete")["transcript"] == "Saved transcript"
    assert "Could not share completed transcript" in caplog.text
    monkeypatch.setenv("TFT_MEDIA_DIR", "")
    assert shared_transcripts.publish_completed_transcripts() == 0
    assert local_transcripts.find(kind="text") == []


def test_unfinished_failed_empty_and_changed_transcripts(local_transcripts):
    """Only completed results publish, and changed text creates a fresh snapshot."""
    for status in ["queued", "running", "failed"]:
        db.create_transcription_task(status, "/fixture/audio.m4a")
        db.update_transcription_task(status, status=status, transcript="Partial")
        assert shared_transcripts.publish_transcript(status) is None
    db.create_transcription_task("complete", "/fixture/audio.m4a")
    db.update_transcription_task("complete", status="completed", transcript="")
    first = shared_transcripts.publish_transcript("complete")
    assert local_transcripts.read_text(first) == ""
    db.update_transcription_task("complete", transcript="Fresh text")
    second = shared_transcripts.publish_transcript("complete")
    assert first != second
    assert local_transcripts.read_text(first) == ""
    assert local_transcripts.read_text(second) == "Fresh text"


def test_parallel_recovery_reuses_snapshot_and_missing_file_can_be_repaired(local_transcripts):
    """Concurrent recovery produces one snapshot and can restore missing bytes."""
    db.create_transcription_task("complete", "/fixture/audio.m4a")
    db.update_transcription_task("complete", status="completed", transcript="Recoverable")
    with ThreadPoolExecutor(max_workers=4) as workers:
        references = list(workers.map(shared_transcripts.publish_transcript, ["complete"] * 4))
    assert len(set(references)) == 1
    assert len(local_transcripts.find(kind="text")) == 1
    local_transcripts.resolve(references[0]).unlink()
    recovered = shared_transcripts.publish_transcript("complete")
    assert recovered != references[0]
    assert local_transcripts.read_text(recovered) == "Recoverable"


def test_video_transcript_has_a_recognizable_name(local_transcripts, tmp_path):
    """A selected video produces a transcript named after its source VOD."""
    video = db.create_video("video", "A game.mp4", tmp_path / "game.mp4", "video/mp4", 1, 10, 10)
    db.create_transcription_task("recognition", "/fixture/vod.mp4", video["id"])
    db.update_transcription_task("recognition", status="completed", transcript="Transcript")
    reference = shared_transcripts.publish_transcript("recognition")
    assert local_transcripts.get(reference).name == "A game.transcript.txt"
    assert local_transcripts.get(reference).metadata["video_id"] == video["id"]
