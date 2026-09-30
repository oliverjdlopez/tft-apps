from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.transcription.download_vod import (
    AUDIO_FORMAT_SELECTOR,
    VIDEO_FORMAT_SELECTOR,
    DownloadConfig,
    FfmpegLocation,
    _atomic_write_json,
    _download_archive_filename,
    _media_id_from_url,
    _resolve_ffmpeg_location,
    detect_download_source,
    download_vod,
)
from scripts.transcription.main import build_parser, run_download, run_transcribe


class ResolveFfmpegLocationTest(unittest.TestCase):
    def test_explicit_ffmpeg_location_wins(self) -> None:
        self.assertEqual(
            _resolve_ffmpeg_location("/custom/ffmpeg"),
            FfmpegLocation(path="/custom/ffmpeg", source="explicit"),
        )

    @patch("scripts.transcription.download_vod._bundled_ffmpeg_path", return_value="/bundle/ffmpeg")
    @patch("scripts.transcription.download_vod.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_system_ffmpeg_preferred_over_bundled(self, _which, _bundled) -> None:
        self.assertEqual(
            _resolve_ffmpeg_location(),
            FfmpegLocation(path="/usr/bin/ffmpeg", source="system"),
        )

    @patch("scripts.transcription.download_vod._bundled_ffmpeg_path", return_value="/bundle/ffmpeg")
    @patch("scripts.transcription.download_vod.shutil.which", return_value=None)
    def test_bundled_ffmpeg_fallback(self, _which, _bundled) -> None:
        self.assertEqual(
            _resolve_ffmpeg_location(),
            FfmpegLocation(path="/bundle/ffmpeg", source="imageio-ffmpeg"),
        )


class CliTest(unittest.TestCase):
    def test_download_source_detection_accepts_twitch_and_youtube(self) -> None:
        self.assertEqual(
            detect_download_source("https://www.twitch.tv/videos/1234567890"),
            "twitch",
        )
        self.assertEqual(
            detect_download_source("https://www.youtube.com/watch?v=abc123"),
            "youtube",
        )
        self.assertEqual(detect_download_source("https://youtu.be/abc123"), "youtube")

    def test_download_source_detection_rejects_unsupported_hosts(self) -> None:
        with self.assertRaises(ValueError):
            detect_download_source("https://example.com/watch?v=abc123")

    def test_media_id_extraction_handles_youtube_and_twitch_urls(self) -> None:
        self.assertEqual(
            _media_id_from_url("https://www.youtube.com/watch?v=VBT6TUrGYzo", "youtube"),
            "VBT6TUrGYzo",
        )
        self.assertEqual(_media_id_from_url("https://youtu.be/VBT6TUrGYzo", "youtube"), "VBT6TUrGYzo")
        self.assertEqual(
            _media_id_from_url("https://www.youtube.com/shorts/VBT6TUrGYzo", "youtube"),
            "VBT6TUrGYzo",
        )
        self.assertEqual(
            _media_id_from_url("https://www.twitch.tv/videos/1234567890", "twitch"),
            "1234567890",
        )

    def test_audio_download_uses_separate_archive_from_legacy_video_downloads(self) -> None:
        self.assertEqual(_download_archive_filename("audio"), "download-audio-archive.txt")
        self.assertEqual(_download_archive_filename("video"), "download-archive.txt")

    def test_download_accepts_ffmpeg_location(self) -> None:
        args = build_parser().parse_args(
            [
                "download",
                "https://www.twitch.tv/videos/1234567890",
                "--ffmpeg-location",
                "/usr/bin/ffmpeg",
            ]
        )

        self.assertEqual(args.ffmpeg_location, "/usr/bin/ffmpeg")

    @patch("scripts.transcription.main.download_vod")
    def test_download_defaults_to_root_data_directory(self, download_vod_mock) -> None:
        args = build_parser().parse_args(
            [
                "download",
                "https://www.twitch.tv/videos/1234567890",
            ]
        )

        run_download(args)

        config = download_vod_mock.call_args.args[0]
        self.assertEqual(config.output_dir, Path("data"))

    @patch("scripts.transcription.main.download_vod")
    def test_download_accepts_youtube_url(self, download_vod_mock) -> None:
        args = build_parser().parse_args(
            [
                "download",
                "https://www.youtube.com/watch?v=abc123",
            ]
        )

        run_download(args)

        config = download_vod_mock.call_args.args[0]
        self.assertEqual(config.url, "https://www.youtube.com/watch?v=abc123")

    @patch("scripts.transcription.main.download_vod")
    def test_download_defaults_to_audio_only(self, download_vod_mock) -> None:
        args = build_parser().parse_args(
            [
                "download",
                "https://www.twitch.tv/videos/1234567890",
            ]
        )

        run_download(args)

        config = download_vod_mock.call_args.args[0]
        self.assertEqual(config.media_type, "audio")
        self.assertEqual(config.format_selector, AUDIO_FORMAT_SELECTOR)
        self.assertIsNone(config.merge_output_format)

    @patch("scripts.transcription.main.download_vod")
    def test_download_video_mode_keeps_old_video_defaults(self, download_vod_mock) -> None:
        args = build_parser().parse_args(
            [
                "download",
                "https://www.twitch.tv/videos/1234567890",
                "--video",
            ]
        )

        run_download(args)

        config = download_vod_mock.call_args.args[0]
        self.assertEqual(config.media_type, "video")
        self.assertEqual(config.format_selector, VIDEO_FORMAT_SELECTOR)
        self.assertEqual(config.merge_output_format, "mp4")

    @patch("scripts.transcription.main.download_vod")
    def test_custom_format_overrides_audio_default(self, download_vod_mock) -> None:
        args = build_parser().parse_args(
            [
                "download",
                "https://www.twitch.tv/videos/1234567890",
                "--format",
                "best[height<=480]/best",
            ]
        )

        run_download(args)

        config = download_vod_mock.call_args.args[0]
        self.assertEqual(config.media_type, "audio")
        self.assertEqual(config.format_selector, "best[height<=480]/best")

    @patch("scripts.transcription.main.transcribe_vod")
    def test_transcribe_defaults_to_scripts_transcription_output(self, transcribe_vod_mock) -> None:
        args = build_parser().parse_args(
            [
                "transcribe",
                "data/audio/TwitchVod-v1234567890.mp4",
            ]
        )

        run_transcribe(args)

        config = transcribe_vod_mock.call_args.args[0]
        self.assertEqual(config.output_dir, Path("scripts/transcription/output"))

    @patch("scripts.transcription.main.transcribe_vod")
    def test_all_uses_transcript_output_dir_separate_from_download_dir(self, transcribe_vod_mock) -> None:
        args = build_parser().parse_args(
            [
                "all",
                "https://www.twitch.tv/videos/1234567890",
                "--output-dir",
                "data",
                "--transcript-output-dir",
                "scripts/transcription/output",
            ]
        )

        run_transcribe(args, video_path=Path("data/audio/TwitchVod-v1234567890.mp4"))

        config = transcribe_vod_mock.call_args.args[0]
        self.assertEqual(config.video_path, Path("data/audio/TwitchVod-v1234567890.mp4"))
        self.assertEqual(config.output_dir, Path("scripts/transcription/output"))

    @patch("scripts.transcription.main.download_vod")
    def test_overwrite_flag_is_disabled_by_default(self, download_vod_mock) -> None:
        args = build_parser().parse_args(
            [
                "download",
                "https://www.twitch.tv/videos/1234567890",
            ]
        )

        run_download(args)

        config = download_vod_mock.call_args.args[0]
        self.assertFalse(config.overwrite)

    @patch("scripts.transcription.main.download_vod")
    def test_overwrite_flag_is_forwarded_to_download_config(self, download_vod_mock) -> None:
        args = build_parser().parse_args(
            [
                "download",
                "https://www.twitch.tv/videos/1234567890",
                "--overwrite",
            ]
        )

        run_download(args)

        config = download_vod_mock.call_args.args[0]
        self.assertTrue(config.overwrite)

    @patch("yt_dlp.YoutubeDL")
    def test_overwrite_ignores_archive_and_forces_replacement(self, youtube_dl_mock) -> None:
        ydl = youtube_dl_mock.return_value.__enter__.return_value
        ydl.extract_info.return_value = {
            "id": "v1234567890",
            "requested_downloads": [
                {"filepath": "/tmp/transcription-test/audio/TwitchVod-v1234567890.mp4"}
            ],
        }
        ydl.prepare_filename.return_value = "/tmp/transcription-test/audio/TwitchVod-v1234567890.mp4"

        with patch("scripts.transcription.download_vod.Path.exists", return_value=True):
            download_vod(
                DownloadConfig(
                    url="https://www.twitch.tv/videos/1234567890",
                    output_dir="/tmp/transcription-test",
                    overwrite=True,
                )
            )

        options = youtube_dl_mock.call_args.args[0]
        self.assertNotIn("download_archive", options)
        self.assertTrue(options["overwrites"])
        self.assertFalse(options["continuedl"])

    @patch("yt_dlp.YoutubeDL")
    def test_youtube_download_is_source_tagged_and_single_video(self, youtube_dl_mock) -> None:
        ydl = youtube_dl_mock.return_value.__enter__.return_value
        ydl.extract_info.return_value = {
            "id": "abc123",
            "requested_downloads": [
                {"filepath": "/tmp/transcription-test/audio/Youtube-abc123.mp4"}
            ],
        }
        ydl.prepare_filename.return_value = "/tmp/transcription-test/audio/Youtube-abc123.mp4"

        with patch("scripts.transcription.download_vod.Path.exists", return_value=True):
            result = download_vod(
                DownloadConfig(
                    url="https://www.youtube.com/watch?v=abc123",
                    output_dir="/tmp/transcription-test",
                )
            )

        options = youtube_dl_mock.call_args.args[0]
        self.assertEqual(result.source, "youtube")
        self.assertTrue(options["noplaylist"])

    @patch("yt_dlp.YoutubeDL")
    def test_archive_skip_uses_existing_media_file(self, youtube_dl_mock) -> None:
        ydl = youtube_dl_mock.return_value.__enter__.return_value
        ydl.extract_info.return_value = None

        existing_media = Path("/tmp/transcription-test/audio/Youtube-VBT6TUrGYzo.webm")

        def fake_exists(path: Path) -> bool:
            return path == existing_media

        def fake_is_file(path: Path) -> bool:
            return path == existing_media

        with (
            patch("scripts.transcription.download_vod.Path.exists", fake_exists),
            patch("scripts.transcription.download_vod.Path.is_file", fake_is_file),
            patch(
                "scripts.transcription.download_vod.Path.stat",
                # st_mode marks a directory so Path.mkdir(exist_ok=True) ->
                # is_dir() is satisfied on Python 3.13+ (its pathlib reads
                # st_mode); st_mtime drives the archive-skip comparison.
                return_value=SimpleNamespace(st_mtime=1, st_mode=0o040755),
            ),
            patch(
                "scripts.transcription.download_vod.Path.glob",
                return_value=[existing_media],
            ),
        ):
            result = download_vod(
                DownloadConfig(
                    url="https://www.youtube.com/watch?v=VBT6TUrGYzo",
                    output_dir="/tmp/transcription-test",
                )
            )

        self.assertEqual(result.media_path, existing_media)
        self.assertEqual(result.source, "youtube")

    @patch("yt_dlp.YoutubeDL")
    def test_archive_skip_without_existing_media_has_clear_error(self, youtube_dl_mock) -> None:
        ydl = youtube_dl_mock.return_value.__enter__.return_value
        ydl.extract_info.return_value = None

        with patch("scripts.transcription.download_vod.Path.glob", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "already recorded in the download archive"):
                download_vod(
                    DownloadConfig(
                        url="https://www.youtube.com/watch?v=VBT6TUrGYzo",
                        output_dir="/tmp/transcription-test",
                    )
                )


class AtomicWriteJsonTest(unittest.TestCase):
    def test_concurrent_writes_do_not_share_temp_path(self) -> None:
        path = Path("/tmp/chat_tft_test_download_progress.json")
        if path.exists():
            path.unlink()

        try:
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(
                    executor.map(
                        lambda index: _atomic_write_json(path, {"index": index}),
                        range(100),
                    )
                )

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("index", payload)
            self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))
        finally:
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    unittest.main()
