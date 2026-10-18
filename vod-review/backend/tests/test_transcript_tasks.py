"""Persisted transcript tasks through real VOD endpoints with mocked upstream HTTP."""
import asyncio
import json

import httpx
import pytest

from backend import app as application, db
from backend.transcript_tasks import store
from backend.transcript_tasks.models import TASKS
from backend.transcript_tasks.service import TranscriptTaskService
from backend.transcript_tasks.utils import transcript_hash


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Keep all source data, task history, and media outside developer runtime state."""
    monkeypatch.setenv("TFT_MEDIA_DIR", "")
    for name, value in {"DATA_DIR": tmp_path, "VIDEO_DIR": tmp_path / "videos", "DOWNLOAD_DIR": tmp_path / "downloads", "DB_PATH": tmp_path / "vod.sqlite3"}.items():
        monkeypatch.setattr(db, name, value)
    db.init_db()
    db.create_transcription_task("speech", "/unused/audio")
    db.update_transcription_task("speech", status="completed", transcript="I might spend. But I will wait.", language="en", segments=[
        {"start": 12.25, "end": 17.8, "text": "I might spend."},
        {"start": 90.5, "end": 92.4, "text": " But I will wait."},
    ])


def response(request, result=None):
    """Expose only the real supported catalogue and task response envelopes."""
    if request.method == "GET":
        return httpx.Response(200, json={"tasks": [task.model_dump() for task in TASKS.values()]})
    name = request.url.path.split("/")[-2]
    output = "# Notes\nOriginal Markdown" if name == "transcription_pipeline" else {"moments": [{"title": "Waiting", "explanation": "The speaker changes the plan.", "evidence": [{"start_segment_id": "s000000", "end_segment_id": "s000001"}]}]}
    return httpx.Response(200, json={"ok": True, "task": name, "result": output if result is None else result})


def service(handler=response, base_url="http://chat"):
    """Create an isolated service and attach it to the actual VOD router."""
    instance = TranscriptTaskService(base_url, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    application.app.state.transcript_tasks = instance
    return instance


def api():
    """Use production endpoints without starting unrelated OCR/scheduler processes."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=application.app), base_url="http://vod")


async def finish(instance):
    """Drain accepted workers deterministically without polling or real models."""
    await asyncio.gather(*list(instance.workers))


def test_independent_tasks_reuse_rerun_and_public_timing():
    """Exercise both actions, exact resolution, and immutable attempt reuse via HTTP."""
    async def check():
        instance = service()
        await instance.start()
        async with api() as client:
            assert (await client.get('/api/transcript-tasks')).json()["available"]
            plain = (await client.get('/api/transcriptions/speech')).json()
            assert "segments" not in plain
            public = (await client.get('/api/transcriptions/speech?include_segments=true')).json()
            assert [s["id"] for s in public["segments"]] == ["s000000", "s000001"]
            assert "id" not in db.get_transcription_task("speech", include_segments=True)["segments"][0]
            started = [await client.post(f'/api/transcriptions/speech/tasks/{name}', json={}) for name in TASKS]
            assert all(r.status_code == 202 for r in started)
            await finish(instance)
            states = (await client.get('/api/transcriptions/speech/tasks')).json()["tasks"]
            assert all(s["successful_run"] and not s["active_run"] for s in states)
            evidence = states[1]["successful_run"]["output"]["moments"][0]["evidence"][0]
            assert evidence == {"start_segment_id": "s000000", "end_segment_id": "s000001", "start_seconds": 12.25, "end_seconds": 92.4, "excerpt": "I might spend. But I will wait."}
            reused = await client.post('/api/transcriptions/speech/tasks/find_key_moments', json={})
            assert reused.status_code == 200 and reused.json()["id"] == started[1].json()["id"]
            rerun = await client.post('/api/transcriptions/speech/tasks/find_key_moments', json={"rerun": True})
            assert rerun.status_code == 202 and rerun.json()["id"] != reused.json()["id"]
            await finish(instance)
        await instance.stop()
    asyncio.run(check())


def test_simultaneous_starts_and_two_request_limit():
    """Coalesce simultaneous submissions and leave extra accepted work queued."""
    async def check():
        gate = asyncio.Event()
        executing = []
        async def handler(request):
            if request.method == "POST":
                executing.append(request.url.path)
                await gate.wait()
            return response(request)
        instance = service(handler)
        same = await asyncio.gather(*[instance.submit("speech", "find_key_moments") for _ in range(5)])
        assert len({run[0]["id"] for run in same}) == 1
        await instance.submit("speech", "transcription_pipeline")
        db.create_transcription_task("other", "/unused")
        db.update_transcription_task("other", status="completed", transcript="Source")
        queued, _ = await instance.submit("other", "transcription_pipeline")
        await asyncio.sleep(0)
        assert len(executing) == 2 and store.get(queued["id"])["status"] == "queued"
        gate.set()
        await finish(instance)
        await instance.stop()
    asyncio.run(check())


