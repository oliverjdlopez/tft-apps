"""Repeatable fixed-frame benchmark for the production round pipeline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from typing import Any
import uuid


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from round_classifier.config import load_round_labels
from backend.processor import process_video_all_frames
from backend.tracing import (
    capture_trace_events,
    configure_performance_logging,
    trace_context,
)
from round_classifier.predict import get_ocr_classifier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument(
        "--box", type=float, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"), required=True
    )
    parser.add_argument("--batch-sizes", type=int, nargs="+", default=[64, 256])
    parser.add_argument("--frame-stride", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("round_pipeline_benchmark.jsonl"))
    parser.add_argument("--trace-output", type=Path, default=Path("round_pipeline_trace.jsonl"))
    parser.add_argument(
        "--no-detailed-profiling",
        action="store_true",
        help="Disable synchronized CUDA/ONNX stage profiling.",
    )
    args = parser.parse_args()
    if args.frame_stride < 1 or args.warmups < 0 or args.runs < 1:
        parser.error("frame stride and runs must be positive; warmups cannot be negative")
    if any(size < 1 for size in args.batch_sizes):
        parser.error("batch sizes must be positive")
    x, y, width, height = args.box
    if min(x, y, width, height) < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        parser.error("box must be normalized, non-empty, and contained inside the frame")
    return args


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as destination:
        destination.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def _git_metadata() -> dict[str, Any]:
    def run(*command: str) -> str:
        completed = subprocess.run(
            command, cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False
        )
        return completed.stdout.strip()

    return {
        "git_commit": run("git", "rev-parse", "HEAD") or None,
        "git_dirty": bool(run("git", "status", "--porcelain")),
    }


def _event_sum(events: list[dict[str, Any]], event: str, field: str) -> float:
    total = 0.0
    for payload in events:
        if payload.get("event") == event and payload.get(field) is not None:
            total += float(payload[field])
    return round(total, 4)


def _component_event_sum(
    events: list[dict[str, Any]], event: str, component: str, field: str
) -> float:
    return round(sum(
        float(payload[field])
        for payload in events
        if payload.get("event") == event
        and payload.get("component") == component
        and payload.get(field) is not None
    ), 4)


def _last_event(events: list[dict[str, Any]], event: str) -> dict[str, Any]:
    return next((payload for payload in reversed(events) if payload.get("event") == event), {})


def _stage_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    crop = _last_event(events, "frame_crop_summary")
    decode = _last_event(events, "video_decode_summary")
    return {
        "container_open_ms": float(decode.get("container_open_ms", 0.0)),
        "decode_wait_ms": float(decode.get("decode_wait_ms", 0.0)),
        "native_crop_ms": float(crop.get("native_crop_ms", 0.0)),
        "full_rgb_ms": float(crop.get("full_rgb_ms", 0.0)),
        "yolo_total_ms": _event_sum(events, "text_detection_batch", "detection_ms"),
        "yolo_cpu_preprocess_ms": _event_sum(events, "text_detection_stage_profile", "cpu_preprocess_ms"),
        "yolo_h2d_ms": _event_sum(events, "text_detection_stage_profile", "h2d_wall_ms"),
        "yolo_forward_ms": _event_sum(events, "text_detection_stage_profile", "forward_wall_ms"),
        "yolo_postprocess_ms": _event_sum(events, "text_detection_stage_profile", "postprocess_wall_ms"),
        "detector_d2h_ms": _event_sum(events, "detector_transfer_stage", "wall_ms"),
        "detector_extract_ms": _event_sum(events, "text_detection_extract_batch", "extraction_ms"),
        "ocr_total_ms": _event_sum(events, "ocr_recognition_batch", "recognition_ms"),
        "ocr_preprocess_ms": _event_sum(events, "ocr_stage_profile", "preprocess_wall_ms"),
        "ocr_h2d_ms": _event_sum(events, "ocr_stage_profile", "h2d_wall_ms"),
        "ocr_forward_ms": _event_sum(events, "ocr_stage_profile", "forward_wall_ms"),
        "ocr_d2h_ms": _event_sum(events, "ocr_stage_profile", "d2h_wall_ms"),
        "ocr_postprocess_ms": _event_sum(events, "ocr_stage_profile", "postprocess_wall_ms"),
        "text_detector_load_ms": _component_event_sum(
            events, "model_initialized", "text_detector", "initialization_ms"
        ),
        "ocr_model_load_ms": _component_event_sum(
            events, "model_initialized", "ocr_recognizer", "initialization_ms"
        ),
        "text_detector_first_batch_ms": _component_event_sum(
            events, "model_first_batch", "text_detector", "first_batch_ms"
        ),
        "ocr_first_batch_ms": _component_event_sum(
            events, "model_first_batch", "ocr_recognizer", "first_batch_ms"
        ),
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


def _probe_video(path: Path) -> tuple[int, int, int]:
    import av

    container = av.open(str(path))
    try:
        stream = container.streams.video[0]
        return int(stream.codec_context.width), int(stream.codec_context.height), int(stream.frames or 0)
    finally:
        container.close()


def main() -> int:
    args = parse_args()
    video = args.video.resolve()
    if not video.is_file():
        raise FileNotFoundError(video)
    if not args.no_detailed_profiling:
        os.environ["VOD_DETAILED_PROFILING"] = "1"
    configure_performance_logging(args.trace_output)
    width, height, source_frames = _probe_video(video)
    box = dict(zip(("x", "y", "width", "height"), args.box, strict=True))
    labels = load_round_labels()
    classifier = get_ocr_classifier(labels)
    benchmark_id = uuid.uuid4().hex
    common = {
        "benchmark_id": benchmark_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "video": str(video),
        "video_bytes": video.stat().st_size,
        "source_frames": source_frames,
        "frame_stride": args.frame_stride,
        "box": box,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "detailed_profiling": not args.no_detailed_profiling,
        **_git_metadata(),
    }
    records: list[dict[str, Any]] = []
    for batch_size in args.batch_sizes:
        for iteration in range(args.warmups + args.runs):
            warmup = iteration < args.warmups
            run_number = iteration + 1 if warmup else iteration - args.warmups + 1
            run_id = uuid.uuid4().hex
            transitions: list[Any] = []
            with trace_context(
                benchmark_id=benchmark_id,
                run_id=run_id,
                benchmark_warmup=warmup,
            ), capture_trace_events() as events:
                started = time.perf_counter()
                processed, device = process_video_all_frames(
                    video,
                    width,
                    height,
                    box,
                    batch_size,
                    lambda batch, *_args: transitions.extend(batch),
                    lambda *_args: None,
                    classifier,
                    frame_stride=args.frame_stride,
                    collect_benchmark_digests=True,
                )
                elapsed = time.perf_counter() - started
            transition_digest = hashlib.sha256(
                json.dumps(transitions, sort_keys=True).encode("utf-8")
            ).hexdigest()
            decode_event = _last_event(events, "video_decode_summary")
            record = {
                "record_type": "benchmark_run",
                **common,
                "run_id": run_id,
                "warmup": warmup,
                "run_number": run_number,
                "batch_size": batch_size,
                "processed_frames": processed,
                "batches": math.ceil(processed / batch_size),
                "device": device,
                "elapsed_seconds": round(elapsed, 6),
                "frames_per_second": round(processed / elapsed, 4),
                "transitions": len(transitions),
                "transition_digest": transition_digest,
                "crop_digest": decode_event.get("crop_digest"),
                "prediction_digest": decode_event.get("prediction_digest"),
                "stages": _stage_summary(events),
            }
            records.append(record)
            _append_jsonl(args.output, record)
            print(json.dumps(record, sort_keys=True))

    for batch_size in args.batch_sizes:
        measured = [
            record for record in records
            if record["batch_size"] == batch_size and not record["warmup"]
        ]
        durations = sorted(float(record["elapsed_seconds"]) for record in measured)
        prediction_digests = {record["prediction_digest"] for record in measured}
        crop_digests = {record["crop_digest"] for record in measured}
        all_measured = [record for record in records if not record["warmup"]]
        stage_names = measured[0]["stages"].keys()
        summary = {
            "record_type": "benchmark_summary",
            **common,
            "batch_size": batch_size,
            "runs": len(measured),
            "median_seconds": round(statistics.median(durations), 6),
            "p95_seconds": round(_percentile(durations, 0.95), 6),
            "median_frames_per_second": round(
                statistics.median(record["frames_per_second"] for record in measured), 4
            ),
            "p95_frames_per_second": round(
                _percentile([record["frames_per_second"] for record in measured], 0.95), 4
            ),
            "stage_medians_ms": {
                name: round(statistics.median(record["stages"][name] for record in measured), 4)
                for name in stage_names
            },
            "stage_p95_ms": {
                name: round(
                    _percentile([record["stages"][name] for record in measured], 0.95), 4
                )
                for name in stage_names
            },
            "predictions_consistent": len(prediction_digests) == 1,
            "crops_consistent": len(crop_digests) == 1,
            "predictions_consistent_across_batch_sizes": len({
                record["prediction_digest"] for record in all_measured
            }) == 1,
            "crops_consistent_across_batch_sizes": len({
                record["crop_digest"] for record in all_measured
            }) == 1,
        }
        _append_jsonl(args.output, summary)
        print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
