"""Video sampling and round-classifier inference."""

from __future__ import annotations

from collections import Counter, deque
from contextvars import copy_context
from dataclasses import dataclass
import hashlib
import json
import math
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

try:
    from .sampling import TimeSampler
    from .constants import FRAME_STRIDE, SAMPLE_INTERVAL_SECONDS
    from .tracing import trace_context, trace_event, trace_resources
except ImportError:  # Running modules directly from the backend directory.
    from sampling import TimeSampler
    from constants import FRAME_STRIDE, SAMPLE_INTERVAL_SECONDS
    from tracing import trace_context, trace_event, trace_resources


def estimate_time_samples(stream, interval):
    frames = int(stream.frames or 0)
    if interval == 0:
        return frames
    duration = getattr(stream, "duration", None)
    if duration is not None and stream.time_base:
        count = math.ceil(float(duration * stream.time_base) / interval)
        return min(frames, count) if frames else count
    return 0


def sample_schedule(duration: float, interval: float = SAMPLE_INTERVAL_SECONDS) -> list[float]:
    """Return sample times strictly before the end of the video."""
    if duration <= interval:
        return []
    count = math.ceil((duration - 1e-9) / interval) - 1
    return [round(interval * index, 6) for index in range(1, max(0, count) + 1)]


def box_to_pixels(box: dict[str, float], width: int, height: int) -> tuple[int, int, int, int]:
    """Convert normalized x/y/width/height into a clamped non-empty crop."""
    x = max(0.0, min(1.0, float(box["x"])))
    y = max(0.0, min(1.0, float(box["y"])))
    right = max(x, min(1.0, x + max(0.0, float(box["width"]))))
    bottom = max(y, min(1.0, y + max(0.0, float(box["height"]))))
    x0 = min(width - 1, max(0, math.floor(x * width)))
    y0 = min(height - 1, max(0, math.floor(y * height)))
    x1 = min(width, max(x0 + 1, math.ceil(right * width)))
    y1 = min(height, max(y0 + 1, math.ceil(bottom * height)))
    return x0, y0, x1, y1


