from pathlib import Path
import av
import cv2
import numpy as np
import pytest
import torch
from backend import db, wisps
from wisp_classifier.detector import TemplateMatcher

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "wisp_classifier/placeholder_template.pgm"
requires_cuda = pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA GPU required")


@requires_cuda
def test_matcher_binary_labels_and_small_crop():
    matcher = TemplateMatcher(TEMPLATE_PATH, threshold=0.99)
    rgb = cv2.cvtColor(matcher.template, cv2.COLOR_GRAY2RGB)
    assert matcher.predict(rgb)[0] is True
    assert matcher.predict(np.zeros((10, 10, 3), dtype=np.uint8))[0] is False
    small = cv2.resize(rgb, (2, 2), interpolation=cv2.INTER_LINEAR)
    assert matcher.predict(small)[0] is True
    with pytest.raises(ValueError, match='Cannot load'):
        TemplateMatcher(Path('/missing-template.pgm'))


@requires_cuda
def test_all_frames_crop_pagination_and_round_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(db, 'VIDEO_DIR', tmp_path / 'videos')
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(wisps, 'TemplateMatcher', lambda: TemplateMatcher(TEMPLATE_PATH))
    monkeypatch.setattr(wisps, 'recognize_batch', lambda crops: ['raw text'] * len(crops))
    db.init_db()
    wisps.initialize()
    path = tmp_path / 'video.mkv'
    template = cv2.cvtColor(cv2.imread(str(TEMPLATE_PATH), 0), cv2.COLOR_GRAY2RGB)
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('ffv1', rate=30)
        stream.width = stream.height = 32
        stream.pix_fmt = 'bgr0'
        for index in range(54):
            rgb = np.zeros((32, 32, 3), dtype=np.uint8)
            # Last frame has a matching template only OUTSIDE the selected region.
            x = 2 if index < 53 else 22
            rgb[2:7, x:x+5] = template
            for packet in stream.encode(av.VideoFrame.from_ndarray(rgb, format='rgb24')):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    db.create_video('test', 'video.mkv', path, 'video/mp4', 1.8, 32, 32)
    with pytest.raises(Exception, match='Save a bounding box'):
        wisps.create_job('test')
    box = dict(x=0, y=0, width=0.5, height=0.5, frame_time=0)
    wisps.save_box('test', box)
    job, created = wisps.create_job('test')
    assert created
    duplicate, created = wisps.create_job('test')
    assert not created and duplicate['id'] == job['id']
    # Editing the next run's box must not change the queued job's snapshot.
    wisps.save_box('test', dict(box, x=0.5))
    wisps.run_job('test', job['id'])
    result = wisps.get_video('test')['current_job']
    assert result['status'] == 'completed'
    assert result['device'] == 'cuda'
    assert result['progress'] == 54
    assert result['detection_count'] == 53
    pages = [wisps.detections('test', job['id'], p) for p in (1, 2, 3)]
    assert [len(p['results']) for p in pages] == [25, 25, 3]
    hits = [hit for p in pages for hit in p['results']]
    assert [hit['frame_index'] for hit in hits] == list(range(53))
    assert hits[30]['timestamp_seconds'] == pytest.approx(1.0)
    assert wisps.detections('test', job['id'], 999)['page'] == 3
    assert db.get_video('test')['box'] is None
    assert db.get_video('test')['current_job'] is None
    # Verify the HTTP boundary validates pagination and scopes results to a video.
    import asyncio
    import httpx
    from backend.app import app
    async def check_api():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            base = f"/api/videos/test/wisps/jobs/{job['id']}/detections"
            assert (await client.get(base + '?page=0')).status_code == 422
            response = await client.get(base + '?page=3')
            assert response.status_code == 200
            assert len(response.json()['results']) == 3
            assert (await client.get('/api/videos/missing/wisps')).status_code == 404
            assert (await client.get(base.replace('/test/', '/missing/'))).status_code == 404
    asyncio.run(check_api())
    wisps.save_box('test', box)
    timed_job, _ = wisps.create_job('test', 0.1)
    wisps.run_job('test', timed_job['id'])
    timed = wisps.get_video('test')['current_job']
    assert timed['id'] == timed_job['id']
    assert timed['progress'] == 18
    assert timed['sample_interval_seconds'] == 0.1
    assert timed['detection_count'] == 18
    timed_hits = wisps.detections('test', timed_job['id'], 1)['results']
    assert [hit['frame_index'] for hit in timed_hits] == list(range(0, 54, 3))
    assert [hit['timestamp_seconds'] for hit in timed_hits] == pytest.approx([n / 10 for n in range(18)])
    next_job, _ = wisps.create_job('test')
    wisps.initialize()
    assert wisps.get_video('test')['latest_job']['status'] == 'failed'
    assert wisps.get_video('test')['current_job']['id'] == timed_job['id']


