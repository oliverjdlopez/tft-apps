"""Test Drive authorization, authoritative round timing, upload recovery and media."""

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException

from backend.gdrive import router as routes
from backend.gdrive import utils
from backend.gdrive.models import DriveUploadOptions, UploadJob


def video_payload() -> dict:
    """Provide transitions with overlap, a repeated round and a short final clip."""
    return {"id": "video", "original_name": "VOD.mp4", "duration": 160,
            "current_job": {"id": "classification", "status": "completed", "results": [
                {"timestamp_seconds": 5.25, "class_label": "11"},
                {"timestamp_seconds": 20, "class_label": "12"},
                {"timestamp_seconds": 130, "class_label": "11"},
                {"timestamp_seconds": 160, "class_label": "12"},
                {"timestamp_seconds": 150, "class_label": "unknown"},
            ]}}


def test_clips_use_actual_round_start_and_do_not_stop_at_next_round():
    """Export all transitions, including repeated labels across games and tails."""
    clips = utils.round_clips(video_payload())
    assert clips == [{"label": "11", "start": 5.25, "duration": 60},
                     {"label": "12", "start": 20.0, "duration": 60},
                     {"label": "11", "start": 130.0, "duration": 30}]


@pytest.mark.parametrize("job", [None, {"status": "running"}, {"status": "completed", "results": []}])
def test_upload_requires_completed_round_results(job):
    """Avoid encoding empty batches or unfinished classifications."""
    video = video_payload()
    video["current_job"] = job
    with pytest.raises(HTTPException) as error:
        utils.round_clips(video)
    assert error.value.status_code == 400


def test_oauth_callback_requires_browser_state_and_stores_private_token(monkeypatch, tmp_path):
    """Reject foreign callbacks and persist refresh tokens without exposing them."""
    config = {"client_id": "client", "client_secret": "secret", "redirect_uri": "http://test/api/gdrive/callback"}
    monkeypatch.setattr(routes, "oauth_config", lambda: config)
    monkeypatch.setattr(routes, "exchange_token", lambda fields: {"refresh_token": "private-refresh"})
    monkeypatch.setenv("VOD_GDRIVE_TOKEN_FILE", str(tmp_path / "token.json"))
    routes.STATES.clear()
    app = FastAPI()
    app.include_router(routes.router)

    async def check():
        """Exercise a browser-bound authorization round trip through ASGI."""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/gdrive/connect")
            state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
            assert (await client.get("/api/gdrive/callback?state=wrong&code=code")).status_code == 400
            response = await client.get(f"/api/gdrive/callback?state={state}&code=code")
            assert response.status_code == 200
            assert "private-refresh" not in response.text
            assert (await client.get(f"/api/gdrive/callback?state={state}&code=code")).status_code == 400
    asyncio.run(check())
    assert json.loads((tmp_path / "token.json").read_text())["refresh_token"] == "private-refresh"
    assert (tmp_path / "token.json").stat().st_mode & 0o777 == 0o600


def test_retry_retains_completed_files_and_cleans_temporary_media(monkeypatch, tmp_path):
    """Resume at the failed clip and remove encoded files on every outcome."""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    job = UploadJob("upload", "video", "classification", utils.round_clips(video_payload()))
    encoded = []
    uploaded_keys = []
    fail = True

    def encode(source, output, clip):
        """Record temporary paths while replacing expensive media encoding."""
        output.write_bytes(b"clip")
        encoded.append(output)

    def upload(path, folder, token, key):
        """Fail the second upload once to exercise partial-batch recovery."""
        if key == "upload-1" and fail:
            raise HTTPException(502, "offline")
        uploaded_keys.append(key)
        return {"id": key}

    monkeypatch.setattr(routes, "access_token", lambda: "token")
    monkeypatch.setattr(routes, "create_folder", lambda *args: "folder")
    monkeypatch.setattr(routes, "render_clip", encode)
    monkeypatch.setattr(routes, "upload_clip", upload)
    routes.run_upload(job, source, "VOD")
    assert (job.status, job.completed, job.error) == ("failed", 1, "offline")
    assert all(not path.exists() for path in encoded)
    fail = False
    job.status, job.error = "running", None
    routes.run_upload(job, source, "VOD")
    assert (job.status, job.completed) == ("completed", 3)
    assert uploaded_keys == ["upload-0", "upload-1", "upload-2"]
    assert all(not path.exists() for path in encoded)


