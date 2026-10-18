"""Online API and worker contracts without external downloads or inference."""
import asyncio
import threading
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from backend import app as service
from backend import db


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Use local temporary storage and suppress external/background services."""
    monkeypatch.setenv('TFT_MEDIA_DIR', '')
    for attribute, path in [('DATA_DIR', tmp_path), ('VIDEO_DIR', tmp_path / 'videos'), ('DOWNLOAD_DIR', tmp_path / 'downloads'), ('DB_PATH', tmp_path / 'vod.sqlite3')]:
        monkeypatch.setattr(db, attribute, path)
    monkeypatch.setattr(service, 'OCR_CACHE_DIR', tmp_path / 'ocr')
    monkeypatch.setattr(service, 'DOWNLOAD_TASKS', {})
    monkeypatch.setattr(service, 'DOWNLOAD_PAUSE_REQUESTS', set())
    monkeypatch.setattr(service, 'WORKERS', SimpleNamespace(submit=lambda *args: None))
    monkeypatch.setattr(service.online, 'resolve_metadata', lambda *args: metadata())
    db.init_db()
    return tmp_path


def metadata():
    """Return a canonical source with an independently bounded review range."""
    return {'source_url': 'https://www.youtube.com/watch?v=abcdefghijk', 'source_id': 'abcdefghijk', 'original_name': 'Tournament', 'duration': 1800, 'width': 1280, 'height': 720}


def review():
    """Create a ready-to-analyze remote review and saved crop."""
    video = db.create_online_video('remote', metadata(), 300, 900)
    return db.save_bounding_box(video['id'], {'x': .5, 'y': 0, 'width': .2, 'height': .1, 'frame_time': 5})


def client():
    """Create an ASGI client without invoking production startup services."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=service.app), base_url='http://test')


@pytest.mark.parametrize("twitch", [False, True])
def test_import_range_metadata_errors_and_preview(isolated, monkeypatch, twitch):
    if twitch:
        monkeypatch.setattr(service.online, "resolve_metadata", lambda *args: {**metadata(), "source_id": "twitch:123", "source_url": "https://www.twitch.tv/videos/123"})
    captured = []

    def preview(video, timestamp):
        captured.append((video['source_start_seconds'] + timestamp, video['source_quality']))
        return np.zeros((8, 8, 3), dtype=np.uint8), timestamp + .03

    monkeypatch.setattr(service.online, 'fetch_preview', preview)

    async def check():
        async with client() as api:
            response = await api.post('/api/videos/online', json={'url': 'https://twitch.tv/videos/123' if twitch else 'https://youtu.be/abcdefghijk', 'start_seconds': 300, 'end_seconds': 900, 'quality': '480p'})
            assert response.status_code == 201
            video = response.json()
            assert video['mode'] == 'online' and video['duration'] == 600 and not video['local_available']
            assert db.physical_video_path(video['id']) is None and 'path' not in video
            response = await api.get(f"/api/videos/{video['id']}/frame?timestamp=10", headers={'Origin': 'http://localhost:5173'})
            assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
            assert float(response.headers['X-Frame-Timestamp']) == 10.03
            assert 'x-frame-timestamp' in response.headers['access-control-expose-headers'].lower()
            assert captured == [(310, '480p')]
            assert (await api.get(f"/api/videos/{video['id']}/frame?timestamp=600")).status_code == 400
            assert (await api.post('/api/videos/online', json={'url': 'https://youtu.be/abcdefghijk', 'start_seconds': 900, 'end_seconds': 300})).status_code == 422
            assert (await api.post('/api/videos/online', json={'url': 'https://youtu.be/abcdefghijk', 'start_seconds': 1900})).status_code == 400
            monkeypatch.setattr(service.online, 'resolve_metadata', lambda *args: (_ for _ in ()).throw(ValueError('unsupported URL')))
            assert (await api.post('/api/videos/online', json={'url': 'https://example.com/video'})).status_code == 400
            monkeypatch.setattr(service.online, 'resolve_metadata', lambda *args: (_ for _ in ()).throw(RuntimeError('network')))
            assert (await api.post('/api/videos/online', json={'url': 'https://youtu.be/abcdefghijk'})).status_code == 502
    asyncio.run(check())


