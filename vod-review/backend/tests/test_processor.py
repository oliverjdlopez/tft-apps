import subprocess
import threading
import time
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from backend.processor import (
    _FrameCropConverter,
    RoundTransitionDetector,
    box_to_pixels,
    decode_frame_at_timestamp,
    process_video,
    process_video_all_frames,
    process_cached_crops,
    sample_schedule,
)
from backend.tracing import capture_trace_events, trace_context
from round_classifier.predict import OCRRoundClassifierPredictor


class FakeClassifier:
    device_label = "cpu"
    labels = ("red", "green", "blue")

    def predict_batch(self, crops):
        return [
            (self.labels[int(crop.mean(axis=(0, 1)).argmax())], 0.9)
            for crop in crops
        ]


class RecordingClassifier(FakeClassifier):
    def __init__(self):
        self.batch_lengths = []

    def predict_batch(self, crops):
        self.batch_lengths.append(len(crops))
        return super().predict_batch(crops)


def make_video_frame(pixel_format: str, width: int = 18, height: int = 14, offset: int = 0):
    import av

    y, x = np.indices((height, width))
    rgb = np.stack(
        (
            (x * 13 + offset) % 256,
            (y * 17 + offset * 3) % 256,
            ((x + y) * 11 + offset * 5) % 256,
        ),
        axis=2,
    ).astype(np.uint8)
    frame = av.VideoFrame.from_ndarray(rgb, format="rgb24").reformat(format=pixel_format)
    frame.time_base = Fraction(1, 30)
    return frame


def test_ocr_classifier_returns_parsed_label_predictions(monkeypatch):
    monkeypatch.setattr(
        "round_classifier.ocr.detect_and_recognize_round_images",
        lambda _images, class_names, minimum_confidence: [
            {"prediction": {"parsed_label": class_names[1], "ocr_confidence": 0.91}},
            {"prediction": None},
        ],
    )
    classifier = OCRRoundClassifierPredictor(("31", "32"))

    assert classifier.device_label == "ocr"
    assert classifier.predict_batch([
        np.zeros((2, 2, 3), dtype=np.uint8),
        np.zeros((2, 2, 3), dtype=np.uint8),
    ]) == [("32", 0.91), ("unknown", 0.0)]


