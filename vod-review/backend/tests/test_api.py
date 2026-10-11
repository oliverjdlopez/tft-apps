import asyncio
import json
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend import app as app_module
from backend import db as db_module


@pytest.fixture(autouse=True)
def local_media_mode(monkeypatch):
    """Keep local-download fixtures independent of suite catalogue reuse."""
    monkeypatch.setenv("TFT_MEDIA_DIR", "")


def make_video(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=11:r=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_supported_video_url_validation():
    assert app_module.is_supported_video_url("https://www.youtube.com/watch?v=abc")
    assert app_module.is_supported_video_url("https://youtu.be/abc")
    assert app_module.is_supported_video_url("https://clips.twitch.tv/example")
    assert not app_module.is_supported_video_url("https://notyoutube.com/watch?v=abc")
    assert not app_module.is_supported_video_url("file:///tmp/video.mp4")


def test_replay_source_url_validation():
    assert app_module.is_replay_source_url("https://www.youtube.com/@example")
    assert app_module.is_replay_source_url("https://youtube.com/channel/UC123")
    assert app_module.is_replay_source_url("https://www.twitch.tv/example_streamer")
    assert not app_module.is_replay_source_url("https://www.youtube.com/watch?v=abc")
    assert not app_module.is_replay_source_url("https://www.twitch.tv/videos/123")
    assert not app_module.is_replay_source_url("https://example.com/@channel")
    assert app_module.replay_discovery_url("https://www.twitch.tv/example_streamer") == (
        "https://www.twitch.tv/example_streamer/videos?filter=archives&sort=time"
    )


def test_replay_discovery_reads_flat_channel_metadata(monkeypatch: pytest.MonkeyPatch):
    captured_command = []

    def fake_run(command, *args, **kwargs):
        captured_command.extend(command)
        payload = {
            "channel": "Example Channel",
            "entries": [{
                "id": "abc123",
                "title": "Fresh tournament VOD",
                "url": "abc123",
                "duration": 3661,
                "upload_date": "20260915",
            }],
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)
    replays = app_module.discover_replays_for_source("https://www.youtube.com/@example")

    assert captured_command[-1] == "https://www.youtube.com/@example/videos"
    assert "--flat-playlist" in captured_command
    assert replays == [{
        "id": "youtube:abc123",
        "platform": "youtube",
        "title": "Fresh tournament VOD",
        "creator": "Example Channel",
        "url": "https://www.youtube.com/watch?v=abc123",
        "source_url": "https://www.youtube.com/@example",
        "thumbnail_url": None,
        "duration_seconds": 3661,
        "published_at": "2026-09-15T00:00:00+00:00",
    }]


def test_download_format_caps_quality_without_falling_back_above_the_cap():
    assert app_module.download_format("best") == (
        "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/best[vcodec^=avc1][ext=mp4]/best[ext=mp4]"
    )
    selector = app_module.download_format("720p")
    assert selector.count("height<=720") == 3
    assert "best[ext=mp4]" not in selector


def test_video_probe_uses_pyav_without_ffprobe(monkeypatch: pytest.MonkeyPatch):
    closed = False

    class Container:
        format = SimpleNamespace(name="mov,mp4,m4a,3gp,3g2,mj2")
        duration = None
        streams = SimpleNamespace(
            video=[
                SimpleNamespace(
                    duration=110,
                    time_base=Fraction(1, 10),
                    codec_context=SimpleNamespace(name="h264", width=1920, height=1080),
                )
            ]
        )

        def close(self):
            nonlocal closed
            closed = True

    fake_av = SimpleNamespace(open=lambda _path: Container(), time_base=1_000_000)
    monkeypatch.setitem(sys.modules, "av", fake_av)

    assert app_module.probe_video(Path("sample.mp4")) == {
        "duration": 11.0,
        "width": 1920,
        "height": 1080,
    }
    assert closed


def test_url_download_persists_video(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    db_module.init_db()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"test video")
    original_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        if "yt_dlp" in command:
            output_template = command[command.index("--output") + 1]
            output = Path(output_template.replace("%(ext)s", "mp4"))
            shutil.copyfile(source, output)
            output.with_suffix(".info.json").write_text("{}")
            stdout = f"FRAMEWISE_PATH={output}\nFRAMEWISE_TITLE=Imported test VOD\n"
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        app_module,
        "probe_video",
        lambda _path: {"duration": 11.0, "width": 64, "height": 64},
    )
    video = app_module.download_video_url("https://youtu.be/example")
    assert video["original_name"] == "Imported test VOD.mp4"
    assert video["duration"] > 10
    assert db_module.video_path(video["id"]).exists()