@requires_cuda
@pytest.mark.parametrize("alpha", [False, True])
def test_color_template_matches_rgb_channels(tmp_path, alpha):
    # Red and green patches with equal grayscale brightness must remain distinct.
    rgb = np.full((5, 5, 3), (200, 0, 0), dtype=np.uint8)
    other_color = np.full((5, 5, 3), (0, 102, 0), dtype=np.uint8)
    assert np.array_equal(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY),
                          cv2.cvtColor(other_color, cv2.COLOR_RGB2GRAY))
    encoded = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGRA if alpha else cv2.COLOR_RGB2BGR)
    path = tmp_path / 'color.png'
    assert cv2.imwrite(str(path), encoded)
    matcher = TemplateMatcher(path, threshold=0.99)
    assert not matcher.grayscale
    assert matcher.template.shape == (5, 5, 3)
    assert matcher.predict(rgb)[0] is True
    assert matcher.predict(other_color)[0] is False
    small = cv2.resize(rgb, (2, 2), interpolation=cv2.INTER_LINEAR)
    assert matcher.predict(small)[0] is True


@requires_cuda
def test_grayscale_template_matches_one_channel(tmp_path):
    rgb = np.full((5, 5, 3), (200, 0, 0), dtype=np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    path = tmp_path / 'gray.png'
    assert cv2.imwrite(str(path), gray)
    matcher = TemplateMatcher(path, threshold=0.99)
    assert matcher.grayscale
    assert matcher.template.ndim == 2
    assert matcher.predict(rgb)[0] is True
    assert matcher.predict(np.full_like(rgb, (0, 102, 0)))[0] is True


def test_cpu_fallback_when_accelerators_are_unavailable(monkeypatch):
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
    monkeypatch.setattr(torch.backends.mps, 'is_available', lambda: False)
    matcher = TemplateMatcher(TEMPLATE_PATH)
    assert matcher.device_label == 'cpu'
    assert matcher._template.device.type == 'cpu'


@requires_cuda
@pytest.mark.parametrize('color', [False, True])
def test_gpu_scores_match_opencv(tmp_path, color):
    rng = np.random.default_rng(42)
    rgb = rng.integers(0, 256, (7, 9, 3), dtype=np.uint8)
    template = rgb if color else cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    path = tmp_path / 'template.png'
    cv2.imwrite(str(path), cv2.cvtColor(template, cv2.COLOR_RGB2BGR) if color else template)
    matcher = TemplateMatcher(path)
    crops = [rng.integers(0, 256, (32, 40, 3), dtype=np.uint8) for _ in range(3)]
    crops[0][12:19, 18:27] = rgb
    crops.append(np.zeros_like(crops[0]))
    assert matcher._template.is_cuda
    for crop, (detected, score) in zip(crops, matcher.predict_batch(crops), strict=True):
        source = crop if color else cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        expected = float(1 - cv2.matchTemplate(source, template, cv2.TM_SQDIFF_NORMED).min())
        assert score == pytest.approx(expected, abs=2e-5)
        assert detected == (expected >= matcher.threshold)


@requires_cuda
@pytest.mark.parametrize('color', [False, True])
def test_template_scales_to_fit_smaller_crop_without_distortion(tmp_path, color):
    rng = np.random.default_rng(7)
    rgb = rng.integers(30, 240, (16, 24, 3), dtype=np.uint8)
    template = rgb if color else cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    path = tmp_path / 'scale.png'
    cv2.imwrite(str(path), cv2.cvtColor(template, cv2.COLOR_RGB2BGR) if color else template)
    matcher = TemplateMatcher(path, threshold=0.99)
    # Fit a 24×16 template into a 16×8 crop: scaled template is 12×8.
    small = cv2.resize(rgb, (12, 8), interpolation=cv2.INTER_LINEAR)
    crop = np.zeros((8, 16, 3), dtype=np.uint8)
    crop[:, 2:14] = small
    results = matcher.predict_batch([crop, np.zeros_like(crop)])
    assert results[0][0] is True
    assert results[1][0] is False
    assert matcher._fitted_template.is_cuda
    assert tuple(matcher._fitted_template.shape[-2:]) == (8, 12)
    fitted = matcher._fitted_template
    matcher.predict(crop)
    assert matcher._fitted_template is fitted
