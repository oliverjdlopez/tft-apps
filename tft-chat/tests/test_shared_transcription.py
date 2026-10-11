"""Verify the public transcription adapter with offline producer substitutes."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.transcription.download_vod import DownloadConfig, DownloadResult, download_vod
from scripts.transcription.media_store import MediaStore
from scripts.transcription.media_store.models import MediaRequest


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires ffmpeg and ffprobe")
class TranscriptionSharedTest(unittest.TestCase):
    """Exercise opt-in routing, legacy fallback and range-isolated work paths."""

    def setUp(self):
        """Create temporary audio and shared storage without network access."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "source.m4a"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=2", "-c:a", "aac", str(self.audio)], check=True)

    def test_shared_hit_avoids_legacy_downloader(self):
        """A catalog hit goes straight to the existing transcriber's local path."""
        store = MediaStore(self.root / "shared")
        existing = store.obtain(MediaRequest("https://youtu.be/abc"), lambda: self.audio)
        with patch.dict(os.environ, {"TFT_MEDIA_DIR": str(store.root)}), patch("scripts.transcription.download_vod.download_vod_local") as download:
            result = download_vod(DownloadConfig("https://youtube.com/watch?v=abc"))
        download.assert_not_called()
        self.assertEqual(result.media_path, existing)
        self.assertTrue(result.progress_path.is_file())
        self.assertTrue(result.info_json_path.is_file())
        self.assertEqual(result.archive_path.name, "catalog.sqlite3")

    def test_unconfigured_keeps_existing_behavior(self):
        """Existing installations need no catalog or additional media probing."""
        config = DownloadConfig("https://youtu.be/abc")
        with patch.dict(os.environ, {"TFT_MEDIA_DIR": ""}), patch("scripts.transcription.download_vod.download_vod_local") as download:
            self.assertIs(download_vod(config), download.return_value)
        download.assert_called_once_with(config)

    def test_bounded_and_full_downloads_do_not_share_archives(self):
        """A short download cannot poison the archive for a subsequent full VOD."""
        outputs = []

        def produce(config):
            """Stand in for yt-dlp while preserving its work-directory contract."""
            outputs.append(config.output_dir)
            config.output_dir.mkdir(parents=True, exist_ok=True)
            path = config.output_dir / "audio.m4a"
            shutil.copyfile(self.audio, path)
            return DownloadResult(path, path.with_suffix(".info.json"), path.with_suffix(".progress.json"), path.with_suffix(".archive"), "youtube")

        with patch.dict(os.environ, {"TFT_MEDIA_DIR": str(self.root / "shared")}), patch("scripts.transcription.download_vod.download_vod_local", side_effect=produce):
            short = download_vod(DownloadConfig("https://youtu.be/abc", max_time=1 / 60))
            full = download_vod(DownloadConfig("https://youtu.be/abc"))
        self.assertEqual(len(outputs), 2)
        self.assertNotEqual(outputs[0], outputs[1])
        self.assertNotEqual(short.media_path, full.media_path)
        self.assertTrue(full.media_path.exists())


if __name__ == "__main__":
    unittest.main()
