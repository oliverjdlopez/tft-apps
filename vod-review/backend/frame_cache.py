"""Reusable sampled frames without full-frame PNG encoding or RGB conversion."""
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import time
from types import SimpleNamespace

from filelock import FileLock
from PIL import Image
import numpy as np

try:
    from . import db
    from .sampling import TimeSampler
except ImportError:
    import db
    from sampling import TimeSampler

VERSION = 1


def directory(video_path):
    key = hashlib.sha256(str(Path(video_path).resolve()).encode()).hexdigest()
    return db.DATA_DIR / 'frame_cache' / key


def _lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path) + '.lock')


def _fingerprint(source):
    stat = source.stat()
    return dict(path=str(source.resolve()), size=stat.st_size, mtime_ns=stat.st_mtime_ns)


class CachedFrame:
    def __init__(self, root, entry):
        self.root = root
        self.index, self.pts, self.width, self.height = entry[:4]
        self.storage = entry[4:]
        self.time_base = Fraction(1)

    def _native_frame(self):
        import av
        data = np.load(self.root / f'{self.index:09d}.npy', mmap_mode='r', allow_pickle=False)
        frame = av.VideoFrame.from_ndarray(data, format=self.storage[0])
        frame.colorspace = self.storage[1]
        frame.color_range = self.storage[2]
        frame.time_base = Fraction(1, 1_000_000)
        frame.pts = round(self.pts * 1_000_000)
        return frame

    def crop_rgb(self, box, include_full_frame=False, converter=None):
        try:
            from .processor import box_to_pixels, _FrameCropConverter
        except ImportError:
            from processor import box_to_pixels, _FrameCropConverter
        if self.storage:
            import av
            converter = converter or _FrameCropConverter(av, box)
            return converter.convert(self._native_frame(), include_full_frame)
        # Previously created PNG caches remain readable.
        with Image.open(self.root / f'{self.index:09d}.png') as image:
            bounds = box_to_pixels(box, self.width, self.height)
            crop = np.asarray(image.crop(bounds)).copy()
            full = np.asarray(image).copy() if include_full_frame else None
        return crop, full

    def to_ndarray(self, format='rgb24'):
        if self.storage:
            return self._native_frame().to_ndarray(format=format)
        if format != 'rgb24':
            raise ValueError('Legacy frame cache stores RGB24 frames')
        with Image.open(self.root / f'{self.index:09d}.png') as image:
            return np.asarray(image).copy()


class CachedVideo:
    def __init__(self, root, manifest):
        self.root = root
        self.manifest = manifest
        self.frame_count = len(manifest['frames'])

    def open(self):
        return CachedContainer(self)


class CachedContainer:
    def __init__(self, cache):
        self.cache = cache
        self.streams = SimpleNamespace(video=[SimpleNamespace(
            frames=cache.frame_count, start_time=0, time_base=Fraction(1),
            duration=cache.manifest['duration'], average_rate=cache.manifest['average_rate'],
            thread_type='CACHE', codec_context=SimpleNamespace(thread_count=0),
        )])

    def decode(self, stream):
        for entry in self.cache.manifest['frames']:
            yield CachedFrame(self.cache.root, entry)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _filename(entry):
    suffix = 'npy' if len(entry) > 4 else 'png'
    return f'{entry[0]:09d}.{suffix}'


def _covers(intervals, requested):
    """A denser aligned time grid includes every sample of a coarser one."""
    for interval in intervals:
        if interval == 0:
            return True
        if requested > 0:
            ratio = requested / interval
            if ratio >= 1 and math.isclose(ratio, round(ratio), rel_tol=0, abs_tol=1e-9):
                return True
    return False


