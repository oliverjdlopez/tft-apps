from concurrent.futures import ThreadPoolExecutor
import os
import time

import av
import cv2
import numpy as np
import pytest
import torch

from backend import app as service, db, frame_cache, processor, wisps
from wisp_classifier.detector import TemplateMatcher
from pathlib import Path


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(db, 'VIDEO_DIR', tmp_path / 'videos')
    monkeypatch.setattr(db, 'DOWNLOAD_DIR', tmp_path / 'downloads')
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'test.sqlite3')
    db.init_db()
    wisps.initialize()
    path = db.VIDEO_DIR / 'test.mkv'
    template_path = Path(__file__).resolve().parents[2] / 'wisp_classifier/placeholder_template.pgm'
    template = cv2.cvtColor(cv2.imread(str(template_path), 0), cv2.COLOR_GRAY2RGB)
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('ffv1', rate=30)
        stream.width = stream.height = 32
        stream.pix_fmt = 'bgr0'
        for n in range(30):
            rgb = np.zeros((32, 32, 3), np.uint8)
            rgb[:, :16] = (n, 20, 30)
            rgb[2:7, 22:27] = template
            for packet in stream.encode(av.VideoFrame.from_ndarray(rgb, format='rgb24')):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    db.create_video('v', 'test.mkv', path, 'video/mp4', 1, 32, 32)
    return path, template_path


def count_decodes(monkeypatch):
    original = av.open
    calls = []
    def opened(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(av, 'open', opened)
    return calls


def test_persistent_cache_and_sparse_reads(source, monkeypatch):
    path, _ = source
    calls = count_decodes(monkeypatch)
    progress = []
    first = frame_cache.ensure(path, lambda n, total: progress.append((n, total)))
    assert first.frame_count == 30 and progress[-1] == (30, 30)
    second = frame_cache.ensure(path)
    assert len(calls) == 1
    assert first.manifest == second.manifest
    image_reads = []
    original = frame_cache.np.load
    def read(*args, **kwargs):
        image_reads.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(frame_cache.np, 'load', read)
    seen = []
    class Classifier:
        device_label = 'cpu'
        def predict_batch(self, crops):
            seen.extend(crops)
            return [('11', 1.0)] * len(crops)
    for sequential in (False, True):
        seen.clear()
        image_reads.clear()
        process = processor._process_video_all_frames_sequential if sequential else processor.process_video_all_frames
        count, _ = process(path, 32, 32, dict(x=0, y=0, width=0.5, height=1), 2,
                           lambda *_: None, lambda *_: None, Classifier(), sample_interval_seconds=0.2,
                           frame_cache=second)
        assert count == 5 and len(image_reads) == 5
        assert [int(crop[0, 0, 0]) for crop in seen] == [0, 6, 12, 18, 24]
        assert all(crop.shape == (32, 16, 3) for crop in seen)
    assert len(calls) == 1


def test_concurrent_requests_share_one_build(source, monkeypatch):
    path, _ = source
    calls = count_decodes(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: frame_cache.ensure(path), range(2)))
    assert len(calls) == 1
    assert results[0].manifest == results[1].manifest


def test_interrupted_missing_and_changed_cache_rebuild(source, monkeypatch):
    path, _ = source
    calls = count_decodes(monkeypatch)
    def fail(*_):
        raise RuntimeError('Interrupted')
    with pytest.raises(RuntimeError, match='Interrupted'):
        frame_cache.ensure(path, fail)
    root = frame_cache.directory(path)
    assert not root.exists()
    assert not list(root.parent.glob(root.name + '.building-*'))
    frame_cache.ensure(path)
    (root / '000000000.npy').unlink()
    frame_cache.ensure(path)
    assert (root / '000000000.npy').exists()
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
    frame_cache.ensure(path)
    assert len(calls) == 4


@pytest.mark.skipif(not torch.cuda.is_available(), reason='CUDA GPU required')
def test_round_then_wisp_and_new_round_box_decode_once(source, monkeypatch):
    path, template_path = source
    calls = count_decodes(monkeypatch)
    class Classifier:
        device_label = 'cpu'
        def predict_batch(self, crops):
            return [('11', 1.0)] * len(crops)
    monkeypatch.setattr(service, 'get_ocr_classifier', lambda *_: Classifier())
    monkeypatch.setattr(wisps, 'TemplateMatcher', lambda: TemplateMatcher(template_path))
    box = dict(x=0, y=0, width=0.5, height=1, frame_time=0)
    db.save_bounding_box('v', box)
    db.create_processing_job('v', 'round-one', 4, 0.2)
    service.run_job('round-one')
    assert db.get_video('v')['current_job']['progress'] == 5
    wisps.save_box('v', dict(box, x=0.5))
    job, _ = wisps.create_job('v', 0.1)
    wisps.run_job('v', job['id'])
    complete = wisps.get_video('v')['current_job']
    assert complete['device'] == 'cuda'
    assert complete['detection_count'] == 10
    hits = wisps.detections('v', job['id'], 1)['results']
    assert [h['frame_index'] for h in hits] == list(range(0, 30, 3))
    db.save_bounding_box('v', dict(box, x=0.5))
    db.create_processing_job('v', 'round-two', 4, 0.1)
    service.run_job('round-two')
    assert db.get_video('v')['current_job']['progress'] == 10
    # A finer interval adds missing frames once; the second round run reuses them.
    assert len(calls) == 2