def test_cached_crops_reuse_the_exact_saved_pixels(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    crop_dir = cache_dir / "crops"
    crop_dir.mkdir(parents=True)
    first = np.full((4, 5, 3), (255, 0, 0), dtype=np.uint8)
    second = np.full((4, 5, 3), (0, 255, 0), dtype=np.uint8)
    Image.fromarray(first).save(crop_dir / "000001_0.000000s.png")
    Image.fromarray(second).save(crop_dir / "000031_1.000000s.png")
    (cache_dir / "manifest.json").write_text(
        '{"version":1,"frame_stride":30,"crops":['
        '{"file":"crops/000001_0.000000s.png","timestamp":0.0},'
        '{"file":"crops/000031_1.000000s.png","timestamp":1.0}]}'
    )
    classifier = RecordingClassifier()
    writes = []
    collection = []

    processed, device = process_cached_crops(
        cache_dir,
        2,
        lambda results, run_device, progress, total: writes.append(
            (results, run_device, progress, total)
        ),
        lambda progress, total: collection.append((progress, total)),
        classifier,
    )

    assert processed == 2
    assert device == "cpu"
    assert classifier.batch_lengths == [2]
    assert collection == [(1, 2), (2, 2)]
    assert writes[0][2:] == (2, 2)


def test_round_transition_detector_requires_a_sliding_window_majority():
    detector = RoundTransitionDetector()
    predictions = [("31", 0.9)] * 10 + [("unknown", 0.0)] * 5

    transitions = [
        detector.observe(index / 30, label, confidence)
        for index, (label, confidence) in enumerate(predictions)
    ]

    assert [transition for transition in transitions if transition is not None] == [(0.0, "31", 0.9)]
    assert detector.observe(0.5, "32", 0.9) is None


def test_sample_schedule_stops_before_duration():
    assert sample_schedule(4.99) == []
    assert sample_schedule(5.0) == []
    assert sample_schedule(10.0) == [5.0]
    assert sample_schedule(12.2) == [5.0, 10.0]
    assert sample_schedule(3.1, interval=1.0) == [1.0, 2.0, 3.0]


def test_box_to_pixels_clamps_and_keeps_non_empty_crop():
    assert box_to_pixels({"x": 0.1, "y": 0.25, "width": 0.5, "height": 0.5}, 100, 80) == (10, 20, 60, 60)
    assert box_to_pixels({"x": 0.99, "y": 0.99, "width": 0.5, "height": 0.5}, 100, 80) == (99, 79, 100, 80)


@pytest.mark.parametrize("pixel_format", ["yuv420p", "yuv422p", "yuv444p", "rgb24"])
@pytest.mark.parametrize(
    "box",
    [
        {"x": 1 / 18, "y": 1 / 14, "width": 10 / 18, "height": 8 / 14},
        {"x": 2 / 18, "y": 2 / 14, "width": 8 / 18, "height": 6 / 14},
        {"x": 17 / 18, "y": 13 / 14, "width": 0.5, "height": 0.5},
    ],
)
def test_native_crop_matches_full_rgb_conversion(pixel_format, box):
    import av

    frame = make_video_frame(pixel_format)
    expected_rgb = frame.to_ndarray(format="rgb24")
    x0, y0, x1, y1 = box_to_pixels(box, frame.width, frame.height)
    expected = expected_rgb[y0:y1, x0:x1].copy()

    actual, full_rgb = _FrameCropConverter(av, box).convert(frame)

    assert full_rgb is None
    assert actual.flags.c_contiguous
    assert np.array_equal(actual, expected)


def test_native_crop_reuses_and_rebuilds_filter_graph():
    import av

    box = {"x": 1 / 18, "y": 1 / 14, "width": 10 / 18, "height": 8 / 14}
    converter = _FrameCropConverter(av, box)

    converter.convert(make_video_frame("yuv420p", offset=1))
    converter.convert(make_video_frame("yuv420p", offset=2))
    assert converter.graph_builds == 1

    converter.convert(make_video_frame("yuv444p", offset=3))
    assert converter.graph_builds == 2

    converter.convert(make_video_frame("yuv444p", width=20, height=16, offset=4))
    assert converter.graph_builds == 3


def test_native_crop_falls_back_once_and_disables_failed_filter(monkeypatch):
    import av

    box = {"x": 1 / 18, "y": 1 / 14, "width": 10 / 18, "height": 8 / 14}
    converter = _FrameCropConverter(av, box)
    build_calls = []
    trace_calls = []

    def fail_build(*_args):
        build_calls.append(True)
        raise RuntimeError("unsupported test format")

    monkeypatch.setattr(converter, "_build_graph", fail_build)
    monkeypatch.setattr("backend.processor.trace_event", lambda event, **fields: trace_calls.append((event, fields)))

    for offset in (1, 2):
        frame = make_video_frame("yuv420p", offset=offset)
        expected_rgb = frame.to_ndarray(format="rgb24")
        x0, y0, x1, y1 = box_to_pixels(box, frame.width, frame.height)
        crop, full_rgb = converter.convert(frame)
        assert full_rgb is None
        assert np.array_equal(crop, expected_rgb[y0:y1, x0:x1])

    assert len(build_calls) == 1
    assert [event for event, _ in trace_calls] == ["native_crop_fallback"]
    assert converter.fallback_frames == 2


def test_full_frame_request_uses_one_full_conversion():
    import av

    box = {"x": 1 / 18, "y": 1 / 14, "width": 10 / 18, "height": 8 / 14}
    frame = make_video_frame("yuv420p")
    converter = _FrameCropConverter(av, box)

    crop, full_rgb = converter.convert(frame, include_full_frame=True)
    x0, y0, x1, y1 = box_to_pixels(box, frame.width, frame.height)

    assert full_rgb is not None
    assert np.array_equal(crop, full_rgb[y0:y1, x0:x1])
    assert converter.full_rgb_frames == 1
    assert converter.native_crop_frames == 0


def test_timestamp_seek_selects_the_nearest_presented_frame():
    class Stream:
        time_base = Fraction(1, 10)
        start_time = 0

    class Frame:
        time_base = Fraction(1, 10)

        def __init__(self, pts: int):
            self.pts = pts

    class Container:
        seek_args = None

        def seek(self, *args, **kwargs):
            self.seek_args = (args, kwargs)

        def decode(self, _stream):
            return iter([Frame(48), Frame(53)])

    container = Container()
    frame, actual = decode_frame_at_timestamp(container, Stream(), 5.0)
    assert frame.pts == 48
    assert actual == 4.8
    seek_args, seek_options = container.seek_args
    assert seek_args == (50,)
    assert seek_options["backward"] is True
    assert seek_options["any_frame"] is False


def test_keyframe_seeking_collects_the_correct_temporal_frames(tmp_path: Path):
    video = tmp_path / "segments.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=64x64:d=5:r=10",
            "-f", "lavfi", "-i", "color=c=green:s=64x64:d=5:r=10",
            "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=2:r=10",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map", "[v]", "-c:v", "libx264", "-g", "20", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        capture_output=True,
    )
    results: list[tuple[float, float, str, float]] = []
    collection_progress: list[tuple[int, int]] = []

    processed, _ = process_video(
        video,
        duration=12,
        width=64,
        height=64,
        box={"x": 0, "y": 0, "width": 1, "height": 1},
        batch_size=2,
        write_batch=lambda batch, _device, _progress, _total: results.extend(batch),
        write_collection_progress=lambda collected, total: collection_progress.append((collected, total)),
        classifier=FakeClassifier(),
    )

    assert processed == 2
    assert collection_progress == [(1, 2), (2, 2)]
    assert [timestamp for timestamp, _, _, _ in results] == [5.0, 10.0]
    assert abs(results[0][1] - 5.0) <= 0.05
    assert abs(results[1][1] - 10.0) <= 0.05
    assert results[0][2:] == ("green", 0.9)
    assert results[1][2:] == ("blue", 0.9)


