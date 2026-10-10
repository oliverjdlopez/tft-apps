"""Own scheduled scans, serial downloads, and shutdown within the VOD backend."""

import asyncio
from datetime import datetime, timezone
import logging

try:
    from ..models import VideoUrlRequest
except ImportError:  # Backend-directory uvicorn launch.
    from models import VideoUrlRequest
from . import store
from .models import ReplaySchedule

logger = logging.getLogger(__name__)


class ReplayAutomation:
    """Run one persistent schedule with a single active discovery/download batch."""

    def __init__(self, discover, importer, transcriber=None) -> None:
        """Inject metadata discovery, URL imports, and optional video transcription."""
        self.discover = discover
        self.importer = importer
        self.transcriber = transcriber
        self.task = None
        self.active = None
        self.wake = asyncio.Event()

    async def start(self) -> None:
        """Recover local state and start a poller without enabling the schedule."""
        store.initialize()
        self.task = asyncio.create_task(self.poll(), name="replay-schedule")

    async def stop(self) -> None:
        """Cancel and await owned tasks before the backend stops ordinary downloads."""
        tasks = [task for task in (self.task, self.active) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.task = self.active = None

    def launch(self, run: dict) -> None:
        """Execute a transactionally claimed run in the background."""
        self.active = asyncio.create_task(self.execute(run), name=f"creator-import-{run['id']}")

    def run_now(self, now: datetime | None = None) -> dict:
        """Claim an explicit run even when the daily schedule is disabled."""
        run = store.claim_run(now or datetime.now(timezone.utc), manual=True)
        self.launch(run)
        return run

    async def poll(self) -> None:
        """Check due times every fifteen seconds and immediately after settings change."""
        while True:
            self.wake.clear()
            try:
                run = store.claim_run(datetime.now(timezone.utc))
                if run:
                    self.launch(run)
            except Exception:
                # A transient SQLite failure must not silently disable future days.
                logger.exception("Could not claim scheduled creator import")
            try:
                await asyncio.wait_for(self.wake.wait(), 15)
            except asyncio.TimeoutError:
                pass

    async def execute(self, run: dict) -> None:
        """Continue other creators/media after errors and record partial successes."""
        matched = imported = skipped = transcribed = 0
        errors = []
        settings = ReplaySchedule.model_validate(run["settings"])
        seen = set()
        try:
            for source in settings.sources:
                try:
                    replays, source_errors = await self.discover(source, datetime.fromisoformat(run["window_start"]), datetime.fromisoformat(run["scheduled_at"]))
                    errors.extend(source_errors)
                except Exception as exc:
                    errors.append({"source_url": source, "message": str(exc)[:500]})
                    continue
                for replay in replays:
                    if replay["id"] in seen:
                        continue
                    seen.add(replay["id"])
                    matched += 1
                    video_id = None
                    if not store.reserve_import(replay, run["id"]):
                        skipped += 1
                        video_id = store.imported_video_id(replay["id"])
                    else:
                        try:
                            request = VideoUrlRequest(url=replay["url"], quality=settings.quality)
                            # The callback starts an ordinary tracked download and
                            # associates its task before awaiting completion.
                            video = await self.importer(request, replay["id"])
                            store.update_import(replay["id"], status="completed", video_id=video["id"])
                            video_id = video["id"]
                            imported += 1
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            store.update_import(replay["id"], status="failed")
                            errors.append({"source_url": source, "message": f"{replay['title']}: {str(exc)[:400]}"})
                    if settings.transcribe and video_id:
                        store.update_run(run["id"], matched=matched, imported=imported, skipped=skipped, errors=errors, transcribed=transcribed)
                        try:
                            if self.transcriber is None:
                                raise RuntimeError("Automatic transcription is not initialized")
                            await self.transcriber(video_id, replay["id"])
                            transcribed += 1
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            errors.append({"source_url": source, "message": f"{replay['title']}: Transcription failed: {str(exc)[:350]}"})
                    store.update_run(run["id"], matched=matched, imported=imported, skipped=skipped, errors=errors, transcribed=transcribed)
            store.update_run(run["id"], matched=matched, imported=imported, skipped=skipped, errors=errors,
                             status="completed_with_errors" if errors else "completed", transcribed=transcribed)
        except asyncio.CancelledError:
            store.update_run(run["id"], matched=matched, imported=imported, skipped=skipped, errors=errors, status="interrupted", transcribed=transcribed)
            raise
        except Exception as exc:
            logger.exception("Creator import run failed")
            errors.append({"source_url": "", "message": str(exc)[:500]})
            store.update_run(run["id"], matched=matched, imported=imported, skipped=skipped, errors=errors, status="failed", transcribed=transcribed)
