"""Command-line entry point for media download and transcription."""

from __future__ import annotations

import argparse
import configparser
import logging
import time
from pathlib import Path
from typing import Any

from scripts.transcription.download_vod import (
    AUDIO_FORMAT_SELECTOR,
    DEFAULT_DATA_DIR,
    VIDEO_FORMAT_SELECTOR,
    DownloadConfig,
    download_vod,
)
from scripts.transcription.transcribe import (
    DEFAULT_TRANSCRIPT_OUTPUT_DIR,
    TranscriptionConfig,
    transcribe_vod,
)

CONFIG_SECTION = "transcribe"
PROJECT_CONFIG_PATH = Path("chat_tft.ini")


def _normalize_config_key(key: str) -> str:
    """Normalize config keys to match argparse destination names."""
    return key.strip().replace("-", "_")


def load_transcribe_config(path: Path = PROJECT_CONFIG_PATH) -> dict[str, Any]:
    """Return discovered [transcribe] settings from the project config file.

    Every key in the section is loaded automatically. The ``urls`` key is the
    only special case because it represents a list of inputs rather than a
    normal scalar option.
    """
    resolved = path.expanduser()
    if not resolved.exists():
        return {}

    parsed = configparser.ConfigParser()
    parsed.read(resolved)

    if not parsed.has_section(CONFIG_SECTION):
        return {}

    config: dict[str, Any] = {}
    for raw_key, raw_value in parsed.items(CONFIG_SECTION):
        key = _normalize_config_key(raw_key)

        if key == "urls":
            urls = [u.strip() for u in raw_value.splitlines() if u.strip()]
            if urls:
                config["urls"] = urls
            continue

        config[key] = raw_value.strip()

    return config


def _add_download_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "url",
        nargs="?",
        default=argparse.SUPPRESS,
        help=(
            "Twitch VOD or YouTube URL, for example "
            "https://www.twitch.tv/videos/123 or https://www.youtube.com/watch?v=abc123. "
            "May be omitted when urls are listed in the [transcribe] config section."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"Directory for downloaded media and checkpoints. Defaults to {DEFAULT_DATA_DIR}.",
    )
    parser.add_argument(
        "--format",
        dest="format_selector",
        default=argparse.SUPPRESS,
        help=f"yt-dlp format selector. Defaults to audio-only: {AUDIO_FORMAT_SELECTOR}",
    )
    parser.add_argument(
        "--video",
        action="store_true",
        default=argparse.SUPPRESS,
        help=f"Download the full video instead of audio only. Uses {VIDEO_FORMAT_SELECTOR} unless --format is set.",
    )
    parser.add_argument(
        "--merge-output-format",
        default=argparse.SUPPRESS,
        help="Container for merged video+audio downloads. Defaults to mp4 in --video mode.",
    )
    parser.add_argument("--concurrent-fragments", type=int, default=argparse.SUPPRESS)
    parser.add_argument(
        "--ffmpeg-location",
        default=argparse.SUPPRESS,
        help="Path to an ffmpeg executable or directory. Defaults to system ffmpeg, then imageio-ffmpeg.",
    )
    parser.add_argument(
        "--max-time",
        type=float,
        default=argparse.SUPPRESS,
        help="Maximum download duration in minutes, starting from the beginning of the media",
    )
    parser.add_argument(
        "--quiet-download",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Reduce noisy third-party logging during the download stage",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Ignore the download archive and replace existing media/output files.",
    )