def test_start_uses_stored_results_and_deduplicates_clicks(monkeypatch, tmp_path):
    """Reuse a running batch when multiple POSTs arrive for the same video."""
    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(routes.db, "get_video", lambda video_id: video_payload())
    monkeypatch.setattr(routes.db, "video_path", lambda video_id: source)
    monkeypatch.setattr(routes, "access_token", lambda: "token")
    monkeypatch.setattr(routes, "JOBS", {})

    async def check():
        """Run concurrent starts without executing queued background workers."""
        tasks = [BackgroundTasks(), BackgroundTasks()]
        first, second = await asyncio.gather(*(routes.start_upload("video", SimpleNamespace(headers={"content-type": "application/json"}), task, DriveUploadOptions()) for task in tasks))
        assert first["id"] == second["id"]
        assert first["total"] == 3
        assert sum(len(task.tasks) for task in tasks) == 1
    asyncio.run(check())


def test_resumable_upload_sends_bounded_chunks(monkeypatch, tmp_path):
    """Check Drive metadata and byte ranges, including the final partial chunk."""
    path = tmp_path / "round.mp4"
    path.write_bytes(b"x" * (8 * 1024 * 1024 + 7))
    requests = []

    def request(url, **kwargs):
        """Model Drive's session creation and incomplete chunk acknowledgement."""
        requests.append((url, kwargs))
        if kwargs.get("method") == "POST":
            return {}, {"Location": "https://www.googleapis.com/session"}, 200
        if kwargs.get("method") == "PUT":
            return ({"id": "uploaded"}, {}, 200) if len(kwargs["data"]) == 7 else ({}, {"Range": "bytes=0-8388607"}, 308)
        return {"files": []}, {}, 200

    monkeypatch.setattr(utils, "google_request", request)
    assert utils.upload_clip(path, "folder", "token", "key")["id"] == "uploaded"
    chunks = [kwargs for _, kwargs in requests if kwargs.get("method") == "PUT"]
    assert len(chunks) == 2
    assert chunks[0]["headers"]["Content-Range"] == "bytes 0-8388607/8388615"
    assert chunks[1]["headers"]["Content-Range"] == "bytes 8388608-8388614/8388615"
    metadata = json.loads(requests[1][1]["data"])
    assert metadata["parents"] == ["folder"]
    assert metadata["appProperties"] == {"roundClip": "key"}


def test_upload_recovers_lost_success_response(monkeypatch, tmp_path):
    """Do not upload another copy when Drive already has the stable clip key."""
    monkeypatch.setattr(utils, "google_request", lambda *args, **kwargs: ({"files": [{"id": "existing"}]}, {}, 200))
    assert utils.upload_clip(tmp_path / "not-needed.mp4", "folder", "token", "key") == {"id": "existing"}


@pytest.mark.parametrize("audio", [True, False])
def test_real_ffmpeg_clip_duration_and_timing(tmp_path, audio):
    """Verify accurate non-keyframe seeks and one-minute output with optional audio."""
    import av
    source = tmp_path / "source.mp4"
    output = tmp_path / "clip.mp4"
    command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=65"]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=1000:duration=65", "-c:a", "aac"]
    subprocess.run(command + ["-c:v", "libx264", "-g", "100", str(source)], check=True, capture_output=True)
    utils.render_clip(source, output, {"start": 2.5, "duration": 60})
    with av.open(str(output)) as container:
        assert abs(container.duration / av.time_base - 60) < 0.15
        assert bool(container.streams.audio) is audio
        first = next(container.decode(video=0))
        assert abs(float(first.pts * first.time_base)) < 0.1
    # Compare decoded pixels: the export must begin at 2.5 s, not the earlier keyframe.
    with av.open(str(source)) as container:
        expected = next(frame for frame in container.decode(video=0) if float(frame.pts * frame.time_base) >= 2.5)
        import numpy as np
        assert np.abs(first.to_ndarray(format="rgb24").astype(float) - expected.to_ndarray(format="rgb24")).mean() < 8


def test_simple_cross_origin_posts_cannot_start_uploads():
    """Require JSON so the browser applies the backend's CORS preflight policy."""
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.start_upload("video", SimpleNamespace(headers={}), BackgroundTasks(), DriveUploadOptions()))
    assert error.value.status_code == 415


def test_missing_credentials_gives_actionable_setup_error(monkeypatch):
    """Explain setup instead of starting an upload that cannot be authorized."""
    monkeypatch.delenv("VOD_GDRIVE_CLIENT_FILE", raising=False)
    with pytest.raises(HTTPException) as error:
        utils.access_token()
    assert error.value.status_code == 503
    assert "VOD_GDRIVE_CLIENT_FILE" in error.value.detail