def test_deleting_video_removes_shared_cache(source):
    import asyncio
    path, _ = source
    frame_cache.ensure(path)
    root = frame_cache.directory(path)
    asyncio.run(service.delete_video('v'))
    assert not root.exists() and not path.exists()


def test_separate_processes_share_one_build(source):
    import subprocess
    import sys
    path, _ = source
    marker = db.DATA_DIR / 'builds.txt'
    script = '''
import sys
from pathlib import Path
from backend import db, frame_cache
db.DATA_DIR = Path(sys.argv[1])
def report(n, total):
    if n == 0:
        with Path(sys.argv[3]).open('a') as marker:
            marker.write('build\\n')
cache = frame_cache.ensure(Path(sys.argv[2]), report)
assert cache.frame_count == 30
'''
    def run(_):
        subprocess.run([sys.executable, '-c', script, str(db.DATA_DIR), str(path), str(marker)],
                       check=True, capture_output=True, text=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, range(2)))
    assert marker.read_text().splitlines() == ['build']


def test_sparse_preparation_and_incremental_reuse(source, monkeypatch):
    path, _ = source
    calls = count_decodes(monkeypatch)
    reports = []
    sparse = frame_cache.ensure(path, lambda n, total: reports.append((n, total)), 0.2)
    assert [e[0] for e in sparse.manifest['frames']] == [0, 6, 12, 18, 24]
    assert reports[0] == (0, 5) and reports[-1] == (5, 5)
    assert len(list(sparse.root.glob('*.npy'))) == 5
    old_mtimes = {p.name: p.stat().st_mtime_ns for p in sparse.root.glob('*.npy')}
    assert frame_cache.ensure(path, sample_interval_seconds=0.4).frame_count == 5
    assert len(calls) == 1
    finer = frame_cache.ensure(path, sample_interval_seconds=0.1)
    assert finer.frame_count == 10 and len(calls) == 2
    for name, mtime in old_mtimes.items():
        assert (finer.root / name).stat().st_mtime_ns == mtime
    assert frame_cache.ensure(path, sample_interval_seconds=0.2).frame_count == 10
    assert len(calls) == 2
    all_frames = frame_cache.ensure(path, sample_interval_seconds=0)
    assert all_frames.frame_count == 30 and len(calls) == 3
    assert frame_cache.ensure(path, sample_interval_seconds=0.17).frame_count == 30
    assert len(calls) == 3


def test_non_aligned_interval_adds_coverage(source):
    path, _ = source
    frame_cache.ensure(path, sample_interval_seconds=0.2)
    cache = frame_cache.ensure(path, sample_interval_seconds=0.3)
    assert [e[0] for e in cache.manifest['frames']] == [0, 6, 9, 12, 18, 24, 27]
    assert cache.manifest['intervals'] == [0.2, 0.3]



def test_yuv_cache_matches_direct_cropping(tmp_path, monkeypatch):
    from backend.tests.test_time_sampling import make_clip
    monkeypatch.setattr(db, 'DATA_DIR', tmp_path / 'data')
    source = tmp_path / 'yuv.mp4'
    make_clip(source, 30)
    box = dict(x=0.13, y=0.21, width=0.5, height=0.5)
    with av.open(str(source)) as container:
        original = next(container.decode(video=0))
        reference, _ = processor._FrameCropConverter(av, box).convert(original)
    cache = frame_cache.ensure(source, sample_interval_seconds=0.5)
    assert cache.manifest['frames'][0][4] == 'yuv420p'
    assert not list(cache.root.glob('*.png'))
    with cache.open() as container:
        cached = next(container.decode(container.streams.video[0]))
        actual, _ = processor._FrameCropConverter(av, box).convert(cached)
    assert np.array_equal(actual, reference)


@pytest.mark.skipif(not torch.cuda.is_available(), reason='CUDA GPU required')
def test_smaller_box_is_processed_with_scaled_template(source, monkeypatch):
    _, template_path = source
    monkeypatch.setattr(wisps, 'TemplateMatcher', lambda: TemplateMatcher(template_path))
    wisps.save_box('v', dict(x=0, y=0, width=0.05, height=0.05, frame_time=0))
    job, _ = wisps.create_job('v', 0.5)
    wisps.run_job('v', job['id'])
    result = wisps.get_video('v')['latest_job']
    assert result['status'] == 'completed'
    assert result['progress'] == 2
    assert result['device'] == 'cuda'
