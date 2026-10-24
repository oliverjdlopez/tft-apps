"""Read-only viewing contracts with isolated catalogue and application state."""

from fastapi.testclient import TestClient
import pytest

from backend import app, db
from backend.media_store.resources import ResourceStore


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Isolate all records and fail immediately if viewing starts processing."""
    for name, path in {"DATA_DIR": tmp_path, "VIDEO_DIR": tmp_path / "videos",
                       "DOWNLOAD_DIR": tmp_path / "downloads", "DB_PATH": tmp_path / "vod.sqlite3"}.items():
        monkeypatch.setattr(db, name, path)
    monkeypatch.setenv("TFT_MEDIA_DIR", str(tmp_path / "shared"))
    db.init_db()

    def forbidden(*args, **kwargs):
        """Reject any attempt to schedule new work while browsing."""
        pytest.fail("Viewing must not start processing")

    monkeypatch.setattr(app, "start_playback_preparation", forbidden)
    monkeypatch.setattr(app, "launch_video_transcription", forbidden)
    return TestClient(app.app), ResourceStore(tmp_path / "shared"), tmp_path


def video(root, identity):
    """Create existing local media without decoding or remote I/O."""
    path = root / f"{identity}.mp4"
    path.write_bytes(b"existing video fixture")
    return db.create_video(identity, f"{identity}.mp4", path, "video/mp4", 300, 1280, 720)


def transcript(identity, task_id="saved"):
    """Persist completed recognition without running a model."""
    db.create_transcription_task(task_id, "/fixture", identity)
    db.update_transcription_task(task_id, status="completed", transcript="Saved speech", language="en",
                                 segments=[{"start": 7, "end": 9, "text": "Saved speech"}])


def rounds(identity):
    """Persist a completed round job with an actual PTS different from schedule."""
    db.save_bounding_box(identity, {"x": .5, "y": 0, "width": .2, "height": .1, "frame_time": 0})
    db.create_processing_job(identity, "rounds", 64, 1)
    db.complete_job("rounds", identity, [(10, 10.125, "21", .9)], 1, 1, "cpu")


def test_filters_unfinished_and_audio_only_and_retains_completed_results(library):
    """Only saved artifacts with attached video qualify, even during a rerun."""
    client, _, root = library
    video(root, "unprocessed")
    video(root, "ready")
    video(root, "unfinished")
    transcript("ready")
    db.create_transcription_task("rerun", "/fixture", "ready")
    db.create_transcription_task("pending", "/fixture", "unfinished")
    transcript(None, "audio")
    entries = client.get("/api/viewing-library").json()
    assert [entry["id"] for entry in entries] == ["ready"]
    detail = client.get("/api/viewing-library/ready").json()
    assert detail["transcript"]["transcript"] == "Saved speech"
    assert detail["transcript"]["segments"][0]["start"] == 7
    assert detail["transitions"] == []
    assert client.get("/api/viewing-library/unprocessed").status_code == 404
    assert client.post("/api/viewing-library/ready").status_code == 405


def test_online_rounds_and_local_copy_do_not_change_review_mode(library):
    """Online reviews are viewable without a download or a transcript."""
    client, _, root = library
    db.create_online_video("remote", {"source_id": "abcdefghijk", "source_url": "https://youtu.be/abcdefghijk",
                                      "original_name": "Online VOD", "duration": 900, "width": 1280, "height": 720}, 100, 400)
    rounds("remote")
    response = client.get("/api/viewing-library/remote")
    assert response.status_code == 200
    detail = response.json()
    assert detail["start"] == 100 and detail["duration"] == 300
    assert detail["has_transitions"] and not detail["has_transcript"]
    assert detail["transitions"][0]["timestamp_seconds"] == 10.125
    local = root / "local.mp4"
    local.write_bytes(b"saved local copy")
    db.bind_local_copy("remote", local, "video/mp4", 1280, 720)
    detail = client.get("/api/viewing-library/remote").json()
    assert client.get(detail["content_url"], headers={"Range": "bytes=0-4"}).content == b"saved"
    assert db.get_video("remote")["mode"] == "online"


def test_catalogue_only_video_and_transcript_are_joined_without_import(library):
    """Explicit same-source transcripts can be read without creating reviews."""
    client, store, root = library
    file = root / "movie.mp4"
    file.write_bytes(b"movie")
    resource = store.publish(file, kind="video", source="example", metadata={"start": 0})
    text = root / "transcript.txt"
    text.write_text("Shared-only speech")
    store.publish(text, kind="text", source="example", metadata={"type": "transcript"})
    entry, = client.get("/api/viewing-library").json()
    assert entry["id"] == resource.reference
    assert client.get(f'/api/viewing-library/{entry["id"]}').json()["transcript"]["transcript"] == "Shared-only speech"
    assert db.list_videos() == []
    # A clip with another timeline must not borrow full-source transcript timing.
    store.publish(file, kind="video", source="example", metadata={"start": 200})
    assert len(client.get("/api/viewing-library").json()) == 1


def test_broken_transcript_does_not_block_video(library):
    """Missing artifacts have a recoverable transcript error beside the player."""
    client, store, root = library
    file = root / "movie.mp4"
    file.write_bytes(b"movie")
    store.publish(file, kind="video", source="example")
    file = root / "transcript.txt"
    file.write_text("speech")
    text = store.publish(file, kind="text", source="example", metadata={"type": "transcript"})
    store.resolve(text.reference).unlink()
    entry, = client.get("/api/viewing-library").json()
    detail = client.get(f'/api/viewing-library/{entry["id"]}').json()
    assert detail["transcript_error"] and detail["content_url"]


def test_both_artifacts_and_missing_video_keep_transcript_readable(library):
    """Removing media bytes must not hide an otherwise useful saved transcript."""
    client, _, root = library
    video(root, "both")
    transcript("both")
    rounds("both")
    detail = client.get("/api/viewing-library/both").json()
    assert detail["has_transcript"] and detail["has_transitions"]
    (root / "both.mp4").unlink()
    detail = client.get("/api/viewing-library/both").json()
    assert not detail["local_available"] and detail["transcript"]["transcript"] == "Saved speech"


def test_disabled_store_has_explicit_error(library, monkeypatch):
    """Disabled sharing is different from an empty library."""
    client, _, _ = library
    monkeypatch.setenv("TFT_MEDIA_DIR", "")
    assert client.get("/api/viewing-library").status_code == 503


def test_imported_shared_video_combines_transcript_and_rounds_once(library):
    """An independently imported review keeps its source artifact relationships."""
    client, store, root = library
    source = root / "shared.mp4"
    source.write_bytes(b"shared video")
    media = store.publish(source, kind="video", source="original", metadata={"video_id": "original"})
    source = root / "transcript.txt"
    source.write_text("Original transcript")
    store.publish(source, kind="text", source="transcription:original",
                  metadata={"type": "transcript", "video_id": "original"})
    db.create_video("imported", "shared.mp4", store.resolve(media.reference), "video/mp4", 300, 1280, 720, shared_media=True)
    rounds("imported")
    entry, = client.get("/api/viewing-library").json()
    assert entry["id"] == "imported" and entry["has_transcript"] and entry["has_transitions"]
    assert client.get("/api/viewing-library/imported").json()["transcript"]["transcript"] == "Original transcript"
