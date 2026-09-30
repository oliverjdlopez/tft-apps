"""Transcribe downloaded VOD files with faster-whisper on CUDA."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.serialization import read_json_lines, write_json_lines

DEFAULT_TRANSCRIPT_OUTPUT_DIR = Path("scripts/transcription/output")


@dataclass(frozen=True)
class TranscriptionConfig:
    """Configuration for faster-whisper transcription."""

    video_path: Path
    output_dir: Path = DEFAULT_TRANSCRIPT_OUTPUT_DIR
    model_size: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str | None = None
    beam_size: int = 5
    vad_filter: bool = True
    word_timestamps: bool = False
    resume: bool = True


@dataclass(frozen=True)
class TranscriptionResult:
    """Transcription artifact paths."""

    text_path: Path
    json_path: Path
    srt_path: Path
    segments_path: Path


def _segment_to_dict(segment: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": segment.id,
        "start": segment.start,
        "end": segment.end,
        "text": segment.text,
    }
    if getattr(segment, "words", None):
        payload["words"] = [
            {"start": word.start, "end": word.end, "word": word.word, "probability": word.probability}
            for word in segment.words
        ]
    return payload


def _read_checkpointed_segments(path: Path) -> list[dict[str, Any]]:
    return read_json_lines(path)


def _format_srt_timestamp(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _write_outputs(
    *,
    text_path: Path,
    json_path: Path,
    srt_path: Path,
    video_path: Path,
    model_size: str,
    segments: list[dict[str, Any]],
    info: Any,
) -> None:
    text_path.write_text("".join(segment["text"] for segment in segments).strip() + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "video_path": str(video_path),
                "model_size": model_size,
                "language": getattr(info, "language", None),
                "language_probability": getattr(info, "language_probability", None),
                "duration": getattr(info, "duration", None),
                "segments": segments,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    srt_blocks = []
    for index, segment in enumerate(segments, start=1):
        srt_blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_format_srt_timestamp(segment['start'])} --> {_format_srt_timestamp(segment['end'])}",
                    segment["text"].strip(),
                ]
            )
        )
    srt_path.write_text("\n\n".join(srt_blocks) + "\n", encoding="utf-8")


def transcribe_vod(config: TranscriptionConfig) -> TranscriptionResult:
    """Transcribe a local VOD with faster-whisper using the configured GPU device.

    Segment JSONL is written incrementally as a checkpoint. If a run fails after
    some segments are emitted, rerun with ``resume=True`` to continue from the
    last completed segment timestamp instead of discarding prior text.
    """

    from faster_whisper import WhisperModel

    video_path = Path(config.video_path).expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"VOD file does not exist: {video_path}")

    output_dir = Path(config.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = video_path.stem
    text_path = output_dir / f"{stem}.txt"
    json_path = output_dir / f"{stem}.json"
    srt_path = output_dir / f"{stem}.srt"
    segments_path = output_dir / f"{stem}.segments.jsonl"

    checkpointed_segments = _read_checkpointed_segments(segments_path) if config.resume else []
    clip_start = checkpointed_segments[-1]["end"] if checkpointed_segments else 0

    model = WhisperModel(
        config.model_size,
        device=config.device,
        compute_type=config.compute_type,
    )
    segments_iter, info = model.transcribe(
        str(video_path),
        language=config.language,
        beam_size=config.beam_size,
        vad_filter=config.vad_filter,
        word_timestamps=config.word_timestamps,
        clip_timestamps=f"{clip_start}",
    )

    new_segments: list[dict[str, Any]] = []
    for segment in segments_iter:
        row = _segment_to_dict(segment)
        if row["end"] <= clip_start:
            continue
        write_json_lines(
            segments_path,
            [row],
            append=bool(checkpointed_segments or new_segments),
            flush=True,
            sort_keys=True,
        )
        new_segments.append(row)

    all_segments = checkpointed_segments + new_segments
    _write_outputs(
        text_path=text_path,
        json_path=json_path,
        srt_path=srt_path,
        video_path=video_path,
        model_size=config.model_size,
        segments=all_segments,
        info=info,
    )
    return TranscriptionResult(
        text_path=text_path,
        json_path=json_path,
        srt_path=srt_path,
        segments_path=segments_path,
    )
