"""Exercise creator scheduling and imports with local SQLite and fake remote media."""

import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
import httpx
from pydantic import ValidationError
import pytest

from backend import app as app_module, db
from backend.replay_automation import discovery, store
from backend.replay_automation.models import ReplaySchedule
from backend.replay_automation.service import ReplayAutomation
from backend.replay_automation.utils import discovery_urls, next_occurrence, media_identity

NOW = datetime(2026, 9, 30, 14, tzinfo=timezone.utc)
SOURCE = "https://www.youtube.com/@example"


@pytest.fixture
def local_store(monkeypatch, tmp_path):
    """Keep every test isolated from runtime videos, datasets, jobs and SQLite state."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "VIDEO_DIR", tmp_path / "videos")
    monkeypatch.setattr(db, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "vod.sqlite3")
    db.init_db()
    store.initialize()
    return tmp_path


def replay(identifier="one", source=SOURCE):
    """Build one eligible replay with a provider-stable identity."""
    return {"id": f"youtube:{identifier}", "url": f"https://www.youtube.com/watch?v={identifier}",
            "title": identifier, "source_url": source, "published_at": NOW.isoformat()}


def add_video(identifier: str, tmp_path: Path):
    """Create library metadata without invoking a decoder or inference engine."""
    path = tmp_path / f"{identifier}.mp4"
    path.write_bytes(b"fake video")
    with closing(db.get_db()) as connection, connection:
        connection.execute("INSERT INTO videos(id,original_name,path,mime_type,duration,width,height,created_at) VALUES(?,?,?,?,?,?,?,?)",
                           (identifier, path.name, str(path), "video/mp4", 60, 64, 64, NOW.isoformat()))
    return {"id": identifier}


@pytest.mark.parametrize("changes", [
    {"daily_time": "25:00"}, {"daily_time": "9:00"}, {"timezone": "Bad/Zone"},
    {"window_hours": 0}, {"window_hours": float("inf")}, {"window_hours": 2161},
    {"sources": ["https://example.com/creator"]}, {"sources": [SOURCE, SOURCE + "/"]},
    {"enabled": True, "sources": []}, {"unexpected": True},
])
def test_invalid_settings_are_rejected(changes):
    """Reject schedules that cannot define a bounded publication window or creator list."""
    with pytest.raises(ValidationError):
        ReplaySchedule(**{"sources": [SOURCE], **changes})


def test_timezones_and_dst_have_one_daily_occurrence():
    """Skip the second fall-back occurrence and shift the spring gap by one hour."""
    assert next_occurrence(datetime(2026, 11, 1, 5, 31, tzinfo=timezone.utc), "01:30", "America/New_York") == datetime(2026, 11, 2, 6, 30, tzinfo=timezone.utc)
    assert next_occurrence(datetime(2026, 3, 8, 6, tzinfo=timezone.utc), "02:30", "America/New_York") == datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)


def test_restart_coalesces_missed_days_and_prevents_overlapping_runs(local_store):
    """Claim only the most recent elapsed window after downtime and persist the next day."""
    settings = ReplaySchedule(enabled=True, sources=[SOURCE], daily_time="09:00", timezone="America/New_York", window_hours=48)
    store.save_settings(settings, NOW - timedelta(days=5))
    run = store.claim_run(NOW)
    assert run["scheduled_at"] == "2026-09-30T13:00:00+00:00"
    assert run["window_start"] == "2026-09-28T13:00:00+00:00"
    assert store.get_settings()[1] == "2026-10-01T13:00:00+00:00"
    assert store.claim_run(NOW) is None
    with pytest.raises(HTTPException) as error:
        store.claim_run(NOW, manual=True)
    assert error.value.status_code == 409
    store.initialize()
    assert store.status()["runs"][0]["status"] == "interrupted"
    assert store.get_settings()[0] == settings


def test_disabled_and_not_yet_due_schedules_do_nothing(local_store):
    """Saving settings never starts a network scan and disabling removes the due time."""
    store.save_settings(ReplaySchedule(enabled=True, sources=[SOURCE], daily_time="15:00"), NOW)
    assert store.claim_run(NOW) is None
    store.save_settings(ReplaySchedule(enabled=False, sources=[SOURCE]), NOW)
    assert store.claim_run(NOW + timedelta(days=10)) is None
    assert store.get_settings()[1] is None


def test_duplicate_downloads_are_skipped_and_failed_or_deleted_imports_retry(local_store):
    """Deduplicate full manual URL imports, while keeping partial clips independent."""
    item = replay()
    db.create_download_task("manual", url="https://youtu.be/one")
    video = add_video("manual-video", local_store)
    db.update_download_task("manual", status="completed", video_id=video["id"])
    assert not store.reserve_import(item, "run")
    with closing(db.get_db()) as connection, connection:
        connection.execute("DELETE FROM videos WHERE id=?", (video["id"],))
    assert store.reserve_import(item, "run")
    assert not store.reserve_import(item, "run2")
    store.update_import(item["id"], status="failed")
    assert store.reserve_import(item, "run3")
    store.update_import(item["id"], status="completed", video_id=add_video("automatic", local_store)["id"])
    assert not store.reserve_import(item, "run4")
    db.create_download_task("partial", url="https://youtu.be/two", start_seconds=10, end_seconds=20)
    assert store.reserve_import(replay("two"), "run")


def test_restart_recovers_completed_download_associations(local_store):
    """A crash after download completion does not cause the next scan to download it again."""
    item = replay()
    assert store.reserve_import(item, "run")
    db.create_download_task("task", url=item["url"])
    store.update_import(item["id"], status="downloading", task_id="task")
    db.update_download_task("task", status="completed", video_id=add_video("downloaded", local_store)["id"])
    store.initialize()
    assert not store.reserve_import(item, "later")
    assert store.status()["imports"][0]["video_id"] == "downloaded"


def test_run_continues_after_source_and_download_failures_and_retries(local_store):
    """Keep successes visible, avoid overlapping windows, and retry only failed media."""
    sources = [SOURCE, "https://www.twitch.tv/example"]
    store.save_settings(ReplaySchedule(sources=sources), NOW)
    attempts = []

    async def discover(source, start, end):
        """Return duplicates or a creator-specific failure without external I/O."""
        if source != SOURCE:
            raise RuntimeError("Creator unavailable")
        assert end - start == timedelta(hours=24)
        return [replay(), replay(), replay("two")], []

    async def importer(request, identifier):
        """Fail one video on the first pass and register the successful import."""
        attempts.append(identifier)
        if identifier == "youtube:two" and attempts.count(identifier) == 1:
            raise RuntimeError("Download failed")
        return add_video(identifier.replace(":", "-"), local_store)

    async def exercise():
        """Execute two explicit runs without starting the time-based poller."""
        owner = ReplayAutomation(discover, importer)
        first = owner.run_now(NOW)
        await owner.active
        assert store.status()["runs"][0]["imported"] == 1
        owner.run_now(NOW + timedelta(seconds=1))
        await owner.active
        return first

    asyncio.run(exercise())
    assert attempts == ["youtube:one", "youtube:two", "youtube:two"]
    latest = store.status()["runs"][0]
    assert latest["status"] == "completed_with_errors"
    assert (latest["matched"], latest["imported"], latest["skipped"]) == (2, 1, 1)
    assert latest["errors"][0]["source_url"] == sources[1]


def test_cancellation_marks_run_interrupted(local_store):
    """Stop owned work without leaving an active run that blocks subsequent schedules."""
    store.save_settings(ReplaySchedule(sources=[SOURCE]), NOW)

    async def exercise():
        """Wait until discovery starts before cancelling its owner."""
        entered = asyncio.Event()

        async def discover(*args):
            """Block metadata discovery until the test shuts the owner down."""
            entered.set()
            await asyncio.Event().wait()

        owner = ReplayAutomation(discover, None)
        owner.run_now(NOW)
        await entered.wait()
        await owner.stop()

    asyncio.run(exercise())
    assert store.status()["runs"][0]["status"] == "interrupted"


def test_scheduled_import_uses_normal_download_and_playback(local_store, monkeypatch):
    """Drive the actual shared task coroutine, with network transfer replaced by a local stub."""
    item = replay()
    assert store.reserve_import(item, "run")
    prepared = []
    monkeypatch.setattr(app_module, "download_video_url", lambda *args, **kwargs: add_video("normal-path", local_store))
    monkeypatch.setattr(app_module, "start_playback_preparation", prepared.append)

    async def exercise():
        """Await the real standard download task through the automation completion adapter."""
        from backend.models import VideoUrlRequest
        return await app_module.import_discovered_video(VideoUrlRequest(url=item["url"]), item["id"])

    assert asyncio.run(exercise())["id"] == "normal-path"
    assert prepared == ["normal-path"]
    task_id = store.status()["imports"][0]["task_id"]
    assert db.get_download_task(task_id)["status"] == "completed"


def test_discovery_has_no_twelve_entry_cap_and_filters_precise_window(monkeypatch):
    """Use a streaming fake extractor to verify limits, exact timestamps, and stopping."""
    entries = [{"id": str(i), "webpage_url": f"https://youtu.be/{i}", "timestamp": NOW.timestamp() - i} for i in range(30)]
    entries += [{"id": "future", "timestamp": NOW.timestamp() + 1},
                {"id": "live", "is_live": True, "timestamp": NOW.timestamp()},
                {"id": "unknown", "upload_date": "20260930"},
                {"id": "old", "timestamp": NOW.timestamp() - 90000}]
    processes = []

    async def launch(*command, **options):
        """Feed JSON metadata through asyncio's actual stream reader."""
        reader = asyncio.StreamReader()
        reader.feed_data(b"\n".join(json.dumps(entry).encode() for entry in entries) + b"\n")
        reader.feed_eof()
        process = SimpleNamespace(stdout=reader, returncode=None, command=command)
        process.terminate = lambda: setattr(process, "returncode", -15)

        async def wait():
            """Complete the fake process without running an executable."""
            return process.returncode

        process.wait = wait
        processes.append(process)
        return process

    monkeypatch.setattr(discovery.asyncio, "create_subprocess_exec", launch)
    found, errors = asyncio.run(discovery.discover_window(SOURCE, NOW - timedelta(hours=24), NOW))
    assert len(found) == 30
    assert len(errors) == 3  # One unknown publication time per tab, not an invented date.
    assert len(processes) == 3
    assert all("--flat-playlist" not in process.command and "--playlist-end" not in process.command for process in processes)
    assert all("--skip-download" in process.command and process.returncode == -15 for process in processes)
    assert discovery_urls(SOURCE) == [SOURCE + suffix for suffix in ("/videos", "/streams", "/shorts")]
    assert media_identity("https://youtube.com/shorts/123") == "youtube:123"