def test_processing_defaults_and_online_local_tool_guards(isolated, monkeypatch):
    monkeypatch.setenv('TFT_MEDIA_DIR', str(isolated / 'shared'))
    review()
    path = isolated / 'uploaded.mp4'
    path.write_bytes(b'fixture')
    db.create_video('local', 'Uploaded', path, 'video/mp4', 600, 1280, 720)
    db.save_bounding_box('local', {'x': .5, 'y': 0, 'width': .2, 'height': .1, 'frame_time': 0})

    async def check():
        async with client() as api:
            assert (await api.post('/api/videos/remote/process', json={'sample_interval_seconds': 0})).status_code == 400
            online_job = await api.post('/api/videos/remote/process', json={})
            offline_job = await api.post('/api/videos/local/process', json={})
            assert online_job.status_code == offline_job.status_code == 202
            assert online_job.json()['sample_interval_seconds'] == 10
            assert offline_job.json()['sample_interval_seconds'] == service.SAMPLE_INTERVAL_SECONDS
            assert (await api.get('/api/videos/remote/transcription')).status_code == 200
            for method, route, payload in [
                ('GET', '/content', None), ('GET', '/playback', None),
                ('POST', '/transcription', None), ('POST', '/share', None),
                ('POST', '/round-export', {'game_number': 1, 'clips': [{'label': '11', 'start_seconds': 0, 'end_seconds': 10}]}),
            ]:
                response = await api.request(method, '/api/videos/remote' + route, json=payload)
                assert response.status_code == 409, (route, response.text)
    asyncio.run(check())


@pytest.mark.parametrize("fails", [False, True])
def test_online_worker_publishes_partial_results_and_preserves_completed_on_failure(isolated, monkeypatch, fails):
    review()
    db.create_processing_job('remote', 'previous', 64, 10)
    db.complete_job('previous', 'remote', [(0, 0, '11', .9)], 1, 1, 'cpu')
    db.create_processing_job('remote', 'rerun', 64, 10)
    monkeypatch.setattr(service, 'get_ocr_classifier', lambda labels: SimpleNamespace(device_label='cpu'))
    monkeypatch.setattr(service, 'trace_resources', lambda *args, **kwargs: None)

    def analyze(video, box, batch, interval, classifier, cache, on_progress, on_results, **kwargs):
        assert interval == 10 and video['source_start_seconds'] == 300
        on_progress('refining', 3, 4)
        on_results([(0, 0, '11', .9), (10, 10.1, '12', .8)])
        current = db.get_video('remote')
        assert current['active_job']['phase'] == 'refining'
        assert len(current['active_job']['results']) == 2
        assert current['current_job']['id'] == 'previous'
        if fails:
            raise RuntimeError('network interrupted')
        return 4, 'cpu'

    monkeypatch.setattr(service.online, 'analyze_online', analyze)
    service.run_job('rerun')
    current = db.get_video('remote')
    assert current['current_job']['id'] == ('previous' if fails else 'rerun')
    assert current['latest_job']['status'] == ('failed' if fails else 'completed')
    if not fails:
        assert len(current['current_job']['results']) == 2