def test_url_download_passes_selected_range_to_yt_dlp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    db_module.init_db()
    captured_command = []

    def fake_run(command, *args, **kwargs):
        captured_command.extend(command)
        output_template = command[command.index("--output") + 1]
        output = Path(output_template.replace("%(ext)s", "mp4"))
        output.write_bytes(b"clipped video")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"FRAMEWISE_PATH={output}\nFRAMEWISE_TITLE=Clipped VOD\n",
            stderr="",
        )

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        app_module,
        "probe_video",
        lambda _path: {"duration": 60.0, "width": 64, "height": 64},
    )

    video = app_module.download_video_url("https://youtu.be/example", 90, 150, quality="480p")

    section_index = captured_command.index("--download-sections")
    assert captured_command[section_index + 1] == "*90.000000-150.000000"
    assert "height<=480" in captured_command[captured_command.index("--format") + 1]
    assert "--force-keyframes-at-cuts" in captured_command
    assert video["duration"] == 60


def test_url_download_reports_monotonic_combined_stream_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    db_module.init_db()
    captured_command: list[str] = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            captured_command.extend(command)
            output_template = command[command.index("--output") + 1]
            output = Path(output_template.replace("%(ext)s", "mp4"))
            output.write_bytes(b"downloaded video")
            self.stdout = iter([
                'FRAMEWISE_PROGRESS=137\tavc1\tnone\t120\t{"status":"downloading","downloaded_bytes":50,"total_bytes":100}\n',
                'FRAMEWISE_PROGRESS=137\tavc1\tnone\t120\t{"status":"finished","downloaded_bytes":100,"total_bytes":100}\n',
                'FRAMEWISE_PROGRESS=140\tnone\tmp4a\t120\t{"status":"downloading","downloaded_bytes":50,"total_bytes":100}\n',
                'FRAMEWISE_PROGRESS=140\tnone\tmp4a\t120\t{"status":"finished","downloaded_bytes":100,"total_bytes":100}\n',
                f"FRAMEWISE_PATH={output}\n",
                "FRAMEWISE_TITLE=Progress test VOD\n",
            ])

        def wait(self):
            return 0

    monkeypatch.setattr(app_module.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(app_module, "probe_video", lambda _path: {"duration": 120.0, "width": 64, "height": 64})
    updates: list[float] = []

    video = app_module.download_video_url("https://youtu.be/example", progress_callback=updates.append)

    separator_index = captured_command.index("--")
    assert captured_command.index("--progress-template") < separator_index
    assert captured_command.index("--no-quiet") < separator_index
    assert captured_command[separator_index + 1] == "https://youtu.be/example"
    assert updates == sorted(updates)
    assert updates == pytest.approx([23.75, 47.5, 71.25, 95.0])
    assert video["original_name"] == "Progress test VOD.mp4"


def test_clipped_download_uses_ffmpeg_playback_time_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    db_module.init_db()
    captured_command: list[str] = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            captured_command.extend(command)
            output_template = command[command.index("--output") + 1]
            output = Path(output_template.replace("%(ext)s", "mp4"))
            output.write_bytes(b"clipped video")
            self.stdout = iter([
                'FRAMEWISE_PROGRESS=137\tavc1\tmp4a\t300\t{"status":"downloading","downloaded_bytes":1,"total_bytes":100}\n',
                "out_time=00:00:15.000000\n",
                "out_time=00:00:30.000000\n",
                f"FRAMEWISE_PATH={output}\n",
                "FRAMEWISE_TITLE=Clipped progress VOD\n",
            ])

        def wait(self):
            return 0

    monkeypatch.setattr(app_module.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(app_module, "probe_video", lambda _path: {"duration": 60.0, "width": 64, "height": 64})
    updates: list[float] = []

    app_module.download_video_url("https://youtu.be/example", 90, 150, updates.append)

    assert "--downloader-args" in captured_command
    assert captured_command[captured_command.index("--downloader-args") + 1] == "ffmpeg:-progress pipe:2 -nostats"
    assert updates == sorted(updates)
    assert updates[-2:] == pytest.approx([23.75, 47.5])


def test_download_task_progress_is_persisted_and_monotonic(tmp_path: Path):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    db_module.init_db()

    db_module.create_download_task("download-id")
    db_module.update_download_task("download-id", status="running", progress=42.5)
    db_module.update_download_task("download-id", progress=10)

    task = db_module.get_download_task("download-id")
    assert task["status"] == "running"
    assert task["progress"] == 42.5


def test_checkpointed_download_becomes_resumable_after_restart(tmp_path: Path):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DOWNLOAD_DIR = db_module.DATA_DIR / "downloads"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    db_module.init_db()
    db_module.create_download_task(
        "resumable-id",
        url="https://youtu.be/example",
        start_seconds=60,
        end_seconds=600,
        checkpoint_interval_seconds=120,
        quality="480p",
    )
    db_module.update_download_task("resumable-id", status="running", progress=38)

    db_module.init_db()

    task = db_module.get_resumable_download_task()
    assert task is not None
    assert task["task_id"] == "resumable-id"
    assert task["status"] == "paused"
    assert task["progress"] == 38
    assert db_module.get_download_request("resumable-id")["quality"] == "480p"


def test_video_url_request_rejects_reversed_range():
    from pydantic import ValidationError
    from backend.models import VideoUrlRequest

    with pytest.raises(ValidationError, match="Download end must be after its start"):
        VideoUrlRequest(url="https://youtu.be/example", start_seconds=120, end_seconds=60)


def test_checkpointed_download_pauses_and_resumes_from_completed_chunks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DOWNLOAD_DIR = db_module.DATA_DIR / "downloads"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    db_module.init_db()
    monkeypatch.setattr(app_module, "_download_url_metadata", lambda _url: {
        "duration": 180,
        "title": "Checkpoint VOD",
        "formats": [
            {"url": "https://media/video", "ext": "mp4", "vcodec": "avc1.640020", "acodec": "none", "height": 720},
            {"url": "https://media/audio", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128},
        ],
    })
    monkeypatch.setattr(app_module, "probe_video", lambda _path: {"duration": 180.0, "width": 64, "height": 64})
    downloaded_ranges: list[tuple[float, float]] = []

    selected_qualities: list[str] = []

    def fake_chunk(_url, template, start, end, progress_callback, quality):
        downloaded_ranges.append((start, end))
        selected_qualities.append(quality)
        path = Path(str(template).replace("%(ext)s", "mp4"))
        path.write_bytes(f"{start}-{end}".encode())
        progress_callback(99)
        return path

    def fake_concat(parts, destination):
        destination.write_bytes(b"".join(part.read_bytes() for part in parts))

    monkeypatch.setattr(app_module, "_download_checkpoint_chunk", fake_chunk)
    monkeypatch.setattr(app_module, "_concat_download_checkpoints", fake_concat)

    with pytest.raises(app_module.DownloadPaused) as paused:
        app_module.download_video_url_checkpointed(
            "checkpoint-task", "https://youtu.be/example", 0, 180, 60, lambda _progress: None, lambda: True, "1080p",
        )

    assert downloaded_ranges == [(0, 60)]
    assert (db_module.DOWNLOAD_DIR / "checkpoint-task" / "checkpoint-000000.mp4").is_file()
    assert paused.value.video["original_name"] == "Checkpoint VOD (paused checkpoint).mp4"
    assert db_module.video_path(paused.value.video["id"]).is_file()

    video = app_module.download_video_url_checkpointed(
        "checkpoint-task", "https://youtu.be/example", 0, 180, 60, lambda _progress: None, lambda: False, "1080p",
    )

    assert downloaded_ranges == [(0, 60), (60, 120), (120, 180)]
    assert selected_qualities == ["1080p", "1080p", "1080p"]
    assert video["id"] == "checkpoint-task"
    assert db_module.video_path(video["id"]).is_file()
    assert not (db_module.DOWNLOAD_DIR / "checkpoint-task").exists()
    assert len(db_module.list_videos()) == 2


def test_checkpoint_interval_must_be_at_least_one_minute():
    from pydantic import ValidationError
    from backend.models import VideoUrlRequest

    with pytest.raises(ValidationError, match="greater than or equal to 60"):
        VideoUrlRequest(url="https://youtu.be/example", checkpoint_interval_seconds=30)


def test_download_quality_must_be_supported():
    from pydantic import ValidationError
    from backend.models import VideoUrlRequest

    assert VideoUrlRequest(url="https://youtu.be/example").quality == "720p"
    with pytest.raises(ValidationError, match="Input should be"):
        VideoUrlRequest(url="https://youtu.be/example", quality="1440p")


def test_classification_results_are_persisted(tmp_path: Path):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    db_module.init_db()
    video = db_module.create_video(
        "video-id",
        "sample.mp4",
        tmp_path / "sample.mp4",
        "video/mp4",
        20.0,
        1920,
        1080,
    )
    db_module.save_bounding_box(
        video["id"],
        {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "frame_time": 0.0},
    )
    _, created = db_module.create_processing_job(video["id"], "job-id", 4, 5.0)
    assert created
    assert db_module.begin_job("job-id") is not None
    db_module.complete_job(
        "job-id",
        video["id"],
        [(5.0, 5.02, "round_07", 0.95)],
        processed=1,
        total=1,
        device="cpu",
    )

    result = db_module.get_video(video["id"])["current_job"]["results"][0]
    assert result["class_label"] == "round_07"
    assert result["confidence"] == 0.95
    assert result["timing_error_ms"] == 20.0


def test_round_export_splices_clips_with_ffmpeg(tmp_path: Path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "export.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=4:r=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
        ],
        check=True,
        capture_output=True,
    )

    app_module.build_round_export(
        source,
        output,
        [
            app_module.RoundExportClip(label="11", start_seconds=0, end_seconds=1),
            app_module.RoundExportClip(label="21", start_seconds=2, end_seconds=3),
        ],
    )

    assert output.exists()
    assert 1.9 <= app_module.probe_video(output)["duration"] <= 2.1
    assert app_module.source_has_audio(output)


def test_playback_assets_are_segmented_and_served(tmp_path: Path):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    db_module.init_db()
    source = db_module.VIDEO_DIR / "video-id.mp4"
    make_video(source)
    db_module.create_video("video-id", "Long VOD.mp4", source, "video/mp4", 11, 64, 64)

    app_module.build_playback_assets("video-id")

    directory = app_module.playback_directory("video-id")
    manifest = (directory / "index.m3u8").read_text()
    assert "#EXTM3U" in manifest
    assert "#EXT-X-MAP:URI=\"init.mp4\"" in manifest
    assert list(directory.glob("segment-*.m4s"))

    async def exercise_api():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            status = await client.get("/api/videos/video-id/playback")
            assert status.json()["status"] == "ready"
            manifest_response = await client.get("/api/videos/video-id/playback/index.m3u8")
            assert manifest_response.status_code == 200
            assert manifest_response.headers["content-type"].startswith("application/vnd.apple.mpegurl")
            assert manifest_response.headers["cache-control"] == "no-cache"
            segment_name = next(directory.glob("segment-*.m4s")).name
            segment_response = await client.get(f"/api/videos/video-id/playback/{segment_name}")
            assert segment_response.status_code == 200
            assert "immutable" in segment_response.headers["cache-control"]

    asyncio.run(exercise_api())


def test_round_export_endpoint_returns_attachment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    db_module.init_db()
    source = db_module.VIDEO_DIR / "video-id.mp4"
    source.write_bytes(b"source")
    db_module.create_video("video-id", "My VOD.mp4", source, "video/mp4", 10, 64, 64)

    def fake_export(_source, output, _clips):
        output.write_bytes(b"exported-video")

    async def direct_to_thread(function, *args):
        return function(*args)

    monkeypatch.setattr(app_module, "build_round_export", fake_export)
    monkeypatch.setattr(app_module.asyncio, "to_thread", direct_to_thread)

    async def exercise_api():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await asyncio.wait_for(
                client.post(
                    "/api/videos/video-id/round-export",
                    json={
                        "game_number": 2,
                        "clips": [{"label": "32", "start_seconds": 1, "end_seconds": 3}],
                    },
                ),
                timeout=5,
            )
            assert response.status_code == 200
            assert response.content == b"exported-video"
            assert response.headers["content-type"] == "video/mp4"
            assert "My-VOD-game-2-rounds.mp4" in response.headers["content-disposition"]

            invalid = await asyncio.wait_for(
                client.post(
                    "/api/videos/video-id/round-export",
                    json={
                        "game_number": 2,
                        "clips": [{"label": "32", "start_seconds": 9, "end_seconds": 11}],
                    },
                ),
                timeout=5,
            )
            assert invalid.status_code == 400

    asyncio.run(exercise_api())


def test_upload_box_process_range_and_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    db_module.DATA_DIR = tmp_path / "data"
    db_module.VIDEO_DIR = db_module.DATA_DIR / "videos"
    db_module.DB_PATH = db_module.DATA_DIR / "vod.sqlite3"
    source = tmp_path / "red.mp4"
    make_video(source)

    class FakeClassifier:
        device_label = "cpu"

        def predict_batch(self, crops):
            return [("round_07", 0.95) for _ in crops]

    monkeypatch.setattr(app_module, "get_ocr_classifier", lambda _labels: FakeClassifier())

    async def exercise_api():
        app_module.startup()
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            invalid_link = await client.post("/api/videos/from-url", json={"url": "https://example.com/video"})
            assert invalid_link.status_code == 400
            with source.open("rb") as handle:
                response = await client.post("/api/videos", files={"file": ("red.mp4", handle, "video/mp4")})
            assert response.status_code == 201, response.text
            video = response.json()
            assert video["duration"] > 10

            range_response = await client.get(f"/api/videos/{video['id']}/content", headers={"Range": "bytes=0-15"})
            assert range_response.status_code == 206
            assert range_response.headers["content-range"].startswith("bytes 0-15/")
            assert len(range_response.content) == 16

            full_response = await client.get(f"/api/videos/{video['id']}/content")
            assert full_response.status_code == 200
            assert "content-range" not in full_response.headers

            box_response = await client.put(
                f"/api/videos/{video['id']}/bounding-box",
                json={"x": 0, "y": 0, "width": 1, "height": 1, "frame_time": 1},
            )
            assert box_response.status_code == 200
            invalid_batch = await client.post(f"/api/videos/{video['id']}/process", json={"batch_size": 0})
            assert invalid_batch.status_code == 422
            process_response = await client.post(
                f"/api/videos/{video['id']}/process",
                json={"batch_size": 2, "sample_interval_seconds": 2.5},
            )
            assert process_response.status_code == 202
            assert process_response.json()["batch_size"] == 2
            assert process_response.json()["sample_interval_seconds"] == 2.5

            completed = None
            for _ in range(100):
                details = (await client.get(f"/api/videos/{video['id']}")).json()
                job = details.get("current_job")
                active = details.get("active_job")
                if job and job["status"] == "completed" and active is None:
                    completed = job
                    break
                if active and active["status"] == "failed":
                    pytest.fail(active["error"])
                await asyncio.sleep(0.05)
            assert completed is not None
            assert len(completed["results"]) == 1
            assert completed["results"][0]["timestamp_seconds"] == 0
            assert completed["results"][0]["scheduled_timestamp_seconds"] == 0
            assert abs(completed["results"][0]["timing_error_ms"]) < 100
            assert completed["results"][0]["class_label"] == "round_07"
            assert completed["results"][0]["confidence"] == 0.95
            assert completed["device"] == "cpu"
            assert completed["batch_size"] == 2
            assert completed["sample_interval_seconds"] == 2.5  # retained for legacy jobs
            assert completed["collected_samples"] == completed["total_samples"]
            assert completed["phase"] == "completed"
            assert completed["max_timing_error_ms"] < 100

            original_processor = app_module.process_video_all_frames
            monkeypatch.setattr(
                app_module,
                "process_video_all_frames",
                lambda *_args, **_kwargs: pytest.fail("rerun decoded the video"),
            )
            rerun_response = await client.post(
                f"/api/videos/{video['id']}/process",
                json={
                    "batch_size": 2,
                    "sample_interval_seconds": 2.5,
                    "reuse_cached_crops": True,
                },
            )
            assert rerun_response.status_code == 202
            assert rerun_response.json()["reuse_cached_crops"] is True
            rerun = None
            for _ in range(100):
                details = (await client.get(f"/api/videos/{video['id']}")).json()
                candidate = details.get("current_job")
                active = details.get("active_job")
                if candidate and candidate["id"] == rerun_response.json()["id"] and active is None:
                    rerun = candidate
                    break
                if active and active["status"] == "failed":
                    pytest.fail(active["error"])
                await asyncio.sleep(0.05)
            monkeypatch.setattr(app_module, "process_video_all_frames", original_processor)
            assert rerun is not None
            assert rerun["source_job_id"] == completed["id"]
            assert rerun["results"] == completed["results"]
            assert (await client.get("/api/videos")).json()[0]["id"] == video["id"]
        app_module.shutdown()

    asyncio.run(exercise_api())
