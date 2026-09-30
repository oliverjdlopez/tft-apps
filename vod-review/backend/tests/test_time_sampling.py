import asyncio
import json
import subprocess
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest
from pydantic import ValidationError
from backend import app as service, db, processor
from backend.models import VideoUrlRequest, ProcessingRequest, WispProcessingRequest
from backend.sampling import TimeSampler


def test_variable_fps_sampling_does_not_drift_or_duplicate():
    sampler = TimeSampler(0.1)
    times = [0, 0.016, 0.05, 0.101, 0.19, 0.205, 0.51, 0.515, 0.6]
    assert [t for t in times if sampler.select(t)] == [0, 0.101, 0.205, 0.51, 0.6]
    every = TimeSampler(0)
    assert all(every.select(t) for t in times)


def make_clip(path, fps, seconds=1):
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=fps)
        stream.width = stream.height = 32
        stream.pix_fmt = 'yuv420p'
        for _ in range(fps * seconds):
            frame = av.VideoFrame.from_ndarray(np.full((32, 32, 3), 80, np.uint8), format='rgb24')
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)


@pytest.mark.parametrize('fps', [30, 60])
@pytest.mark.parametrize('sequential', [False, True])
def test_round_pipeline_samples_time_across_fps(tmp_path, fps, sequential):
    source = tmp_path / 'source.mp4'
    make_clip(source, fps)
    crops = tmp_path / 'crops'
    class Classifier:
        device_label = 'cpu'
        def predict_batch(self, images):
            return [('11', 1.0)] * len(images)
    process = processor._process_video_all_frames_sequential if sequential else processor.process_video_all_frames
    processed, _ = process(source, 32, 32, dict(x=0, y=0, width=1, height=1), 3,
                           lambda *_: None, lambda *_: None, Classifier(), box_images=crops,
                           sample_interval_seconds=0.1)
    timestamps = [float(p.stem.split('_')[1][:-1]) for p in sorted(crops.glob('*.png'))]
    assert processed == 10
    assert timestamps == pytest.approx([i / 10 for i in range(10)], abs=1e-6)


def test_download_fps_conversion_and_native(tmp_path):
    source = tmp_path / 'source.mp4'
    make_clip(source, 60)
    original = source.read_bytes()
    service.apply_download_fps(source, None)
    assert source.read_bytes() == original
    service.apply_download_fps(source, 30)
    with av.open(str(source)) as video:
        assert video.streams.video[0].average_rate == Fraction(30)
        assert len(list(video.decode(video=0))) == 30
    assert not source.with_name('source.fps-tmp.mp4').exists()


def test_conversion_failure_preserves_source(tmp_path, monkeypatch):
    path = tmp_path / 'source.mp4'
    path.write_bytes(b'original')
    def fail(command, **kwargs):
        Path(command[-1]).write_bytes(b'incomplete')
        raise subprocess.CalledProcessError(1, command, stderr='conversion failed')
    monkeypatch.setattr(service.subprocess, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        service.apply_download_fps(path, 30)
    assert path.read_bytes() == b'original'
    assert not path.with_name('source.fps-tmp.mp4').exists()


@pytest.mark.parametrize('checkpoint', [None, 60])
def test_fps_persists_and_reaches_download_worker(tmp_path, monkeypatch, checkpoint):
    monkeypatch.setattr(db, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(db, 'VIDEO_DIR', tmp_path / 'videos')
    monkeypatch.setattr(db, 'DOWNLOAD_DIR', tmp_path / 'downloads')
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'test.sqlite3')
    db.init_db()
    source = db.VIDEO_DIR / 'v.mp4'
    source.write_bytes(b'video')
    video = db.create_video('v', 'v.mp4', source, 'video/mp4', 1, 32, 32)
    db.create_download_task('task', url='https://youtu.be/example', quality='480p',
                            checkpoint_interval_seconds=checkpoint, target_fps=30)
    db.init_db()
    request = VideoUrlRequest(**db.get_download_request('task'))
    assert request.target_fps == 30 and request.quality == '480p'
    seen = []
    def download(*args, **kwargs):
        seen.append(kwargs['target_fps'])
        return video
    monkeypatch.setattr(service, 'download_video_url', download)
    monkeypatch.setattr(service, 'download_video_url_checkpointed', download)
    monkeypatch.setattr(service, 'start_playback_preparation', lambda *_: None)
    asyncio.run(service._run_download_task('task', request))
    assert seen == [30]
    assert db.get_download_task('task')['status'] == 'completed'


def test_sampling_cache_rejects_old_or_different_cadence(tmp_path):
    manifest = tmp_path / 'manifest.json'
    for payload in [dict(version=1, frame_stride=30), dict(version=2, sample_interval_seconds=0.5)]:
        manifest.write_text(json.dumps(payload))
        with pytest.raises(RuntimeError, match='incompatible'):
            processor.process_cached_crops(tmp_path, 64, lambda *_: None, lambda *_: None,
                                           None, sample_interval_seconds=0.1)


def test_invalid_fps_and_intervals_are_rejected():
    for fps in [0, -1, 121, float('inf'), float('nan')]:
        with pytest.raises(ValidationError):
            VideoUrlRequest(url='https://youtu.be/example', target_fps=fps)
    for interval in [-1, 3601, float('inf'), float('nan')]:
        for model in [ProcessingRequest, WispProcessingRequest]:
            with pytest.raises(ValidationError):
                model(sample_interval_seconds=interval)