class _FrameCropConverter:
    """Convert only an aligned native frame region to the requested RGB crop."""

    def __init__(self, av_module: Any, box: dict[str, float]) -> None:
        self._av = av_module
        self._box = box
        self._graph_key: tuple[Any, ...] | None = None
        self._graph: Any | None = None
        self._source: Any | None = None
        self._sink: Any | None = None
        self._slice = (slice(0, 0), slice(0, 0))
        self._native_enabled = True
        self._fallback_logged = False
        self.graph_builds = 0
        self.native_crop_frames = 0
        self.native_crop_ms = 0.0
        self.full_rgb_frames = 0
        self.full_rgb_ms = 0.0
        self.fallback_frames = 0

    @staticmethod
    def _chroma_alignment(frame: Any) -> tuple[int, int]:
        frame_format = getattr(frame, "format", None)
        components = getattr(frame_format, "components", None)
        if frame_format is None or components is None:
            raise RuntimeError("video frame does not expose pixel-format components")
        chroma = [component for component in components if component.is_chroma]
        if not chroma:
            return 1, 1
        chroma_width = max(int(component.width) for component in chroma)
        chroma_height = max(int(component.height) for component in chroma)
        if chroma_width <= 0 or chroma_height <= 0:
            raise RuntimeError("video frame exposes invalid chroma dimensions")
        # Keep at least a two-pixel conversion context around planar YUV crops.
        # This also preserves swscale's edge interpolation for 4:2:2 and 4:4:4.
        return (
            max(2, math.ceil(frame.width / chroma_width)),
            max(2, math.ceil(frame.height / chroma_height)),
        )

    def _build_graph(
        self,
        frame: Any,
        aligned_bounds: tuple[int, int, int, int],
    ) -> tuple[Any, Any, Any]:
        left, top, right, bottom = aligned_bounds
        graph = self._av.filter.Graph()
        source = graph.add_buffer(template=frame)
        crop = graph.add(
            "crop",
            f"w={right - left}:h={bottom - top}:x={left}:y={top}:exact=1",
        )
        sink = graph.add("buffersink")
        graph.link_nodes(source, crop, sink)
        graph.configure()
        return graph, source, sink

    def _native_crop(self, frame: Any) -> Any:
        x0, y0, x1, y1 = box_to_pixels(self._box, frame.width, frame.height)
        align_x, align_y = self._chroma_alignment(frame)
        aligned_x0 = (x0 // align_x) * align_x
        aligned_y0 = (y0 // align_y) * align_y
        aligned_x1 = min(frame.width, math.ceil(x1 / align_x) * align_x)
        aligned_y1 = min(frame.height, math.ceil(y1 / align_y) * align_y)
        aligned_bounds = (aligned_x0, aligned_y0, aligned_x1, aligned_y1)
        graph_key = (
            frame.width,
            frame.height,
            frame.format.name,
            (x0, y0, x1, y1),
            aligned_bounds,
        )
        if graph_key != self._graph_key:
            self._graph, self._source, self._sink = self._build_graph(frame, aligned_bounds)
            self._graph_key = graph_key
            self._slice = (
                slice(y0 - aligned_y0, y1 - aligned_y0),
                slice(x0 - aligned_x0, x1 - aligned_x0),
            )
            self.graph_builds += 1
        assert self._source is not None and self._sink is not None
        self._source.push(frame)
        aligned_rgb = self._sink.pull().to_ndarray(format="rgb24")
        return aligned_rgb[self._slice].copy()

    def convert(self, frame: Any, include_full_frame: bool = False) -> tuple[Any, Any | None]:
        """Return the logical RGB crop and, when requested, the full RGB frame."""
        if hasattr(frame, 'crop_rgb'):
            return frame.crop_rgb(self._box, include_full_frame, self)
        if include_full_frame:
            started = time.perf_counter()
            rgb = frame.to_ndarray(format="rgb24")
            x0, y0, x1, y1 = box_to_pixels(self._box, frame.width, frame.height)
            crop = rgb[y0:y1, x0:x1].copy()
            self.full_rgb_ms += (time.perf_counter() - started) * 1000
            self.full_rgb_frames += 1
            return crop, rgb

        if self._native_enabled:
            started = time.perf_counter()
            try:
                crop = self._native_crop(frame)
            except Exception as exc:  # noqa: BLE001 - preserve the full-frame fallback
                self._native_enabled = False
                if not self._fallback_logged:
                    trace_event(
                        "native_crop_fallback",
                        error=type(exc).__name__,
                        reason=str(exc).replace(" ", "_")[:160],
                    )
                    self._fallback_logged = True
            else:
                self.native_crop_ms += (time.perf_counter() - started) * 1000
                self.native_crop_frames += 1
                return crop, None

        started = time.perf_counter()
        rgb = frame.to_ndarray(format="rgb24")
        x0, y0, x1, y1 = box_to_pixels(self._box, frame.width, frame.height)
        crop = rgb[y0:y1, x0:x1].copy()
        self.full_rgb_ms += (time.perf_counter() - started) * 1000
        self.full_rgb_frames += 1
        self.fallback_frames += 1
        return crop, None

    def trace_summary(self, selected_frames: int) -> None:
        trace_event(
            "frame_crop_summary",
            selected_frames=selected_frames,
            native_crop_frames=self.native_crop_frames,
            native_crop_ms=f"{self.native_crop_ms:.2f}",
            full_rgb_frames=self.full_rgb_frames,
            full_rgb_ms=f"{self.full_rgb_ms:.2f}",
            fallback_frames=self.fallback_frames,
            graph_builds=self.graph_builds,
        )


def decode_frame_at_timestamp(container, stream, target_seconds: float):
    """Seek by keyframe and return the nearest frame on the presentation timeline."""
    time_base = stream.time_base
    if time_base is None:
        raise RuntimeError("The video stream does not expose a time base")
    start_pts = stream.start_time or 0
    start_seconds = float(start_pts * time_base)
    target_pts = start_pts + int(target_seconds / float(time_base))
    target_absolute_seconds = start_seconds + target_seconds

    container.seek(target_pts, stream=stream, backward=True, any_frame=False)
    previous = None
    for frame in container.decode(stream):
        if frame.pts is None:
            continue
        frame_time_base = frame.time_base or time_base
        frame_absolute_seconds = float(frame.pts * frame_time_base)
        frame_relative_seconds = frame_absolute_seconds - start_seconds
        if frame_absolute_seconds + 1e-6 >= target_absolute_seconds:
            if previous is not None:
                previous_frame, previous_seconds = previous
                if abs(previous_seconds - target_seconds) <= abs(frame_relative_seconds - target_seconds):
                    return previous_frame, previous_seconds
            return frame, frame_relative_seconds
        previous = (frame, frame_relative_seconds)
    raise RuntimeError(f"Could not decode a frame at {target_seconds:.3f} seconds")


class RoundTransitionDetector:
    """Emit a round only after it dominates a short sliding window of frames."""

    window_size = 3
    minimum_votes = 2

    def __init__(self) -> None:
        self._window: deque[tuple[float, str, float]] = deque(maxlen=self.window_size)
        self._current_label: str | None = None

    def observe(self, timestamp: float, label: str, confidence: float) -> tuple[float, str, float] | None:
        self._window.append((timestamp, label, confidence))
        if len(self._window) < self.window_size:
            return None
        votes = Counter(item_label for _, item_label, _ in self._window if item_label != "unknown")
        eligible = [item_label for item_label, count in votes.items() if count >= self.minimum_votes]
        if not eligible:
            return None
        selected = max(
            eligible,
            key=lambda item_label: (
                votes[item_label],
                math.fsum(confidence for _, window_label, confidence in self._window if window_label == item_label),
                item_label,
            ),
        )
        if selected == self._current_label:
            return None
        supporting_frames = [
            (frame_timestamp, frame_confidence)
            for frame_timestamp, frame_label, frame_confidence in self._window
            if frame_label == selected
        ]
        self._current_label = selected
        return (
            supporting_frames[0][0],
            selected,
            round(
                math.fsum(frame_confidence for _, frame_confidence in supporting_frames)
                / len(supporting_frames),
                12,
            ),
        )


@dataclass
class _DecodedBatch:
    items: list[tuple[float, Any]]
    total: int


@dataclass
class _DecodeComplete:
    decoded_frames: int
    selected_frames: int
    container_open_ms: float
    decode_wait_ms: float
    crop_digest: str | None
    native_crop_frames: int
    native_crop_ms: float
    full_rgb_frames: int
    full_rgb_ms: float
    fallback_frames: int
    graph_builds: int
    producer_wait_ms: float
    max_queue_depth: int


@dataclass
class _DecodeFailure:
    error: BaseException


def _put_pipeline_item(
    pipeline_queue: queue.Queue[Any], item: Any, cancelled: threading.Event
) -> tuple[bool, float, int]:
    """Put an item without making cancellation wait on a full queue forever."""
    started = time.perf_counter()
    while not cancelled.is_set():
        try:
            pipeline_queue.put(item, timeout=0.05)
            return True, (time.perf_counter() - started) * 1000, pipeline_queue.qsize()
        except queue.Full:
            continue
    return False, (time.perf_counter() - started) * 1000, pipeline_queue.qsize()


def process_video_all_frames(
    video_path: Path,
    width: int,
    height: int,
    box: dict[str, float],
    batch_size: int,
    write_batch: Callable[[list[tuple[float, float, str, float]], str, int, int], None],
    write_collection_progress: Callable[[int, int], None],
    classifier: Any,
    frame_output_dir: Path | None = None,
    box_images: Path | None = None,
    frame_stride: int = FRAME_STRIDE,
    collect_benchmark_digests: bool = False,
    sample_interval_seconds: float | None = None,
    frame_cache: Any | None = None,
) -> tuple[int, str]:
    """Decode/crop ahead of inference with at most two live crop batches."""
    sampler = TimeSampler(sample_interval_seconds) if sample_interval_seconds is not None else None
    if frame_stride < 1:
        raise ValueError("frame_stride must be at least 1")
    try:
        import av  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyAV is required to process videos") from exc

    image_class = None
    if frame_output_dir is not None or box_images is not None:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Pillow is required when processed-image saving is enabled") from exc
        image_class = Image
    if frame_output_dir is not None:
        frame_output_dir.mkdir(parents=True, exist_ok=True)
    if box_images is not None:
        box_images.mkdir(parents=True, exist_ok=True)

    pipeline_queue: queue.Queue[_DecodedBatch | _DecodeComplete | _DecodeFailure] = queue.Queue(
        maxsize=2
    )
    batch_slots = threading.Semaphore(2)
    cancelled = threading.Event()

    def produce() -> None:
        held_slot = False
        container = None
        producer_wait_ms = 0.0
        max_queue_depth = 0
        try:
            container_open_started = time.perf_counter()
            container = frame_cache.open() if frame_cache is not None else av.open(str(video_path))
            container_open_ms = (time.perf_counter() - container_open_started) * 1000
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            trace_event(
                "video_decoder_configured",
                thread_type=str(stream.thread_type),
                thread_count=int(stream.codec_context.thread_count),
                overlap_mode="bounded_producer_consumer",
            )
            decoded_total = int(stream.frames or 0)
            total = math.ceil(decoded_total / frame_stride) if decoded_total and sampler is None else 0
            if sampler is not None:
                total = estimate_time_samples(stream, sample_interval_seconds)
            start_seconds = (
                float((stream.start_time or 0) * stream.time_base) if stream.time_base else 0.0
            )
            converter = _FrameCropConverter(av, box)
            crop_digest = hashlib.sha256() if collect_benchmark_digests else None
            decoded = 0
            selected = 0
            decode_wait_ms = 0.0
            batch: list[tuple[float, Any]] = []

            frame_iterator = iter(container.decode(stream))
            while True:
                if cancelled.is_set():
                    return
                decode_started = time.perf_counter()
                try:
                    frame = next(frame_iterator)
                except StopIteration:
                    decode_wait_ms += (time.perf_counter() - decode_started) * 1000
                    break
                decode_wait_ms += (time.perf_counter() - decode_started) * 1000
                if frame.pts is None:
                    continue
                decoded += 1
                if sampler is None and (decoded - 1) % frame_stride:
                    continue
                frame_time_base = frame.time_base or stream.time_base
                if frame_time_base is None:
                    raise RuntimeError("The video stream does not expose a time base")
                timestamp = float(frame.pts * frame_time_base) - start_seconds
                if sampler is not None and not sampler.select(timestamp):
                    continue
                if not batch:
                    wait_started = time.perf_counter()
                    while not cancelled.is_set():
                        if batch_slots.acquire(timeout=0.05):
                            held_slot = True
                            break
                    producer_wait_ms += (time.perf_counter() - wait_started) * 1000
                    if cancelled.is_set():
                        return
                crop, rgb = converter.convert(
                    frame, include_full_frame=frame_output_dir is not None
                )
                if crop_digest is not None:
                    crop_digest.update(str(crop.shape).encode("ascii"))
                    crop_digest.update(str(crop.dtype).encode("ascii"))
                    crop_digest.update(crop.tobytes(order="C"))
                selected += 1
                if frame_output_dir is not None and image_class is not None:
                    assert rgb is not None
                    image_class.fromarray(rgb).save(
                        frame_output_dir / f"{decoded:06d}_{timestamp:.6f}s.png"
                    )
                if box_images is not None and image_class is not None:
                    image_class.fromarray(crop).save(
                        box_images / f"{decoded:06d}_{timestamp:.6f}s.png"
                    )
                batch.append((timestamp, crop))
                if len(batch) == batch_size:
                    sent, waited, depth = _put_pipeline_item(
                        pipeline_queue, _DecodedBatch(batch, total or selected), cancelled
                    )
                    producer_wait_ms += waited
                    max_queue_depth = max(max_queue_depth, depth)
                    if not sent:
                        return
                    held_slot = False
                    batch = []

            if batch:
                sent, waited, depth = _put_pipeline_item(
                    pipeline_queue, _DecodedBatch(batch, total or selected), cancelled
                )
                producer_wait_ms += waited
                max_queue_depth = max(max_queue_depth, depth)
                if not sent:
                    return
                held_slot = False
            completion = _DecodeComplete(
                decoded_frames=decoded,
                selected_frames=selected,
                container_open_ms=container_open_ms,
                decode_wait_ms=decode_wait_ms,
                crop_digest=crop_digest.hexdigest() if crop_digest is not None else None,
                native_crop_frames=converter.native_crop_frames,
                native_crop_ms=converter.native_crop_ms,
                full_rgb_frames=converter.full_rgb_frames,
                full_rgb_ms=converter.full_rgb_ms,
                fallback_frames=converter.fallback_frames,
                graph_builds=converter.graph_builds,
                producer_wait_ms=producer_wait_ms,
                max_queue_depth=max_queue_depth,
            )
            _put_pipeline_item(pipeline_queue, completion, cancelled)
        except BaseException as exc:  # propagate producer failures to the job thread
            if held_slot:
                batch_slots.release()
                held_slot = False
            _put_pipeline_item(pipeline_queue, _DecodeFailure(exc), cancelled)
        finally:
            if held_slot:
                batch_slots.release()
            if container is not None:
                container.close()

    producer_context = copy_context()
    producer = threading.Thread(
        target=lambda: producer_context.run(produce),
        name="video-decode-producer",
        daemon=True,
    )
    try:
        producer.start()
    except RuntimeError:
        trace_event("video_overlap_fallback", reason="thread_start_failed")
        return _process_video_all_frames_sequential(
            video_path, width, height, box, batch_size, write_batch,
            write_collection_progress, classifier, frame_output_dir, box_images,
            frame_stride, collect_benchmark_digests, sample_interval_seconds, frame_cache,
        )

    processed = 0
    collected = 0
    batch_index = 0
    consumer_wait_ms = 0.0
    device = classifier.device_label
    detector = RoundTransitionDetector()
    prediction_digest = hashlib.sha256() if collect_benchmark_digests else None
    completion: _DecodeComplete | None = None
    try:
        while completion is None:
            wait_started = time.perf_counter()
            item = pipeline_queue.get()
            consumer_wait_ms += (time.perf_counter() - wait_started) * 1000
            if isinstance(item, _DecodeFailure):
                raise item.error
            if isinstance(item, _DecodeComplete):
                completion = item
                continue
            batch = item.items
            try:
                for _ in batch:
                    collected += 1
                    write_collection_progress(collected, item.total)
                batch_index += 1
                actual_batch_size = len(batch)
                batch_started = time.perf_counter()
                with trace_context(
                    batch_index=batch_index,
                    actual_batch_size=actual_batch_size,
                    batch_capacity=batch_size,
                ):
                    predictions = classifier.predict_batch([crop for _, crop in batch])
                if prediction_digest is not None:
                    for label, confidence in predictions:
                        prediction_digest.update(
                            json.dumps([label, float(confidence)], separators=(",", ":")).encode(
                                "utf-8"
                            )
                        )
                        prediction_digest.update(b"\n")
                transitions: list[tuple[float, float, str, float]] = []
                for (timestamp, _), (label, confidence) in zip(
                    batch, predictions, strict=True
                ):
                    transition = detector.observe(timestamp, label, confidence)
                    if transition is not None:
                        transition_timestamp, transition_label, transition_confidence = transition
                        transitions.append(
                            (
                                transition_timestamp,
                                transition_timestamp,
                                transition_label,
                                transition_confidence,
                            )
                        )
                processed += actual_batch_size
                write_batch(transitions, device, processed, item.total or processed)
                trace_event(
                    "processing_batch",
                    batch_index=batch_index,
                    actual_batch_size=actual_batch_size,
                    batch_capacity=batch_size,
                    progress=f"{processed}/{item.total or processed}",
                    device=device,
                    batch_ms=f"{(time.perf_counter() - batch_started) * 1000:.2f}",
                    overlap_mode="bounded_producer_consumer",
                )
                trace_resources(
                    "batch_complete",
                    batch_index=batch_index,
                    actual_batch_size=actual_batch_size,
                    batch_capacity=batch_size,
                )
            finally:
                batch_slots.release()
    except BaseException:
        cancelled.set()
        while True:
            try:
                pending = pipeline_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(pending, _DecodedBatch):
                batch_slots.release()
        producer.join(timeout=5)
        raise
    finally:
        cancelled.set()
        producer.join(timeout=5)

    assert completion is not None
    trace_event(
        "frame_crop_summary",
        selected_frames=completion.selected_frames,
        native_crop_frames=completion.native_crop_frames,
        native_crop_ms=f"{completion.native_crop_ms:.2f}",
        full_rgb_frames=completion.full_rgb_frames,
        full_rgb_ms=f"{completion.full_rgb_ms:.2f}",
        fallback_frames=completion.fallback_frames,
        graph_builds=completion.graph_builds,
    )
    trace_event(
        "video_decode_summary",
        decoded_frames=completion.decoded_frames,
        selected_frames=completion.selected_frames,
        container_open_ms=f"{completion.container_open_ms:.2f}",
        decode_wait_ms=f"{completion.decode_wait_ms:.2f}",
        average_decode_wait_ms=(
            f"{completion.decode_wait_ms / completion.decoded_frames:.4f}"
            if completion.decoded_frames
            else "0.0000"
        ),
        crop_digest=completion.crop_digest,
        prediction_digest=(prediction_digest.hexdigest() if prediction_digest is not None else None),
    )
    trace_event(
        "video_overlap_summary",
        overlap_mode="bounded_producer_consumer",
        producer_wait_ms=f"{completion.producer_wait_ms:.2f}",
        consumer_wait_ms=f"{consumer_wait_ms:.2f}",
        max_queue_depth=completion.max_queue_depth,
        batch_slots=2,
    )
    return processed, device


def process_cached_crops(
    cache_dir: Path,
    batch_size: int,
    write_batch: Callable[[list[tuple[float, float, str, float]], str, int, int], None],
    write_collection_progress: Callable[[int, int], None],
    classifier: Any,
    frame_stride: int = FRAME_STRIDE,
    sample_interval_seconds: float | None = None,
) -> tuple[int, str]:
    """Run inference on the exact lossless crops produced by an earlier decode."""
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("The cached OCR crops are missing or incomplete; re-decode the video")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    compatible = (
        manifest.get("version") == 2 and manifest.get("sample_interval_seconds") == sample_interval_seconds
        if sample_interval_seconds is not None
        else manifest.get("version") == 1 and manifest.get("frame_stride") == frame_stride
    )
    if not compatible:
        raise RuntimeError("The cached OCR crops are incompatible; re-decode the video")
    entries = manifest.get("crops")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("The cached OCR crop set is empty; re-decode the video")
    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("NumPy and Pillow are required to reuse cached OCR crops") from exc

    total = len(entries)
    processed = 0
    detector = RoundTransitionDetector()
    device = classifier.device_label
    for offset in range(0, total, batch_size):
        chunk = entries[offset : offset + batch_size]
        batch: list[tuple[float, Any]] = []
        for entry in chunk:
            crop_path = cache_dir / str(entry["file"])
            if not crop_path.is_file():
                raise RuntimeError("A cached OCR crop is missing; re-decode the video")
            with Image.open(crop_path) as image:
                batch.append((float(entry["timestamp"]), np.asarray(image.convert("RGB")).copy()))
            write_collection_progress(processed + len(batch), total)

        predictions = classifier.predict_batch([crop for _, crop in batch])
        transitions: list[tuple[float, float, str, float]] = []
        for (timestamp, _), (label, confidence) in zip(batch, predictions, strict=True):
            transition = detector.observe(timestamp, label, confidence)
            if transition is not None:
                transition_timestamp, transition_label, transition_confidence = transition
                transitions.append(
                    (transition_timestamp, transition_timestamp, transition_label, transition_confidence)
                )
        processed += len(batch)
        write_batch(transitions, device, processed, total)
        trace_event(
            "cached_ocr_batch",
            actual_batch_size=len(batch),
            progress=f"{processed}/{total}",
            device=device,
        )
    return processed, device


def _process_video_all_frames_sequential(
    video_path: Path,
    width: int,
    height: int,
    box: dict[str, float],
    batch_size: int,
    write_batch: Callable[[list[tuple[float, float, str, float]], str, int, int], None],
    write_collection_progress: Callable[[int, int], None],
    classifier: Any,
    frame_output_dir: Path | None = None,
    box_images: Path | None = None,
    frame_stride: int = FRAME_STRIDE,
    collect_benchmark_digests: bool = False,
    sample_interval_seconds: float | None = None,
    frame_cache: Any | None = None,
) -> tuple[int, str]:
    """Classify every ``frame_stride``-th decoded frame in inference batches."""
    sampler = TimeSampler(sample_interval_seconds) if sample_interval_seconds is not None else None
    if frame_stride < 1:
        raise ValueError("frame_stride must be at least 1")
    try:
        import av  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyAV is required to process videos") from exc

    image_class = None
    if frame_output_dir is not None or box_images is not None:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Pillow is required when processed-image saving is enabled") from exc
        image_class = Image
    if frame_output_dir is not None:
        frame_output_dir.mkdir(parents=True, exist_ok=True)
    if box_images is not None:
        box_images.mkdir(parents=True, exist_ok=True)

    container_open_started = time.perf_counter()
    container = frame_cache.open() if frame_cache is not None else av.open(str(video_path))
    container_open_ms = (time.perf_counter() - container_open_started) * 1000
    processed = 0
    decoded = 0
    device = classifier.device_label
    detector = RoundTransitionDetector()
    batch: list[tuple[float, Any]] = []
    crop_converter = _FrameCropConverter(av, box)
    selected_frames = 0
    decode_wait_ms = 0.0
    batch_index = 0
    crop_digest = hashlib.sha256() if collect_benchmark_digests else None
    prediction_digest = hashlib.sha256() if collect_benchmark_digests else None
    try:
        stream = container.streams.video[0]
        # PyAV defaults to slice threading, which leaves codecs without multiple
        # slices effectively single-threaded. AUTO also enables frame threading
        # while preserving decoded presentation order.
        stream.thread_type = "AUTO"
        trace_event(
            "video_decoder_configured",
            thread_type=str(stream.thread_type),
            thread_count=int(stream.codec_context.thread_count),
        )
        decoded_total = int(stream.frames or 0)
        total = math.ceil(decoded_total / frame_stride) if decoded_total and sampler is None else 0
        if sampler is not None:
            total = estimate_time_samples(stream, sample_interval_seconds)
        start_seconds = float((stream.start_time or 0) * stream.time_base) if stream.time_base else 0.0

        def classify_batch() -> None:
            nonlocal batch_index, processed
            if not batch:
                return
            batch_index += 1
            batch_started = time.perf_counter()
            actual_batch_size = len(batch)
            with trace_context(
                batch_index=batch_index,
                actual_batch_size=actual_batch_size,
                batch_capacity=batch_size,
            ):
                predictions = classifier.predict_batch([crop for _, crop in batch])
            if prediction_digest is not None:
                for label, confidence in predictions:
                    prediction_digest.update(
                        json.dumps(
                            [label, float(confidence)], separators=(",", ":")
                        ).encode("utf-8")
                    )
                    prediction_digest.update(b"\n")
            transitions: list[tuple[float, float, str, float]] = []
            for (timestamp, _), (label, confidence) in zip(batch, predictions, strict=True):
                transition = detector.observe(timestamp, label, confidence)
                if transition is not None:
                    transition_timestamp, transition_label, transition_confidence = transition
                    transitions.append((transition_timestamp, transition_timestamp, transition_label, transition_confidence))
            processed += len(batch)
            write_batch(transitions, device, processed, total or processed)
            trace_event(
                "processing_batch",
                batch_index=batch_index,
                actual_batch_size=actual_batch_size,
                batch_capacity=batch_size,
                progress=f"{processed}/{total or processed}",
                device=device,
                batch_ms=f"{(time.perf_counter() - batch_started) * 1000:.2f}",
            )
            trace_resources(
                "batch_complete",
                batch_index=batch_index,
                actual_batch_size=actual_batch_size,
                batch_capacity=batch_size,
            )
            batch.clear()

        frame_iterator = iter(container.decode(stream))
        while True:
            decode_started = time.perf_counter()
            try:
                frame = next(frame_iterator)
            except StopIteration:
                decode_wait_ms += (time.perf_counter() - decode_started) * 1000
                break
            decode_wait_ms += (time.perf_counter() - decode_started) * 1000
            if frame.pts is None:
                continue
            decoded += 1
            if sampler is None and (decoded - 1) % frame_stride:
                continue
            frame_time_base = frame.time_base or stream.time_base
            if frame_time_base is None:
                raise RuntimeError("The video stream does not expose a time base")
            timestamp = float(frame.pts * frame_time_base) - start_seconds
            if sampler is not None and not sampler.select(timestamp):
                continue
            crop, rgb = crop_converter.convert(
                frame,
                include_full_frame=frame_output_dir is not None,
            )
            if crop_digest is not None:
                crop_digest.update(str(crop.shape).encode("ascii"))
                crop_digest.update(str(crop.dtype).encode("ascii"))
                crop_digest.update(crop.tobytes(order="C"))
            selected_frames += 1
            if frame_output_dir is not None and image_class is not None:
                assert rgb is not None
                image_class.fromarray(rgb).save(frame_output_dir / f"{decoded:06d}_{timestamp:.6f}s.png")
            if box_images is not None and image_class is not None:
                image_class.fromarray(crop).save(box_images / f"{decoded:06d}_{timestamp:.6f}s.png")
            batch.append((timestamp, crop))
            selected = processed + len(batch)
            write_collection_progress(selected, total or selected)
            if len(batch) >= batch_size:
                classify_batch()
        classify_batch()
        crop_converter.trace_summary(selected_frames)
        trace_event(
            "video_decode_summary",
            decoded_frames=decoded,
            selected_frames=selected_frames,
            container_open_ms=f"{container_open_ms:.2f}",
            decode_wait_ms=f"{decode_wait_ms:.2f}",
            average_decode_wait_ms=f"{decode_wait_ms / decoded:.4f}" if decoded else "0.0000",
            crop_digest=crop_digest.hexdigest() if crop_digest is not None else None,
            prediction_digest=(
                prediction_digest.hexdigest() if prediction_digest is not None else None
            ),
        )
    finally:
        container.close()
    return processed, device


def process_video(
    video_path: Path,
    duration: float,
    width: int,
    height: int,
    box: dict[str, float],
    batch_size: int,
    write_batch: Callable[[list[tuple[float, float, str, float]], str, int, int], None],
    write_collection_progress: Callable[[int, int], None],
    classifier: Any,
    sample_interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
    frame_output_dir: Path | None = None,
    box_images: Path | None = None,
) -> tuple[int, str]:
    """Collect every scheduled crop, then process them in fixed-size batches."""
    try:
        import av  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyAV is required to process videos") from exc

    schedule = sample_schedule(duration, sample_interval_seconds)
    if not schedule:
        trace_event("video_process_skipped", reason="no_scheduled_samples", duration_seconds=duration)
        return 0, "cpu"

    process_started = time.perf_counter()
    collection_started = time.perf_counter()
    collected, container_open_ms = _collect_scheduled_crops(
        av,
        video_path,
        schedule,
        width,
        height,
        box,
        write_collection_progress,
        frame_output_dir,
        box_images,
    )

    if len(collected) != len(schedule):
        raise RuntimeError(f"Decoded {len(collected)} of {len(schedule)} scheduled sample frames")

    collection_ms = (time.perf_counter() - collection_started) * 1000
    batches_started = time.perf_counter()
    processed, device = _process_collected_crops(
        collected,
        len(schedule),
        batch_size,
        write_batch,
        classifier,
    )
    batches_ms = (time.perf_counter() - batches_started) * 1000
    trace_event(
        "video_process_complete",
        samples=processed,
        batches=math.ceil(processed / batch_size),
        batch_size=batch_size,
        device=device,
        container_open_ms=f"{container_open_ms:.2f}",
        collection_ms=f"{collection_ms:.2f}",
        processing_ms=f"{batches_ms:.2f}",
        total_ms=f"{(time.perf_counter() - process_started) * 1000:.2f}",
    )
    return processed, device


def _collect_scheduled_crops(
    av: Any,
    video_path: Path,
    schedule: list[float],
    width: int,
    height: int,
    box: dict[str, float],
    write_collection_progress: Callable[[int, int], None],
    frame_output_dir: Path | None,
    box_images: Path | None,
) -> tuple[list[tuple[float, float, Any]], float]:
    """Decode scheduled frames and collect their cropped image data."""
    image_class = _prepare_image_output(frame_output_dir, box_images)
    collected: list[tuple[float, float, Any]] = []
    crop_converter = _FrameCropConverter(av, box)
    container_open_started = time.perf_counter()
    container = av.open(str(video_path))
    container_open_ms = (time.perf_counter() - container_open_started) * 1000
    try:
        stream = container.streams.video[0]
        for sample_index, target in enumerate(schedule, start=1):
            decode_started = time.perf_counter()
            frame, actual_timestamp = decode_frame_at_timestamp(container, stream, target)
            decode_ms = (time.perf_counter() - decode_started) * 1000
            crop_started = time.perf_counter()
            crop, rgb = crop_converter.convert(
                frame,
                include_full_frame=frame_output_dir is not None,
            )
            frame_name = f"{sample_index:06d}_{target:.6f}s.png"
            if frame_output_dir is not None and image_class is not None:
                assert rgb is not None
                image_class.fromarray(rgb).save(frame_output_dir / frame_name)
            if box_images is not None and image_class is not None:
                image_class.fromarray(crop).save(box_images / frame_name)
            crop_ms = (time.perf_counter() - crop_started) * 1000
            collected.append((target, actual_timestamp, crop))
            trace_event(
                "frame_collected", sample=f"{sample_index}/{len(schedule)}",
                scheduled_seconds=f"{target:.3f}", actual_seconds=f"{actual_timestamp:.3f}",
                timing_error_ms=f"{(actual_timestamp - target) * 1000:.2f}",
                seek_decode_ms=f"{decode_ms:.2f}", convert_crop_ms=f"{crop_ms:.2f}",
                crop_pixels=f"{crop.shape[1]}x{crop.shape[0]}",
            )
            write_collection_progress(len(collected), len(schedule))
    finally:
        container.close()
    crop_converter.trace_summary(len(collected))
    return collected, container_open_ms


def _prepare_image_output(frame_output_dir: Path | None, box_images: Path | None) -> Any | None:
    """Load Pillow and create output directories when image saving is enabled."""
    image_class = None
    if frame_output_dir is not None or box_images is not None:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Pillow is required when processed-image saving is enabled") from exc
        image_class = Image
    if frame_output_dir is not None:
        frame_output_dir.mkdir(parents=True, exist_ok=True)
    if box_images is not None:
        box_images.mkdir(parents=True, exist_ok=True)
    return image_class


def _process_collected_crops(
    collected: list[tuple[float, float, Any]],
    total: int,
    batch_size: int,
    write_batch: Callable[[list[tuple[float, float, str, float]], str, int, int], None],
    classifier: Any,
) -> tuple[int, str]:
    """Classify collected crops in batches and write ordered predictions."""
    processed = 0
    device = classifier.device_label
    for batch_index, offset in enumerate(range(0, len(collected), batch_size), start=1):
        batch_started = time.perf_counter()
        chunk = collected[offset:offset + batch_size]
        predictions = classifier.predict_batch([entry[2] for entry in chunk])
        ordered = [
            (scheduled_timestamp, actual_timestamp, label, confidence)
            for (scheduled_timestamp, actual_timestamp, _), (label, confidence) in zip(
                chunk, predictions, strict=True,
            )
        ]
        processed += len(ordered)
        write_batch(ordered, device, processed, total)
        trace_event(
            "processing_batch", batch=batch_index, samples=len(ordered),
            progress=f"{processed}/{total}", device=device,
            batch_ms=f"{(time.perf_counter() - batch_started) * 1000:.2f}",
        )
    return processed, device