@pytest.mark.parametrize("failure", ["timeout", "malformed", "ok_false", "reference", "source_changed", "network"])
def test_failed_rerun_keeps_previous_success(failure):
    """Surface upstream/schema/staleness failures while retaining the earlier output."""
    async def check():
        failing = False
        def handler(request):
            if failing and request.method == "POST":
                if failure == "timeout":
                    raise httpx.ReadTimeout("timeout")
                if failure == "network":
                    raise httpx.ConnectError("unavailable")
                if failure == "malformed":
                    return httpx.Response(200, text="not json")
                if failure == "ok_false":
                    return httpx.Response(200, json={"ok": False, "error": "refused"})
                if failure == "reference":
                    return response(request, {"moments": [{"title": "Bad", "explanation": "Bad", "evidence": [{"start_segment_id": "missing", "end_segment_id": "s000001"}]}]})
                db.update_transcription_task("speech", transcript="changed")
            return response(request)
        instance = service(handler)
        old, _ = await instance.submit("speech", "find_key_moments")
        await finish(instance)
        failing = True
        attempt, _ = await instance.submit("speech", "find_key_moments", True)
        await finish(instance)
        assert store.get(attempt["id"])["status"] == "failed"
        assert store.get(old["id"])["status"] == "completed"
        if failure != "source_changed":
            states = instance.states("speech")["tasks"][1]
            assert states["latest_run"]["status"] == "failed" and states["successful_run"]["id"] == old["id"]
        if failure == "timeout":
            assert "may still be running" in store.get(attempt["id"])["error"]
        await instance.stop()
    asyncio.run(check())


def test_shutdown_restart_recovery_and_offline_saved_results():
    """Await cancellation, recover queued rows, and keep successes readable offline."""
    async def check():
        instance = service()
        old, _ = await instance.submit("speech", "transcription_pipeline")
        await finish(instance)
        instance.base_url = ""
        assert (await instance.submit("speech", "transcription_pipeline"))[0]["id"] == old["id"]
        with pytest.raises(Exception) as error:
            await instance.submit("speech", "find_key_moments")
        assert error.value.status_code == 503
        queued, _ = store.choose("speech", "find_key_moments", 1, transcript_hash(db.get_transcription_task("speech", include_segments=True)), True)
        await instance.start()
        assert store.get(queued["id"])["error_code"] == "interrupted"
        assert instance.states("speech")["tasks"][0]["successful_run"]["id"] == old["id"]
        await instance.stop()
    asyncio.run(check())


@pytest.mark.parametrize("status,text,segments,code", [("running", "source", None, 409), ("completed", "source", None, 409), ("completed", "", [], 422), ("completed", "source", [{"start": -1, "end": 1, "text": "source"}], 422)])
def test_prerequisites_fail_before_model(status, text, segments, code):
    """Reject unfinished, untimed, silent, or malformed sources before HTTP execution."""
    async def check():
        db.update_transcription_task("speech", status=status, transcript=text)
        with db.get_db() as connection:
            connection.execute("UPDATE transcription_tasks SET segments_json=? WHERE id='speech'", (json.dumps(segments) if segments is not None else None,))
        instance = service(lambda request: pytest.fail("Upstream called"))
        async with api() as client:
            assert (await client.post('/api/transcriptions/speech/tasks/find_key_moments')).status_code == code
            assert (await client.post('/api/transcriptions/speech/tasks/unknown')).status_code == 404
            assert (await client.post('/api/transcriptions/missing/tasks/find_key_moments')).status_code == 404
        await instance.stop()
    asyncio.run(check())


def test_saved_online_transcript_read():
    """Allow saved recognition reads without changing the Offline requirement for POST."""
    db.create_online_video("remote", {"source_url": "https://youtu.be/abcdefghijk", "source_id": "abcdefghijk", "original_name": "Online", "duration": 600, "width": 1280, "height": 720}, 0, 600)
    with db.get_db() as connection:
        connection.execute("UPDATE transcription_tasks SET video_id='remote' WHERE id='speech'")
    async def check():
        async with api() as client:
            assert (await client.get('/api/videos/remote/transcription')).json()["task_id"] == "speech"
            assert (await client.post('/api/videos/remote/transcription')).status_code == 409
    asyncio.run(check())


def test_hash_distinguishes_legacy_and_silence():
    """Retain the meaningful null-versus-empty segment distinction in reuse keys."""
    assert transcript_hash({"transcript": "", "language": "en", "segments": None}) != transcript_hash({"transcript": "", "language": "en", "segments": []})


def test_cancellation_and_queued_source_change():
    """Cancel owned running workers and reject changed source before queued execution."""
    async def check():
        gate = asyncio.Event()
        async def handler(request):
            if request.method == "POST":
                await gate.wait()
            return response(request)
        instance = service(handler)
        run, _ = await instance.submit("speech", "find_key_moments")
        await asyncio.sleep(0)
        await instance.stop()
        assert not instance.workers
        assert store.get(run["id"])["status"] == "failed"
        instance = service()
        await instance.capacity.acquire()
        await instance.capacity.acquire()
        queued, _ = await instance.submit("speech", "find_key_moments", True)
        db.update_transcription_task("speech", transcript="Changed while queued")
        instance.capacity.release()
        await finish(instance)
        assert store.get(queued["id"])["status"] == "failed"
        await instance.stop()
    asyncio.run(check())


def test_oversized_source_is_rejected_before_upstream(monkeypatch):
    """Enforce byte and token budgets without silently truncating stored source."""
    from backend.transcript_tasks import utils
    class Encoding:
        """Represent an input just beyond the named application token budget."""
        def encode(self, *args, **kwargs):
            """Return a deterministic oversized token inventory without network access."""
            return range(64_001)
    monkeypatch.setattr(utils, "encoding", lambda: Encoding())
    async def check():
        instance = service(lambda request: pytest.fail("Upstream called"))
        async with api() as client:
            response = await client.post('/api/transcriptions/speech/tasks/transcription_pipeline')
            assert response.status_code == 422 and "64,000" in response.json()["detail"]
            db.update_transcription_task("speech", transcript="x" * (10 * 1024 * 1024 + 1))
            response = await client.post('/api/transcriptions/speech/tasks/transcription_pipeline')
            assert response.status_code == 422 and "10 MB" in response.json()["detail"]
        await instance.stop()
    asyncio.run(check())
