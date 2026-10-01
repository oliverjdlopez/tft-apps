"""Shared catalog integration with app-owned records and deletion semantics."""

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from backend import app, db
from backend.media_store import MediaStore
from backend.media_store.models import MediaRequest
from backend.media_store.resources import ResourceStore
from backend.tests.test_api import make_video


@pytest.fixture
def shared_media(tmp_path, monkeypatch):
    """Keep both catalog and review DB isolated from user media."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "vod")
    monkeypatch.setattr(db, "VIDEO_DIR", tmp_path / "vod" / "videos")
    monkeypatch.setattr(db, "DOWNLOAD_DIR", tmp_path / "vod" / "downloads")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "vod" / "vod.sqlite3")
    monkeypatch.setenv("TFT_MEDIA_DIR", str(tmp_path / "shared"))
    db.init_db()
    source = tmp_path / "original.mp4"
    make_video(source)
    return MediaStore(tmp_path / "shared"), source


def test_cached_import_and_delete_leave_shared_bytes(shared_media, monkeypatch):
    """Deleting either independent review must leave the shared source intact."""
    store, source = shared_media
    cached = store.obtain(MediaRequest("https://youtu.be/abc", "video", profile="video:720p"), lambda: source)

    def unexpected(*args, **kwargs):
        raise AssertionError("unexpected remote download")

    monkeypatch.setattr(app, "download_video_url_local", unexpected)
    first = app.download_video_url("https://youtube.com/watch?v=abc")
    second = app.download_video_url("https://youtu.be/abc")
    assert first["id"] != second["id"]
    assert db.video_path(first["id"]) == cached
    assert db.video_is_shared(first["id"])
    monkeypatch.delenv("TFT_MEDIA_DIR")
    asyncio.run(app.delete_video(first["id"]))
    assert cached.is_file()
    assert db.video_path(second["id"]).is_file()


def test_download_rebinds_original_and_preserves_task_metadata(shared_media, monkeypatch):
    """A cache miss retains its review ID, then moves ownership to the catalog."""
    store, source = shared_media
    local = db.VIDEO_DIR / "review.mp4"

    def produce(*args, **kwargs):
        shutil.copyfile(source, local)
        return app.persist_video(local, "My VOD.mp4", "video/mp4", "review")

    monkeypatch.setattr(app, "download_video_url_local", produce)
    result = app.download_video_url("https://youtu.be/abc")
    assert result["id"] == "review"
    assert result["original_name"] == "My VOD.mp4"
    assert db.video_is_shared("review")
    assert db.video_path("review").is_relative_to(store.root)
    assert not local.exists()


def test_paused_download_is_not_published_as_complete(shared_media, monkeypatch):
    """Pause/resume keeps its existing exception contract and local partial data."""
    store, source = shared_media

    def pause(*args, **kwargs):
        raise app.DownloadPaused({"id": "partial"})

    monkeypatch.setattr(app, "download_video_url_checkpointed_local", pause)
    with pytest.raises(app.DownloadPaused):
        app.download_video_url_checkpointed("task", "https://youtu.be/abc", None, None, 60, lambda _: None, lambda: True)
    with store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM media_assets").fetchone()[0] == 0


def test_audio_download_publication_and_reuse(shared_media, monkeypatch):
    """Audio-only downloads enter the same catalogue and avoid subsequent transfers."""
    store, _ = shared_media
    audio = db.DOWNLOAD_DIR / "source.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=duration=1", "-c:a", "aac", str(audio)], check=True)
    monkeypatch.setattr(app, "download_audio_url_local", lambda *args: audio)
    published = app.download_audio_url("https://youtu.be/audio", "task")
    assert published.is_relative_to(store.root)
    assert published.is_file()
    assert not audio.exists()
    resources = ResourceStore(store.root).find(source="youtube:audio", kind="audio")
    assert len(resources) == 1
    assert ResourceStore(store.root).resolve(resources[0].reference).read_bytes() == published.read_bytes()

    def unexpected(*args):
        """Fail if an alias of a cached source attempts a remote transfer."""
        raise AssertionError("unexpected audio transfer")

    monkeypatch.setattr(app, "download_audio_url_local", unexpected)
    assert app.download_audio_url("https://youtube.com/watch?v=audio", "another") == published
