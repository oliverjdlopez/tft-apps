"""Cancellable metadata discovery over newest-first creator feeds."""

import asyncio
from datetime import datetime
import json
import sys
import tempfile

from .utils import discovery_urls, media_identity, publication_time


async def stop_process(process) -> None:
    """Reap an extractor on cancellation, timeout, or reaching the window boundary."""
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


async def discover_window(source: str, start: datetime, end: datetime) -> tuple[list[dict], list[dict]]:
    """Read complete timestamps without the manual discovery list's 12-entry limit.

    Args:
        source: Validated YouTube channel or Twitch streamer URL.
        start: Inclusive UTC publication boundary.
        end: Inclusive scheduled run instant; later publications belong to another run.

    Returns:
        Eligible videos and explicit metadata/feed errors; successful tabs survive failures.
    """
    found = {}
    errors = []
    for feed in discovery_urls(source):
        with tempfile.TemporaryFile() as stderr:
            process = None
            reached_boundary = False
            try:
                # Flat playlists omit timestamps on YouTube. Full extraction here
                # fetches metadata only, and lazy playlists stop before old media.
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "yt_dlp", "--ignore-config", "--lazy-playlist",
                    "--no-flat-playlist", "--skip-download", "--dump-json", "--ignore-errors",
                    "--quiet", "--no-warnings", "--socket-timeout", "30", "--retries", "2",
                    "--extractor-retries", "2", "--", feed,
                    stdout=asyncio.subprocess.PIPE, stderr=stderr, limit=8 * 1024 * 1024,
                )
                while True:
                    line = await asyncio.wait_for(process.stdout.readline(), 90)
                    if not line:
                        break
                    entry = json.loads(line)
                    if entry.get("is_live") or entry.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
                        continue
                    published = publication_time(entry)
                    if published is None:
                        errors.append({"source_url": source, "message": f"Cannot verify publication time for {entry.get('id', 'a video')}; skipped"})
                        continue
                    if published < start:
                        reached_boundary = True
                        break
                    if published > end:
                        continue
                    url = entry.get("webpage_url")
                    identifier = media_identity(url or "")
                    if not identifier:
                        errors.append({"source_url": source, "message": "A discovered video has no supported video URL; skipped"})
                        continue
                    found[identifier] = {"id": identifier, "title": str(entry.get("title") or "Untitled replay"),
                                         "url": url, "source_url": source, "published_at": published.isoformat()}
                if reached_boundary:
                    await stop_process(process)
                else:
                    await asyncio.wait_for(process.wait(), 10)
                    stderr.seek(0)
                    detail = stderr.read(16000).decode("utf-8", errors="replace").strip()
                    # Channels may have no shorts or streams tab. That is an empty feed.
                    missing_tab = "does not have a" in detail.lower() and "tab" in detail.lower()
                    if not missing_tab and (process.returncode or detail):
                        errors.append({"source_url": source, "message": detail[-500:] or "Creator feed extraction failed"})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                errors.append({"source_url": source, "message": str(exc)[:500] or "Creator feed timed out"})
            finally:
                if process is not None:
                    await stop_process(process)
    return list(found.values()), errors