def _add_transcription_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model-size", default=argparse.SUPPRESS)
    parser.add_argument("--device", default=argparse.SUPPRESS)
    parser.add_argument("--compute-type", default=argparse.SUPPRESS)
    parser.add_argument("--language", default=argparse.SUPPRESS)
    parser.add_argument("--beam-size", type=int, default=argparse.SUPPRESS)
    parser.add_argument(
        "--no-vad",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable faster-whisper VAD filtering",
    )
    parser.add_argument("--word-timestamps", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument(
        "--no-resume",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Ignore existing transcription segment checkpoints",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download and transcribe Twitch VODs or YouTube videos.")
    subparsers = parser.add_subparsers(dest="command")

    download_parser = subparsers.add_parser("download", help="Download supported media only")
    _add_download_options(download_parser)

    transcribe_parser = subparsers.add_parser("transcribe", help="Transcribe a local media file only")
    transcribe_parser.add_argument(
        "video_path",
        nargs="?",
        type=Path,
        default=argparse.SUPPRESS,
    )
    transcribe_parser.add_argument(
        "--output-dir",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"Directory for transcript outputs. Defaults to {DEFAULT_TRANSCRIPT_OUTPUT_DIR}.",
    )
    _add_transcription_options(transcribe_parser)

    all_parser = subparsers.add_parser("all", help="Download supported media and then transcribe it")
    _add_download_options(all_parser)
    all_parser.add_argument(
        "--transcript-output-dir",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"Directory for transcript outputs. Defaults to {DEFAULT_TRANSCRIPT_OUTPUT_DIR}.",
    )
    _add_transcription_options(all_parser)

    return parser


def _iter_parser_actions(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    """Return actions from the root parser and all subparsers."""
    actions: list[argparse.Action] = []

    for action in parser._actions:
        actions.append(action)

        if isinstance(action, argparse._SubParsersAction):
            for subparser in action.choices.values():
                actions.extend(_iter_parser_actions(subparser))

    return actions


def _build_config_action_map(parser: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    """Map config keys and CLI option names to argparse actions."""
    action_map: dict[str, argparse.Action] = {}

    for action in _iter_parser_actions(parser):
        if not action.dest or action.dest == argparse.SUPPRESS:
            continue

        action_map[_normalize_config_key(action.dest)] = action

        for option in action.option_strings:
            key = option.lstrip("-")
            if key:
                action_map[_normalize_config_key(key)] = action

    return action_map


def _coerce_config_value(value: Any, action: argparse.Action | None) -> Any:
    """Coerce config strings using argparse metadata where available."""
    if action is None or not isinstance(value, str):
        return value

    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        return configparser.ConfigParser.BOOLEAN_STATES[value.lower()]

    if action.type is not None:
        return action.type(value)

    return value


def _load_cli_aware_config(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Load config and coerce values based on discovered parser options."""
    raw_config = load_transcribe_config()
    action_map = _build_config_action_map(parser)

    config: dict[str, Any] = {}
    for raw_key, raw_value in raw_config.items():
        key = _normalize_config_key(raw_key)

        if key == "urls":
            config[key] = raw_value
            continue

        action = action_map.get(key)
        dest = action.dest if action is not None else key
        config[dest] = _coerce_config_value(raw_value, action)

    return config


def _merge_config_into_args(args: argparse.Namespace, config: dict[str, Any]) -> None:
    """Apply config defaults without replacing values explicitly passed on the CLI."""
    for key, value in config.items():
        if key == "urls":
            continue
        if not hasattr(args, key):
            setattr(args, key, value)


def _apply_runtime_defaults(args: argparse.Namespace) -> None:
    """Fill in application defaults after CLI/config precedence is resolved."""
    defaults = {
        "output_dir": DEFAULT_DATA_DIR,
        "format_selector": None,
        "video": False,
        "merge_output_format": None,
        "concurrent_fragments": 4,
        "ffmpeg_location": None,
        "max_time": None,
        "quiet_download": False,
        "overwrite": False,
        "transcript_output_dir": DEFAULT_TRANSCRIPT_OUTPUT_DIR,
        "model_size": "large-v3",
        "device": "cuda",
        "compute_type": "float16",
        "language": None,
        "beam_size": 5,
        "no_vad": False,
        "word_timestamps": False,
        "no_resume": False,
    }

    for key, value in defaults.items():
        if not hasattr(args, key):
            setattr(args, key, value)


def run_download(args: argparse.Namespace, url: str | None = None):
    _apply_runtime_defaults(args)
    media_type = "video" if args.video else "audio"
    format_selector = args.format_selector or (
        VIDEO_FORMAT_SELECTOR if args.video else AUDIO_FORMAT_SELECTOR
    )
    merge_output_format = args.merge_output_format
    if args.video and merge_output_format is None:
        merge_output_format = "mp4"

    return download_vod(
        DownloadConfig(
            url=url or args.url,
            output_dir=args.output_dir,
            format_selector=format_selector,
            media_type=media_type,
            merge_output_format=merge_output_format,
            concurrent_fragments=args.concurrent_fragments,
            max_time=args.max_time,
            ffmpeg_location=args.ffmpeg_location,
            overwrite=args.overwrite,
        )
    )


def run_transcribe(args: argparse.Namespace, video_path: Path | None = None):
    explicit_output_dir = hasattr(args, "output_dir")
    _apply_runtime_defaults(args)
    output_dir = (
        getattr(args, "transcript_output_dir", DEFAULT_TRANSCRIPT_OUTPUT_DIR)
        if video_path is not None
        else (args.output_dir if explicit_output_dir else DEFAULT_TRANSCRIPT_OUTPUT_DIR)
    )
    return transcribe_vod(
        TranscriptionConfig(
            video_path=video_path or args.video_path,
            output_dir=output_dir,
            model_size=args.model_size,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
            beam_size=args.beam_size,
            vad_filter=not args.no_vad,
            word_timestamps=args.word_timestamps,
            resume=not args.no_resume,
        )
    )


def _resolve_urls(args: argparse.Namespace, config: dict[str, Any]) -> list[str]:
    """Return the list of URLs to process, from CLI arg or config file."""
    cli_url = getattr(args, "url", None)
    if cli_url:
        return [cli_url]

    urls = config.get("urls", [])
    if not urls:
        raise SystemExit(
            "No URL provided. Pass a URL as a positional argument or list urls "
            f"under [{CONFIG_SECTION}] in {PROJECT_CONFIG_PATH}."
        )
    return urls


def _suppress_noisy_loggers(quiet: bool) -> dict[str, int | None]:
    prev_levels: dict[str, int | None] = {}
    if quiet:
        for name in ["yt_dlp", "urllib3", "fsspec", "filelock"]:
            lg = logging.getLogger(name)
            prev_levels[name] = lg.level if lg.level != 0 else None
            lg.setLevel(logging.WARNING)
    return prev_levels


def _restore_loggers(prev_levels: dict[str, int | None]) -> None:
    for name, level in prev_levels.items():
        lg = logging.getLogger(name)
        lg.setLevel(logging.NOTSET if level is None else level)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_parser()
    args = parser.parse_args()

    config = _load_cli_aware_config(parser)
    _merge_config_into_args(args, config)
    _apply_runtime_defaults(args)

    overall_start = time.perf_counter()

    if args.command == "transcribe":
        if not hasattr(args, "video_path"):
            raise SystemExit(
                "No media path provided. Pass video_path as a positional argument "
                f"or set video_path under [{CONFIG_SECTION}] in {PROJECT_CONFIG_PATH}."
            )

        start = time.perf_counter()
        result = run_transcribe(args)
        elapsed = time.perf_counter() - start
        print(f"Transcript: {result.text_path}")
        print(f"Segments checkpoint: {result.segments_path}")
        logging.info("Timing summary:")
        logging.info(f"  total: {elapsed:.3f}s")
        logging.info(f"  transcribe: {elapsed:.3f}s")
        return

    if args.command not in ("download", "all"):
        parser.print_help()
        raise SystemExit(2)

    urls = _resolve_urls(args, config)
    quiet = getattr(args, "quiet_download", False)

    for i, url in enumerate(urls):
        if len(urls) > 1:
            logging.info("--- [%d/%d] %s ---", i + 1, len(urls), url)

        timings: dict[str, float] = {}

        if args.command == "download":
            prev_levels = _suppress_noisy_loggers(quiet)
            start = time.perf_counter()
            try:
                result = run_download(args, url=url)
            finally:
                _restore_loggers(prev_levels)
            timings["download"] = time.perf_counter() - start
            print(f"Downloaded media: {result.media_path}")

        elif args.command == "all":
            prev_levels = _suppress_noisy_loggers(quiet)
            start = time.perf_counter()
            try:
                download_result = run_download(args, url=url)
            finally:
                _restore_loggers(prev_levels)
            timings["download"] = time.perf_counter() - start

            start = time.perf_counter()
            transcription_result = run_transcribe(args, video_path=download_result.media_path)
            timings["transcribe"] = time.perf_counter() - start

            print(f"Downloaded media: {download_result.media_path}")
            print(f"Transcript: {transcription_result.text_path}")
            print(f"Segments checkpoint: {transcription_result.segments_path}")

        logging.info("Timing summary:")
        for key, value in timings.items():
            logging.info(f"  {key}: {value:.3f}s")

    total = time.perf_counter() - overall_start
    if len(urls) > 1:
        logging.info("Total time for %d URLs: %.3fs", len(urls), total)


if __name__ == "__main__":
    main()
