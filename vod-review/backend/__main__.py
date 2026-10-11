"""Command-line launcher for the VOD Review backend."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the VOD Review backend server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--save-frames",
        action="store_true",
        help="Save every sampled frame to frames/<video UUID>/",
    )
    parser.add_argument(
        "--save-boxes",
        action="store_true",
        help="Save each sampled bounding-box crop to boxes/<video UUID>/",
    )
    parser.add_argument(
        "--trace-jsonl",
        type=Path,
        help="Append structured performance events to this JSONL file.",
    )
    parser.add_argument(
        "--detailed-profiling",
        action="store_true",
        help="Enable synchronized CUDA-event and ONNX transfer profiling.",
    )
    args = parser.parse_args()
    return args


def main() -> None:
    args = parse_args()
    if args.save_frames:
        os.environ["VOD_SAVE_FRAMES"] = "1"
    if args.save_boxes:
        os.environ["VOD_SAVE_BOXES"] = "1"
    if args.trace_jsonl:
        os.environ["VOD_TRACE_JSONL"] = str(args.trace_jsonl)
    if args.detailed_profiling:
        os.environ["VOD_DETAILED_PROFILING"] = "1"
    import uvicorn

    uvicorn.run("backend.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
