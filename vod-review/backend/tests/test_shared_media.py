"""Offline protocol tests, also run by the independently installed VOD repository."""

from __future__ import annotations

import multiprocessing
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.media_store import MediaStore
from backend.media_store.models import MediaRequest
from backend.media_store.utils import probe, source_key


def download_in_process(root, source, log, ready):
    """Exercise process-wide exclusion rather than only in-process locking."""
    store = MediaStore(Path(root))
    ready.wait()

    def produce():
        """Record each actual download attempt for the concurrency assertion."""
        with open(log, "a") as output:
            output.write("download\n")
        return Path(source)

    store.obtain(MediaRequest("https://youtu.be/concurrent", kind="video", profile="video:best"), produce)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires ffmpeg and ffprobe")
class SharedMediaTest(unittest.TestCase):
    """Verify reuse with real tiny media files and separate catalog instances."""

    def setUp(self):
        """Create isolated source video/audio and an empty shared catalog."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.video = self.root / "source.mp4"
        self.audio = self.root / "source.m4a"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=size=64x64:rate=10:duration=3",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(self.video)], check=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(self.video), "-vn", "-c:a", "copy", str(self.audio)], check=True)
        self.store = MediaStore(self.root / "shared")

    def no_download(self):
        """Fail if a cache hit incorrectly calls the remote downloader."""
        self.fail("unexpected download")

    def test_video_reused_as_audio_across_instances_and_url_aliases(self):
        """A VOD supplies transcription audio without a second source transfer."""
        path = self.store.obtain(MediaRequest("https://youtu.be/abc", "video", profile="video:best"), lambda: self.video)
        other = MediaStore(self.store.root)
        reused = other.obtain(MediaRequest("https://www.youtube.com/watch?v=abc&t=10"), self.no_download)
        self.assertEqual(path, reused)
        self.video.unlink()
        self.assertTrue(path.is_file())

    def test_audio_does_not_satisfy_video(self):
        """An audio-first task still downloads the missing video representation."""
        audio = self.store.obtain(MediaRequest("https://youtu.be/abc"), lambda: self.audio)
        video = self.store.obtain(MediaRequest("https://youtu.be/abc", "video", profile="video:best"), lambda: self.video)
        self.assertNotEqual(audio, video)
        self.assertTrue(probe(video)["video"])

    def test_full_video_locally_supplies_range_and_quality(self):
        """A requested clip is cut and scaled locally with its own zero timeline."""
        self.store.obtain(MediaRequest("https://youtu.be/abc", "video", profile="video:best"), lambda: self.video)
        path = self.store.obtain(MediaRequest("https://youtu.be/abc", "video", start=1, end=2,
                                              profile="video:32p", height=32, playable=True), self.no_download)
        metadata = probe(path)
        self.assertEqual(metadata["height"], 32)
        self.assertAlmostEqual(metadata["duration"], 1, delta=0.15)
        self.assertEqual(path, self.store.obtain(MediaRequest("https://youtu.be/abc", "video", start=1, end=2,
                                                             profile="video:32p", height=32, playable=True), self.no_download))

    def test_partial_does_not_satisfy_full_and_low_quality_does_not_satisfy_high(self):
        """Neither insufficient timeline coverage nor resolution is a cache hit."""
        partial = self.store.obtain(MediaRequest("https://youtu.be/abc", "video", end=2, profile="video:64p", height=64), lambda: self.video)
        full = self.store.obtain(MediaRequest("https://youtu.be/abc", "video", profile="video:64p", height=64), lambda: self.video)
        higher = self.store.obtain(MediaRequest("https://youtu.be/abc", "video", profile="video:128p", height=128), lambda: self.video)
        self.assertNotEqual(partial, full)
        self.assertNotEqual(full, higher)

    def test_missing_file_and_failure_are_recoverable(self):
        """Missing bytes cause a new download; failures publish no false hit."""
        request = MediaRequest("https://youtu.be/abc")
        path = self.store.obtain(request, lambda: self.audio)
        path.unlink()
        recovered = self.store.obtain(request, lambda: self.audio)
        self.assertTrue(recovered.is_file())
        with self.assertRaises(ValueError):
            self.store.obtain(MediaRequest("https://youtu.be/bad", "video"), lambda: self.audio)
        recovered = self.store.obtain(MediaRequest("https://youtu.be/bad", "video"), lambda: self.video)
        self.assertTrue(probe(recovered)["video"])

    def test_concurrent_processes_download_once(self):
        """Two workers for the same source share one completed download."""
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        log = self.root / "downloads.log"
        processes = [context.Process(target=download_in_process, args=(str(self.store.root), str(self.video), str(log), ready)) for _ in range(2)]
        for process in processes:
            process.start()
        ready.set()
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join()
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(log.read_text().splitlines(), ["download"])

    def test_refresh_keeps_existing_consumers_file(self):
        """Forced refresh publishes a new immutable asset without deleting old media."""
        request = MediaRequest("https://youtu.be/abc")
        first = self.store.obtain(request, lambda: self.audio)
        second = self.store.obtain(request, lambda: self.audio, refresh=True)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())

    def test_source_identity_and_opt_in(self):
        """Only stable source identities participate and no env means local mode."""
        self.assertEqual(source_key("https://twitch.tv/videos/123"), "twitch:123")
        self.assertEqual(source_key("https://clips.twitch.tv/Abc"), source_key("https://www.twitch.tv/user/clip/Abc"))
        with self.assertRaises(ValueError):
            source_key("https://twitch.tv/channel")
        with patch.dict(os.environ, {"TFT_MEDIA_DIR": ""}):
            self.assertIsNone(MediaStore.from_env())
        with patch.dict(os.environ, {"TFT_MEDIA_DIR": "relative/path"}):
            with self.assertRaises(ValueError):
                MediaStore.from_env()


if __name__ == "__main__":
    unittest.main()
