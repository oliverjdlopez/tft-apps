"""Exercise stream detection and consent with real local media."""
import asyncio
import subprocess

import httpx
import pytest

from backend import app, db
from backend.media_store.resources import ResourceStore


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """Isolate media, task records, and shared publication."""
    for key, value in {"DATA_DIR": tmp_path, "VIDEO_DIR": tmp_path / "videos", "DOWNLOAD_DIR": tmp_path / "downloads", "DB_PATH": tmp_path / "test.sqlite3"}.items():
        monkeypatch.setattr(db, key, value)
    monkeypatch.setenv("TFT_MEDIA_DIR", str(tmp_path / "shared"))
    db.init_db()
    monkeypatch.setattr(app, "start_playback_preparation", lambda _: None)
    return tmp_path


@pytest.mark.parametrize("video", [False, True])
def test_stream_detection_and_consent(uploads, monkeypatch, video):
    """An audio MP4 needs consent; silent video imports normally."""
    path = uploads / "input.mp4"
    source = "color=c=red:s=64x64:d=0.2" if video else "sine=frequency=440:duration=0.2"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", source, str(path)], check=True, capture_output=True)
    calls = []

    def recognize(path, progress_callback=None):
        """Return deterministic text without model loading."""
        calls.append(path)
        return app.AudioTranscription(transcript="hello", language="en", segments=[])

    monkeypatch.setattr(app, "_transcribe_audio_file", recognize)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://test") as client:
            response = await client.post("/api/uploads", files={"file": ("audio.mp4", path.read_bytes(), "video/mp4")})
            assert response.status_code == 201
            payload = response.json()
            assert calls == []
            if video:
                assert payload["kind"] == "video"
                return
            assert payload["kind"] == "audio"
            task_id = payload["upload_id"]
            assert (await client.get(f"/api/transcriptions/{task_id}")).status_code == 404
            assert (await client.get("/api/videos")).json() == []
            assert (await client.post(f"/api/uploads/{task_id}/transcription")).status_code == 202
            await app.TRANSCRIPTION_TASKS[task_id]
            assert db.get_transcription_task(task_id)["status"] == "completed"
            assert len(calls) == 1
            assert (await client.post(f"/api/uploads/{task_id}/transcription")).json()["status"] == "completed"
            assert len(calls) == 1
            assert len(ResourceStore(uploads / "shared").find(kind="text")) == 1
            assert (await client.delete(f"/api/uploads/{task_id}")).status_code == 409
            pending = (await client.post("/api/uploads", files={"file": ("second.mp4", path.read_bytes())})).json()
            assert (await client.delete(f"/api/uploads/{pending['upload_id']}")).status_code == 204
            assert not (uploads / "audio-uploads" / pending["upload_id"]).exists()
            assert len(calls) == 1
    asyncio.run(scenario())


def test_invalid_upload_is_removed(uploads):
    """Reject unreadable files without leaving input behind."""
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://test") as client:
            response = await client.post("/api/uploads", files={"file": ("fake.mp4", b"not media")})
            assert response.status_code == 400
            assert not list(db.VIDEO_DIR.iterdir())
    asyncio.run(scenario())