def test_processed_frames_and_bounding_boxes_can_be_saved(tmp_path: Path):
    video = tmp_path / "red.mp4"
    frame_output = tmp_path / "frames" / "video-id"
    box_output = tmp_path / "boxes" / "video-id"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=32x24:d=2.1:r=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        capture_output=True,
    )

    processed, _ = process_video(
        video,
        duration=2.1,
        width=32,
        height=24,
        box={"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
        batch_size=2,
        write_batch=lambda *_args: None,
        write_collection_progress=lambda *_args: None,
        classifier=FakeClassifier(),
        sample_interval_seconds=1.0,
        frame_output_dir=frame_output,
        box_images=box_output,
    )

    assert processed == 2
    expected_names = [
        "000001_1.000000s.png",
        "000002_2.000000s.png",
    ]
    assert sorted(path.name for path in frame_output.glob("*.png")) == expected_names
    assert sorted(path.name for path in box_output.glob("*.png")) == expected_names
    with Image.open(frame_output / expected_names[0]) as frame_image:
        assert frame_image.size == (32, 24)
    with Image.open(box_output / expected_names[0]) as box_image:
        assert box_image.size == (16, 12)


def test_all_frames_processing_selects_before_conversion_and_batches(tmp_path: Path):
    video = tmp_path / "frames.mp4"
    box_output = tmp_path / "boxes"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=32x24:d=3:r=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        capture_output=True,
    )
    classifier = RecordingClassifier()
    collection_progress = []

    with trace_context(job_id="trace-job", video_id="trace-video"), capture_trace_events() as events:
        processed, _ = process_video_all_frames(
            video,
            width=32,
            height=24,
            box={"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
            batch_size=2,
            write_batch=lambda *_args: None,
            write_collection_progress=lambda selected, total: collection_progress.append((selected, total)),
            classifier=classifier,
            box_images=box_output,
            frame_stride=10,
            collect_benchmark_digests=True,
        )

    assert processed == 3
    assert classifier.batch_lengths == [2, 1]
    assert collection_progress == [(1, 3), (2, 3), (3, 3)]
    assert len(list(box_output.glob("*.png"))) == 3
    with Image.open(sorted(box_output.glob("*.png"))[0]) as box_image:
        assert box_image.size == (16, 12)
    batch_events = [event for event in events if event["event"] == "processing_batch"]
    assert [event["batch_index"] for event in batch_events] == [1, 2]
    assert [event["actual_batch_size"] for event in batch_events] == [2, 1]
    assert all(event["batch_capacity"] == 2 for event in batch_events)
    assert all(event["job_id"] == "trace-job" for event in batch_events)
    decode_event = next(event for event in events if event["event"] == "video_decode_summary")
    assert decode_event["decoded_frames"] == 30
    assert decode_event["selected_frames"] == 3
    assert float(decode_event["container_open_ms"]) >= 0
    assert len(decode_event["crop_digest"]) == 64
    assert len(decode_event["prediction_digest"]) == 64
    decoder_event = next(
        event for event in events if event["event"] == "video_decoder_configured"
    )
    assert decoder_event["thread_type"] == "ThreadType.AUTO"
    assert decoder_event["thread_count"] == 0
    assert decoder_event["job_id"] == "trace-job"


def test_all_frames_processing_decodes_ahead_while_classifier_is_running(tmp_path: Path):
    video = tmp_path / "overlap.mp4"
    box_output = tmp_path / "boxes"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=32x24:d=1:r=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        capture_output=True,
    )

    class OverlapClassifier(RecordingClassifier):
        def predict_batch(self, crops):
            if not self.batch_lengths:
                deadline = time.monotonic() + 2
                while len(list(box_output.glob("*.png"))) < 4 and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert len(list(box_output.glob("*.png"))) >= 4
            return super().predict_batch(crops)

    classifier = OverlapClassifier()
    with capture_trace_events() as events:
        processed, _ = process_video_all_frames(
            video,
            width=32,
            height=24,
            box={"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
            batch_size=2,
            write_batch=lambda *_args: None,
            write_collection_progress=lambda *_args: None,
            classifier=classifier,
            box_images=box_output,
            frame_stride=1,
        )

    assert processed == 6
    assert classifier.batch_lengths == [2, 2, 2]
    overlap = next(event for event in events if event["event"] == "video_overlap_summary")
    assert overlap["overlap_mode"] == "bounded_producer_consumer"
    assert overlap["batch_slots"] == 2
    assert overlap["max_queue_depth"] <= 2


def test_all_frames_processing_propagates_classifier_failure_without_hanging(tmp_path: Path):
    video = tmp_path / "classifier-failure.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=32x24:d=1:r=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        capture_output=True,
    )

    class FailingClassifier(FakeClassifier):
        def predict_batch(self, crops):
            raise RuntimeError("classifier failed")

    with pytest.raises(RuntimeError, match="classifier failed"):
        process_video_all_frames(
            video, 32, 24,
            {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
            2, lambda *_args: None, lambda *_args: None, FailingClassifier(),
            frame_stride=1,
        )


def test_all_frames_processing_propagates_producer_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    video = tmp_path / "producer-failure.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=32x24:d=1:r=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(
        _FrameCropConverter,
        "convert",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crop failed")),
    )

    with pytest.raises(RuntimeError, match="crop failed"):
        process_video_all_frames(
            video, 32, 24,
            {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
            2, lambda *_args: None, lambda *_args: None, FakeClassifier(),
            frame_stride=1,
        )


def test_all_frames_processing_cancels_producer_when_callback_fails(tmp_path: Path):
    video = tmp_path / "callback-failure.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=32x24:d=1:r=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        capture_output=True,
    )

    def fail_progress(*_args):
        raise RuntimeError("progress failed")

    with pytest.raises(RuntimeError, match="progress failed"):
        process_video_all_frames(
            video, 32, 24,
            {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
            2, lambda *_args: None, fail_progress, FakeClassifier(),
            frame_stride=1,
        )


def test_all_frames_processing_falls_back_when_thread_start_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    video = tmp_path / "fallback.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=32x24:d=1:r=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(threading.Thread, "start", lambda _self: (_ for _ in ()).throw(
        RuntimeError("threads unavailable")
    ))
    classifier = RecordingClassifier()

    with capture_trace_events() as events:
        processed, _ = process_video_all_frames(
            video, 32, 24,
            {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
            2, lambda *_args: None, lambda *_args: None, classifier,
            frame_stride=1,
        )

    assert processed == 4
    assert classifier.batch_lengths == [2, 2]
    assert any(event["event"] == "video_overlap_fallback" for event in events)