def test_google_errors_do_not_echo_credentials(monkeypatch):
    """Keep sensitive request URLs and provider bodies out of API errors."""
    from urllib.error import HTTPError

    def fail(*args, **kwargs):
        """Simulate a Google error whose URL contains an upload-session secret."""
        raise HTTPError("https://www.googleapis.com/?secret=private", 403, "private body", {}, None)

    monkeypatch.setattr(utils, "urlopen", fail)
    with pytest.raises(HTTPException) as error:
        utils.google_request("https://www.googleapis.com/")
    assert "private" not in error.value.detail
    assert "403" in error.value.detail


@pytest.mark.parametrize("content,connected", [(None, False), ("invalid json", False), ("[]", False), ('{"refresh_token":""}', False), ('{"refresh_token":"private"}', True)])
def test_connection_status_reports_saved_authorization_without_secrets(monkeypatch, tmp_path, content, connected):
    """Distinguish absent and saved grants without exposing their contents."""
    path = tmp_path / "token.json"
    monkeypatch.setenv("VOD_GDRIVE_TOKEN_FILE", str(path))
    if content is not None:
        path.write_text(content)
    assert routes.google_status() == {"connected": connected}


def test_configurable_key_rounds_offset_and_duration():
    """Match the UI key rounds and clamp shifted clips at the source boundaries."""
    video = video_payload()
    video['current_job']['results'] = [
        {'timestamp_seconds': time, 'class_label': label}
        for time, label in [(5, '11'), (20, '12'), (40, '31'), (60, '3-2'), (80, '42'), (100, '43'), (150, '51')]
    ]
    options = DriveUploadOptions(key_rounds_only=True, offset_seconds=-10, duration_seconds=45)
    clips = utils.round_clips(video, options)
    assert [clip['label'] for clip in clips] == ['11', '12', '31', '3-2', '42', '51']
    assert [clip['start'] for clip in clips] == [0, 10, 30, 50, 70, 140]
    assert [clip['duration'] for clip in clips] == [45, 45, 45, 45, 45, 20]
    shifted = utils.round_clips(video, DriveUploadOptions(offset_seconds=20, duration_seconds=10))
    assert len(shifted) == 6
    assert shifted[0]['start'] == 25
    assert all(clip['duration'] == 10 for clip in shifted)


@pytest.mark.parametrize('fields', [
    {'duration_seconds': 0}, {'duration_seconds': 181}, {'duration_seconds': float('nan')},
    {'offset_seconds': float('inf')}, {'offset_seconds': -3601}, {'offset_seconds': 3601},
])
def test_invalid_upload_timing_is_rejected(fields):
    """Reject out-of-range and non-finite timing before encoding or uploading."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DriveUploadOptions(**fields)


def test_changed_settings_start_new_batch_and_same_settings_reuse(monkeypatch, tmp_path):
    """Do not silently reuse completed exports when the requested timing changes."""
    source = tmp_path / 'source.mp4'
    source.touch()
    monkeypatch.setattr(routes.db, 'get_video', lambda video_id: video_payload())
    monkeypatch.setattr(routes.db, 'video_path', lambda video_id: source)
    monkeypatch.setattr(routes, 'access_token', lambda: 'token')
    monkeypatch.setattr(routes, 'JOBS', {})

    async def check():
        """Exercise settings identity without executing the queued workers."""
        request = SimpleNamespace(headers={'content-type': 'application/json'})
        first = await routes.start_upload('video', request, BackgroundTasks(), DriveUploadOptions())
        routes.JOBS['video'].status = 'completed'
        same = await routes.start_upload('video', request, BackgroundTasks(), DriveUploadOptions())
        assert same['id'] == first['id']
        changed = await routes.start_upload('video', request, BackgroundTasks(), DriveUploadOptions(duration_seconds=30))
        assert changed['id'] != first['id']
        assert changed['options']['duration_seconds'] == 30
    asyncio.run(check())


@pytest.mark.parametrize('label', [f'1{round}' for round in range(1, 8)] + [f'1-{round}' for round in range(1, 8)])
def test_key_uploads_include_every_stage_one_round(label):
    """Keep upload filtering aligned with the UI for every stage-one label."""
    video = video_payload()
    video['current_job']['results'] = [{'timestamp_seconds': 5, 'class_label': label}]
    assert utils.round_clips(video, DriveUploadOptions(key_rounds_only=True))[0]['label'] == label
