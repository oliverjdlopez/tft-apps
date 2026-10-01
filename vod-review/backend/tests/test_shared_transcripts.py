"""Verify completed recognition reaches shared storage without live inference."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

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
    db.create_transcription_task("recognition", "/fixture/vod.mp4")
    monkeypatch.setattr(app, "_transcribe_audio_file", lambda _: (text, "en"))
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


def test_disabled_or_unavailable_sharing_preserves_completed_tasks(local_transcripts, monkeypatch, caplog):
    """Storage errors never discard or relabel already recognized text."""
    db.create_transcription_task("complete", "/fixture/audio.m4a")
    monkeypatch.setattr(app, "_transcribe_audio_file", lambda _: ("Saved transcript", "en"))

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