def test_configuration_api_and_run_now_share_one_owner(local_store, monkeypatch):
    """Exercise validation, persistent settings, and overlapping HTTP run rejection."""
    async def exercise():
        """Use ASGI transport without production startup, remote calls, or inference."""
        entered = asyncio.Event(), asyncio.Event()

        async def discover(*args):
            """Keep the first explicit run active until overlap rejection is checked."""
            entered[0].set()
            await entered[1].wait()
            return [], []

        owner = ReplayAutomation(discover, None)
        monkeypatch.setattr(app_module.app.state, "replay_automation", owner, raising=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_module.app), base_url="http://test") as client:
            assert (await client.put("/api/replay-automation", json={"enabled": True})).status_code == 422
            response = await client.put("/api/replay-automation", json={"sources": [SOURCE], "daily_time": "10:30", "window_hours": 48})
            assert response.status_code == 200
            assert (await client.get("/api/replay-automation")).json()["settings"]["window_hours"] == 48
            assert (await client.post("/api/replay-automation/run")).status_code == 202
            await entered[0].wait()
            assert (await client.post("/api/replay-automation/run")).status_code == 409
            await owner.stop()

    asyncio.run(exercise())


def test_backend_lifespan_runs_due_schedule_and_stops_its_owner(local_store, monkeypatch):
    """Exercise automatic clock-triggered work and restart without initializing ML or live data."""
    scans, shutdowns = [], []
    monkeypatch.setattr(app_module, "startup", lambda: None)
    monkeypatch.setattr(app_module, "shutdown", lambda: shutdowns.append(True))

    async def exercise():
        """Wake a due persisted schedule and verify that the next startup does not repeat it."""
        entered = asyncio.Event()

        async def discover(source, start, end):
            """Record the scheduled window without requesting any creator metadata."""
            scans.append((source, start, end))
            entered.set()
            return [], []

        monkeypatch.setattr(discovery, "discover_window", discover)
        now = datetime.now(timezone.utc)
        store.save_settings(ReplaySchedule(enabled=True, sources=[SOURCE]), now - timedelta(days=2))
        async with app_module.lifespan(app_module.app):
            owner = app_module.app.state.replay_automation
            await asyncio.wait_for(entered.wait(), 2)
            await owner.active
            assert store.status()["runs"][0]["status"] == "completed"
        assert owner.task is None and owner.active is None
        assert app_module.app.state.replay_automation is None
        async with app_module.lifespan(app_module.app):
            await asyncio.sleep(0)
        assert len(scans) == 1
        assert scans[0][2] - scans[0][1] == timedelta(hours=24)

    asyncio.run(exercise())
    assert len(shutdowns) == 2