def test_conversion_waits_for_playback_keeps_identity_and_coalesces_clicks(isolated, monkeypatch):
    initial = review()
    db.create_processing_job('remote', 'previous', 64, 10)
    db.complete_job('previous', 'remote', [(0, 0, '11', .9)], 1, 1, 'cpu')
    prepared = threading.Event()
    release = threading.Event()
    calls = []

    def download(*args, **kwargs):
        calls.append((args, kwargs))
        path = isolated / 'download.mp4'
        path.write_bytes(b'fixture')
        return db.bind_local_copy(kwargs['target_video_id'], path, 'video/mp4', 1280, 720)

    def prepare(video_id):
        assert db.get_video(video_id)['mode'] == 'online'
        prepared.set()
        assert release.wait(5)

    monkeypatch.setattr(service, 'download_video_url', download)
    monkeypatch.setattr(service, 'build_playback_assets', prepare)

    async def check():
        async with client() as api:
            first = await api.post('/api/videos/remote/offline-download', json={})
            assert first.status_code == 202
            task_id = first.json()['task_id']
            task = service.DOWNLOAD_TASKS[task_id]
            try:
                assert await asyncio.to_thread(prepared.wait, 5)
                assert db.get_video('remote')['mode'] == 'online'
                duplicate = await api.post('/api/videos/remote/offline-download', json={})
                assert duplicate.json()['task_id'] == task_id
                for method, route, payload in [('POST', '/process', {}), ('PATCH', '/mode', {'mode': 'offline'}), ('DELETE', '', None)]:
                    assert (await api.request(method, '/api/videos/remote' + route, json=payload)).status_code == 409
            finally:
                release.set()
                await task
            result = db.get_download_task(task_id)
            assert result['status'] == 'completed' and result['video']['id'] == 'remote'
            assert result['video']['mode'] == 'offline'
            assert result['video']['duration'] == initial['duration'] and result['video']['box'] == initial['box']
            assert result['video']['current_job']['id'] == 'previous'
            assert len(db.list_videos()) == 1 and len(calls) == 1
            assert calls[0][1]['target_video_id'] == 'remote'
            assert calls[0][0][1:3] == (300, 900)
    asyncio.run(check())


@pytest.mark.parametrize("failure_stage", ["download", "playback"])
def test_failed_conversion_preserves_online_playback(isolated, monkeypatch, failure_stage):
    review()

    def download(*args, **kwargs):
        if failure_stage == 'download':
            raise RuntimeError('failed download')
        path = isolated / 'download.mp4'
        path.write_bytes(b'fixture')
        return db.bind_local_copy('remote', path, 'video/mp4', 1280, 720)

    monkeypatch.setattr(service, 'download_video_url', download)
    monkeypatch.setattr(service, 'build_playback_assets', lambda *args: (_ for _ in ()).throw(RuntimeError('failed playback preparation')))

    async def check():
        async with client() as api:
            response = await api.post('/api/videos/remote/offline-download', json={})
            task_id = response.json()['task_id']
            await service.DOWNLOAD_TASKS[task_id]
            assert db.get_download_task(task_id)['status'] == 'failed'
            assert db.get_video('remote')['mode'] == 'online'
    asyncio.run(check())


def test_existing_local_copy_is_reused_without_downloading(isolated, monkeypatch):
    review()
    path = isolated / 'already-downloaded.mp4'
    path.write_bytes(b'fixture')
    db.bind_local_copy('remote', path, 'video/mp4', 1280, 720, shared_media=True)
    calls = []
    monkeypatch.setattr(service, 'download_video_url', lambda *args, **kwargs: pytest.fail('must reuse local copy'))
    monkeypatch.setattr(service, 'build_playback_assets', lambda video_id: calls.append(video_id))

    async def check():
        async with client() as api:
            response = await api.post('/api/videos/remote/offline-download', json={})
            task_id = response.json()['task_id']
            await service.DOWNLOAD_TASKS[task_id]
            assert db.get_video('remote')['mode'] == 'offline'
            assert db.video_is_shared('remote') and calls == ['remote']
    asyncio.run(check())


def test_paused_conversion_resume_uses_target_worker_and_blocks_partial_save(isolated, monkeypatch):
    review()
    db.create_download_task('paused', url=metadata()['source_url'], start_seconds=300, end_seconds=900, checkpoint_interval_seconds=60, target_video_id='remote')
    db.update_download_task('paused', status='paused', video_id='remote')
    calls = []

    async def runner(task_id, request, video_id):
        calls.append((task_id, request, video_id))

    monkeypatch.setattr(service, 'run_offline_conversion', runner)

    async def check():
        async with client() as api:
            assert (await api.post('/api/downloads/paused/save')).status_code == 409
            assert (await api.post('/api/videos/remote/process', json={})).status_code == 409
            response = await api.post('/api/downloads/paused/resume')
            assert response.status_code == 202
            await service.DOWNLOAD_TASKS['paused']
            assert calls[0][0] == 'paused' and calls[0][2] == 'remote'
            assert calls[0][1].start_seconds == 300
    asyncio.run(check())