def ensure(video_path, on_progress=None, sample_interval_seconds=0):
    """Cache requested timestamps only; reuse compatible coverage or add missing frames."""
    import av
    sampler = TimeSampler(sample_interval_seconds)
    source = Path(video_path)
    root = directory(source)
    with _lock(root):
        fingerprint = _fingerprint(source)
        manifest_path = root / 'manifest.json'
        previous = None
        try:
            manifest = json.loads(manifest_path.read_text())
            if manifest['version'] == VERSION and manifest['source'] == fingerprint and manifest['frames']:
                previous = manifest
                # Manifests written before sparse preparation contain every source frame.
                intervals = manifest.get('intervals', [0])
                available = {path.name for path in root.iterdir()}
                intact = all(_filename(entry) in available for entry in manifest['frames'])
                if intact and _covers(intervals, sample_interval_seconds):
                    return CachedVideo(root, manifest)
        except (FileNotFoundError, ValueError, KeyError):
            pass
        root.parent.mkdir(parents=True, exist_ok=True)
        for abandoned in root.parent.glob(root.name + '.building-*'):
            shutil.rmtree(abandoned)
        staging = Path(tempfile.mkdtemp(prefix=root.name + '.building-', dir=root.parent))
        entries = {entry[0]: entry for entry in previous['frames']} if previous else {}
        intervals = previous.get('intervals', [0]) if previous else []
        # Restore missing frames from previous coverage as well as the requested grid.
        missing = {index for index, entry in entries.items() if not (root / _filename(entry)).is_file()}
        selected = 0
        last_report = 0.0
        try:
            with av.open(str(source)) as container:
                stream = container.streams.video[0]
                stream.thread_type = 'AUTO'
                origin = float((stream.start_time or 0) * stream.time_base)
                rate = float(stream.average_rate or 30)
                duration = float(stream.duration * stream.time_base) if stream.duration is not None else 0
                if not duration and container.duration:
                    duration = container.duration / av.time_base
                source_total = stream.frames or max(1, round(duration * rate))
                total = source_total if sample_interval_seconds == 0 else min(source_total, math.ceil(duration / sample_interval_seconds))
                if on_progress:
                    on_progress(0, total)
                for index, frame in enumerate(container.decode(stream)):
                    if frame.pts is None or frame.time_base is None:
                        raise RuntimeError('A video frame has no presentation timestamp')
                    timestamp = float(frame.pts * frame.time_base) - origin
                    requested = sampler.select(timestamp)
                    if not requested and index not in missing:
                        continue
                    if requested:
                        selected += 1
                    if index not in entries or index in missing:
                        # Preserve native YUV420 when possible; RGB is the lossless fallback.
                        storage = 'yuv420p' if frame.format.name == 'yuv420p' else 'rgb24'
                        data = frame.to_ndarray(format=storage)
                        np.save(staging / f'{index:09d}.npy', data, allow_pickle=False)
                        entries[index] = [index, timestamp, frame.width, frame.height,
                                          storage, int(frame.colorspace), int(frame.color_range)]
                    now = time.monotonic()
                    if on_progress and now - last_report >= 0.5:
                        on_progress(selected, max(total, selected))
                        last_report = now
            if not entries:
                raise RuntimeError('The video contains no decoded frames')
            if _fingerprint(source) != fingerprint:
                raise RuntimeError('The source video changed while its frame cache was being built; retry')
            ordered = [entries[key] for key in sorted(entries)]
            manifest = dict(version=VERSION, source=fingerprint, frames=ordered,
                            intervals=sorted(set(intervals + [sample_interval_seconds])),
                            duration=max(duration, ordered[-1][1] + 1 / rate), average_rate=rate)
            (staging / 'manifest.json').write_text(json.dumps(manifest))
            if previous is None and root.exists():
                shutil.rmtree(root)
            root.mkdir(exist_ok=True)
            # Existing readers retain their frames while denser coverage is published.
            for image in staging.glob('*.npy'):
                image.replace(root / image.name)
            (staging / 'manifest.json').replace(manifest_path)
            if on_progress:
                on_progress(selected, selected)
            return CachedVideo(root, manifest)
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def remove(video_path):
    root = directory(video_path)
    with _lock(root):
        shutil.rmtree(root, ignore_errors=True)
