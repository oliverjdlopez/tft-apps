from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import argparse
import asyncio
from typing import Any

from aws.s3 import build_s3_client, upload_match_payload
from core.chat_tft_riot import ChatTftRiotClient
from core.config import load_config
from core.routing import PLATFORM_TO_REGION
from db.build_query_tables import (
    catch_up_query_tables,
    finalize_query_tables,
    process_match_batch,
)
from db.insert import insert_match_payload
from db.models import TABLE_MODELS
from db.session import open_db
from db.utils import existing_match_ids_from_table_models, extract_patch
from sqlalchemy.orm import Session
from utils.tft import TFTNameResolver

from scripts.ingestion.riot_fetch import (
    collect_ladder_puuids,
    fetch_match,
    select_new_match_ids,
)
from scripts.ingestion.utils import (
    ProgressLogger,
    S3UploadConfig,
    active_ingest_filters,
    filter_match_for_ingest,
    logger,
)


@dataclass(frozen=True)
class _FetchedMatch:
    platform: str
    region: str
    match_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class _PlatformDone:
    platform: str


@dataclass
class _PlatformWriteStats:
    inserted: int = 0
    duplicates: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    analytics_processed_matches: int = 0
    analytics_processed_boards: int = 0
    analytics_errors: list[dict[str, Any]] = field(default_factory=list)


class _DatabaseWriter:
    """Synchronous database owner executed on one dedicated worker thread."""

    def __init__(self, args: argparse.Namespace, conn: Session | None) -> None:
        self.args = args
        self.conn = conn
        self._owns_conn = conn is None
        self.commit_every = max(getattr(args, "commit_every", 1) or 1, 1)
        self.analysis_every = max(
            getattr(args, "analysis_every", 500) or 500,
            1,
        )
        self.pending: list[_FetchedMatch] = []
        self.pending_analysis: list[_FetchedMatch] = []
        self.resolvers: dict[tuple[str | None, int | None], TFTNameResolver] = {}
        self.stats: defaultdict[str, _PlatformWriteStats] = defaultdict(
            _PlatformWriteStats
        )
        self.s3_config: S3UploadConfig | None = None
        self.s3_client: Any = None
        self.catch_up_result: dict[str, Any] = {
            "processed_matches": 0,
            "boards": 0,
            "remaining_matches": None,
            "performed": False,
        }

    def initialize(self) -> set[str]:
        self.s3_config = S3UploadConfig.from_env()
        if self.s3_config is not None:
            self.s3_client = build_s3_client()
        if not self.args.insert_to_db:
            return set()
        if self.conn is None:
            self.conn = open_db()
        stored_match_ids = existing_match_ids_from_table_models(TABLE_MODELS)
        return stored_match_ids(self.conn)

    def _resolver_for(self, payload: dict[str, Any]) -> TFTNameResolver:
        """Return the name resolver matching the stored patch and TFT set.

        Args:
            payload: Riot match payload whose patch and set select the resolver.

        Returns:
            A resolver cached for the effective patch and set.
        """
        info = payload.get("info", {})
        set_number = info.get("tft_set_number")
        if set_number is None:
            set_number = load_config().chat.set_number
        patch = getattr(self.args, "patch_override", None) or extract_patch(
            info.get("game_version")
        )
        identity = (patch, set_number)
        resolver = self.resolvers.get(identity)
        if resolver is None:
            # This runs on the dedicated writer thread, so the resolver's HTTP
            # bootstrap cannot block Riot producers or the application event loop.
            resolver = asyncio.run(
                TFTNameResolver.from_latest(
                    set_number=set_number,
                    patch=patch or "latest",
                )
            )
            self.resolvers[identity] = resolver
        return resolver

    def _upload(self, item: _FetchedMatch) -> None:
        if self.s3_config is None:
            return
        try:
            upload_match_payload(
                self.s3_config.bucket,
                item.region,
                item.match_id,
                item.payload,
                prefix=self.s3_config.prefix,
                s3_client=self.s3_client,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("S3 upload failed for %s: %s", item.match_id, exc)

    def _drop_pending_after_connection_reset(self) -> None:
        if not self.pending:
            return
        dropped = Counter(item.platform for item in self.pending)
        logger.warning(
            "transaction reset dropped %d uncommitted matches",
            len(self.pending),
        )
        for platform, count in dropped.items():
            self.stats[platform].inserted -= count
        self.pending.clear()

    def _record_analytics_success(
        self,
        committed: list[_FetchedMatch],
        analytics: dict[str, Any],
    ) -> None:
        platform_matches = Counter(item.platform for item in committed)
        processed = int(analytics.get("processed_matches", 0))
        boards = int(analytics.get("boards", 0))
        total = sum(platform_matches.values())
        remaining_processed = processed
        remaining_boards = boards
        platforms = list(platform_matches)
        for index, platform in enumerate(platforms):
            count = platform_matches[platform]
            if index == len(platforms) - 1:
                platform_processed = remaining_processed
                platform_boards = remaining_boards
            else:
                platform_processed = min(count, remaining_processed)
                platform_boards = (
                    round(boards * count / total) if total else 0
                )
            self.stats[platform].analytics_processed_matches += platform_processed
            self.stats[platform].analytics_processed_boards += platform_boards
            remaining_processed -= platform_processed
            remaining_boards -= platform_boards

    def _record_analytics_error(
        self,
        committed: list[_FetchedMatch],
        exc: Exception,
    ) -> None:
        by_platform: defaultdict[str, list[str]] = defaultdict(list)
        for item in committed:
            by_platform[item.platform].append(item.match_id)
        for platform, match_ids in by_platform.items():
            self.stats[platform].analytics_errors.append(
                {
                    "match_ids": match_ids,
                    "stage": "analytics",
                    "error": str(exc),
                }
            )

    def _analyze_batch(self, matches: list[_FetchedMatch]) -> None:
        assert self.conn is not None
        try:
            analytics = process_match_batch(
                self.conn,
                [item.match_id for item in matches],
                finalize=False,
            )
            self._record_analytics_success(matches, analytics)
        except Exception as exc:  # noqa: BLE001
            self.conn.rollback()
            logger.exception(
                "analytics refresh failed for committed matches %s",
                [item.match_id for item in matches],
            )
            self._record_analytics_error(matches, exc)

    def _has_analytics_errors(self) -> bool:
        return any(stats.analytics_errors for stats in self.stats.values())

    def _analytics_changed(self) -> bool:
        return any(
            stats.analytics_processed_matches > 0
            for stats in self.stats.values()
        )

    def _record_cycle_analytics_error(self, stage: str, exc: Exception) -> None:
        for platform_stats in self.stats.values():
            platform_stats.analytics_errors.append(
                {"stage": stage, "error": str(exc)}
            )

    def _analyze_pending(self, *, force: bool = False) -> None:
        while len(self.pending_analysis) >= self.analysis_every or (
            force and self.pending_analysis
        ):
            batch_size = min(self.analysis_every, len(self.pending_analysis))
            matches = self.pending_analysis[:batch_size]
            del self.pending_analysis[:batch_size]
            self._analyze_batch(matches)

    def _commit_pending(self) -> None:
        if not self.pending:
            return
        assert self.conn is not None
        committed = list(self.pending)
        self.conn.commit()
        self.pending.clear()
        self.pending_analysis.extend(committed)
        self._analyze_pending()

    def persist(self, items: list[_FetchedMatch]) -> None:
        for item in items:
            self._upload(item)
            if not self.args.insert_to_db:
                logger.info("Fetched %s without DB insert", item.match_id)
                continue

            assert self.conn is not None
            try:
                resolver = self._resolver_for(item.payload)
                with self.conn.begin_nested():
                    is_new = insert_match_payload(
                        self.conn,
                        item.payload,
                        region=item.region,
                        platform=item.platform,
                        resolver=resolver,
                        patch_override=getattr(self.args, "patch_override", None),
                        commit=False,
                    )
            except Exception as exc:  # noqa: BLE001
                if not self.conn.is_active:
                    self.conn.rollback()
                    self._drop_pending_after_connection_reset()
                logger.exception("persist failed for %s", item.match_id)
                self.stats[item.platform].errors.append(
                    {
                        "match_id": item.match_id,
                        "stage": "persist",
                        "error": str(exc),
                    }
                )
                continue

            if is_new:
                self.stats[item.platform].inserted += 1
                self.pending.append(item)
                logger.info(
                    "Inserted %s (%d inserted for %s)",
                    item.match_id,
                    self.stats[item.platform].inserted,
                    item.platform,
                )
                if len(self.pending) >= self.commit_every:
                    self._commit_pending()
            else:
                self.stats[item.platform].duplicates += 1
                logger.info(
                    "Already present %s (%d duplicates for %s)",
                    item.match_id,
                    self.stats[item.platform].duplicates,
                    item.platform,
                )

    def finalize(self) -> dict[str, _PlatformWriteStats]:
        if not self.args.insert_to_db:
            if self._owns_conn and self.conn is not None:
                self.conn.close()
            return dict(self.stats)
        assert self.conn is not None
        try:
            self._commit_pending()
            self._analyze_pending(force=True)
            should_catch_up = (
                bool(getattr(self.args, "force_analytics_catch_up", False))
                or self._has_analytics_errors()
            )
            if should_catch_up:
                reason = (
                    "analytics_error"
                    if self._has_analytics_errors()
                    else "periodic"
                )
                logger.info("analytics catch-up starting reason=%s", reason)
                try:
                    catch_up = catch_up_query_tables(
                        self.conn,
                        batch_size=self.analysis_every,
                        finalize=False,
                    )
                    self.catch_up_result = {**catch_up, "performed": True}
                    logger.info("analytics catch-up complete counts=%s", catch_up)
                except Exception as exc:  # noqa: BLE001
                    self.conn.rollback()
                    logger.exception(
                        "analytics catch-up failed; raw ingestion remains committed"
                    )
                    self._record_cycle_analytics_error(
                        "analytics_catch_up", exc
                    )
            else:
                logger.info("analytics catch-up skipped for this ingestion run")
            if self._analytics_changed() or should_catch_up:
                try:
                    published = finalize_query_tables(self.conn)
                    logger.info(
                        "analytics cycle publication complete counts=%s",
                        published,
                    )
                except Exception as exc:  # noqa: BLE001
                    self.conn.rollback()
                    logger.exception(
                        "analytics finalization failed; raw ingestion remains committed"
                    )
                    self._record_cycle_analytics_error(
                        "analytics_finalize", exc
                    )
            return dict(self.stats)
        finally:
            if self._owns_conn:
                self.conn.close()

    def abort(self) -> None:
        if self.conn is None:
            return
        try:
            self.conn.rollback()
        finally:
            if self._owns_conn:
                self.conn.close()


async def _produce_platform(
    args: argparse.Namespace,
    *,
    platform: str,
    stored_ids: set[str],
    output: asyncio.Queue[_FetchedMatch | _PlatformDone],
    riot_client_factory: Callable[..., ChatTftRiotClient],
) -> dict[str, Any]:
    region = PLATFORM_TO_REGION[platform]
    progress = ProgressLogger(
        label=(
            f"tft-ingest {platform} endless cycle"
            if getattr(args, "endless", False)
            else f"tft-ingest {platform}"
        )
    )
    filters = active_ingest_filters(args)
    tiers = [tier.strip().lower() for tier in args.tiers.split(",") if tier.strip()]
    riot: ChatTftRiotClient | None = None
    skipped_existing = 0
    skipped_filtered = 0
    matches_considered = 0
    errors: list[dict[str, Any]] = []
    ladder_summary: list[dict[str, Any]] = []

    try:
        riot = riot_client_factory()
        puuids, ladder_summary = await collect_ladder_puuids(
            riot,
            platform=platform,
            queue=args.queue,
            tiers=tiers,
            max_new_matches=args.max_new_matches,
            matches_per_player=args.matches_per_player,
        )
        logger.info(
            "Collected %d ladder players for %s. Region=%s filters=%s "
            "stored_matches=%d",
            len(puuids),
            platform,
            region,
            filters,
            len(stored_ids),
        )

        known_match_ids = set(stored_ids)
        max_new = args.max_new_matches
        player_batch_size = args.player_batch_size or len(puuids) or 1
        if player_batch_size < 1:
            raise SystemExit("--player-batch-size must be greater than 0")
        if args.fetch_concurrency < 1:
            raise SystemExit("--fetch-concurrency must be greater than 0")

        for batch_start in range(0, len(puuids), player_batch_size):
            if max_new is not None and len(known_match_ids - stored_ids) >= max_new:
                break
            batch_puuids = puuids[batch_start : batch_start + player_batch_size]
            remaining_matches = (
                None
                if max_new is None
                else max_new - len(known_match_ids - stored_ids)
            )
            batch_args = argparse.Namespace(
                **{**vars(args), "max_new_matches": remaining_matches}
            )
            match_ids, batch_skipped, batch_errors = await select_new_match_ids(
                riot,
                batch_puuids,
                known_match_ids,
                batch_args,
                region,
                progress,
            )
            skipped_existing += batch_skipped
            errors.extend(batch_errors)
            known_match_ids.update(match_ids)

            semaphore = asyncio.Semaphore(args.fetch_concurrency)
            tasks = [
                asyncio.create_task(
                    fetch_match(riot, match_id, region, semaphore)
                )
                for match_id in match_ids
            ]
            matches_considered += len(tasks)
            try:
                for considered, future in enumerate(
                    asyncio.as_completed(tasks), start=1
                ):
                    match_id, match, fetch_error = await future
                    if fetch_error is not None:
                        logger.error(
                            "match fetch failed for %s: %s body=%s",
                            match_id,
                            fetch_error,
                            fetch_error.body,
                        )
                        errors.append(
                            {
                                "match_id": match_id,
                                "stage": "match",
                                "status": fetch_error.status,
                                "error": str(fetch_error),
                            }
                        )
                        continue
                    assert match is not None
                    filter_reason = filter_match_for_ingest(
                        match,
                        args.patch,
                        patch_override=getattr(args, "patch_override", None),
                    )
                    if filter_reason is not None:
                        skipped_filtered += 1
                        logger.info("Skipped %s: %s", match_id, filter_reason)
                        continue
                    await output.put(
                        _FetchedMatch(
                            platform=platform,
                            region=region,
                            match_id=match_id,
                            payload=match,
                        )
                    )
                    progress.maybe(
                        "queued matches=%d/%d considered=%d errors=%d",
                        considered,
                        len(tasks),
                        matches_considered,
                        len(errors),
                    )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await output.put(_PlatformDone(platform))
        aclose = getattr(riot, "aclose", None) if riot is not None else None
        if aclose is not None:
            await aclose()

    return {
        "platform": platform,
        "region": region,
        "queue": args.queue,
        "max_new_matches": args.max_new_matches,
        "player_batch_size": args.player_batch_size,
        "fetch_concurrency": args.fetch_concurrency,
        "analysis_every": getattr(args, "analysis_every", 500),
        "matches_considered": matches_considered,
        "skipped_existing": skipped_existing,
        "skipped_filtered": skipped_filtered,
        "insert_to_db": args.insert_to_db,
        "filters": filters,
        "riot_match_fetches": matches_considered,
        "errors": errors,
        "ladders": ladder_summary,
    }


async def _forward_platform_queue(
    source: asyncio.Queue[_FetchedMatch | _PlatformDone],
    destination: asyncio.Queue[_FetchedMatch | _PlatformDone],
) -> None:
    while True:
        item = await source.get()
        await destination.put(item)
        if isinstance(item, _PlatformDone):
            return


async def _consume_writer_queue(
    queue: asyncio.Queue[_FetchedMatch | _PlatformDone],
    *,
    platform_count: int,
    writer: _DatabaseWriter,
    executor: ThreadPoolExecutor,
) -> dict[str, _PlatformWriteStats]:
    loop = asyncio.get_running_loop()
    completed_platforms = 0
    write_batch_size = max(writer.commit_every, 1)
    writer_failure: BaseException | None = None
    while completed_platforms < platform_count:
        item = await queue.get()
        if isinstance(item, _PlatformDone):
            completed_platforms += 1
            continue

        batch = [item]
        while len(batch) < write_batch_size:
            try:
                queued = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if isinstance(queued, _PlatformDone):
                completed_platforms += 1
            else:
                batch.append(queued)
        if writer_failure is None:
            try:
                await loop.run_in_executor(executor, writer.persist, batch)
            except BaseException as exc:  # keep draining so producers cannot deadlock
                writer_failure = exc

    if writer_failure is not None:
        await loop.run_in_executor(executor, writer.abort)
        raise writer_failure
    return await loop.run_in_executor(executor, writer.finalize)


def _merge_platform_result(
    fetch_result: dict[str, Any],
    write_stats: _PlatformWriteStats,
    catch_up_result: dict[str, Any],
) -> dict[str, Any]:
    errors = [*fetch_result["errors"], *write_stats.errors]
    analytics_errors = write_stats.analytics_errors
    catch_up_performed = bool(catch_up_result.get("performed"))
    remaining_matches = catch_up_result.get("remaining_matches")
    terminal_analytics_errors = [
        error
        for error in analytics_errors
        if error.get("stage") in {"analytics_catch_up", "analytics_finalize"}
    ]
    recovered = bool(
        analytics_errors
        and catch_up_performed
        and remaining_matches == 0
        and not terminal_analytics_errors
    )
    return {
        **fetch_result,
        "inserted": write_stats.inserted,
        "duplicates": write_stats.duplicates + fetch_result["skipped_existing"],
        "errors": errors[:25],
        "error_count": len(errors),
        "analytics": {
            "processed_matches": write_stats.analytics_processed_matches,
            "processed_boards": write_stats.analytics_processed_boards,
            "remaining_matches": remaining_matches,
            "catch_up_performed": catch_up_performed,
            "recovered": recovered,
            "lagging": bool(
                terminal_analytics_errors
                or (analytics_errors and not recovered)
                or remaining_matches
            ),
            "errors": analytics_errors[:25],
            "error_count": len(analytics_errors),
        },
    }


async def _ingest_platforms(
    args: argparse.Namespace,
    platforms: list[str],
    conn: Session | None = None,
    *,
    riot_client_factory: Callable[..., ChatTftRiotClient] = ChatTftRiotClient,
) -> list[dict[str, Any]]:
    """Run concurrent platform producers feeding one dedicated DB writer."""
    executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="tft-ingest-db-writer",
    )
    loop = asyncio.get_running_loop()
    writer = _DatabaseWriter(args, conn)
    producer_tasks: list[asyncio.Task[dict[str, Any]]] = []
    forwarders: list[asyncio.Task[None]] = []
    writer_task: asyncio.Task[dict[str, _PlatformWriteStats]] | None = None
    try:
        stored_ids = await loop.run_in_executor(executor, writer.initialize)
        per_platform_capacity = max(int(args.fetch_concurrency) * 2, 1)
        writer_capacity = max(
            per_platform_capacity * max(len(platforms), 1),
            writer.commit_every,
        )
        writer_queue: asyncio.Queue[_FetchedMatch | _PlatformDone] = asyncio.Queue(
            maxsize=writer_capacity
        )
        platform_queues = {
            platform: asyncio.Queue(maxsize=per_platform_capacity)
            for platform in platforms
        }
        forwarders = [
            asyncio.create_task(
                _forward_platform_queue(platform_queues[platform], writer_queue)
            )
            for platform in platforms
        ]
        writer_task = asyncio.create_task(
            _consume_writer_queue(
                writer_queue,
                platform_count=len(platforms),
                writer=writer,
                executor=executor,
            )
        )
        producer_tasks = [
            asyncio.create_task(
                _produce_platform(
                    args,
                    platform=platform,
                    stored_ids=stored_ids,
                    output=platform_queues[platform],
                    riot_client_factory=riot_client_factory,
                )
            )
            for platform in platforms
        ]

        producer_outcomes = await asyncio.gather(
            *producer_tasks,
            return_exceptions=True,
        )
        await asyncio.gather(*forwarders)
        write_results = await writer_task

        for outcome in producer_outcomes:
            if isinstance(outcome, BaseException):
                raise outcome

        fetch_results = [
            outcome for outcome in producer_outcomes if isinstance(outcome, dict)
        ]
        return [
            _merge_platform_result(
                result,
                write_results.get(result["platform"], _PlatformWriteStats()),
                writer.catch_up_result,
            )
            for result in fetch_results
        ]
    except BaseException:
        # On cancellation or orchestration failure, stop Riot work but let the
        # forwarders and writer drain already-fetched payloads. This keeps queue
        # backpressure from deadlocking shutdown and closes the writer session
        # before its executor disappears.
        for task in producer_tasks:
            if not task.done():
                task.cancel()
        if producer_tasks:
            await asyncio.gather(*producer_tasks, return_exceptions=True)
        if forwarders:
            await asyncio.gather(*forwarders, return_exceptions=True)
        if writer_task is not None:
            try:
                await writer_task
            except BaseException:
                pass
        elif writer.conn is not None:
            try:
                await loop.run_in_executor(executor, writer.abort)
            except BaseException:
                pass
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


async def _ingest_top_matches(
    args: argparse.Namespace,
    conn: Session,
    *,
    riot_client_factory: Callable[..., ChatTftRiotClient] = ChatTftRiotClient,
) -> dict[str, Any]:
    platform = args.platform.lower()
    if platform not in PLATFORM_TO_REGION:
        raise SystemExit(f"Unknown platform {args.platform!r}")
    results = await _ingest_platforms(
        args,
        [platform],
        conn,
        riot_client_factory=riot_client_factory,
    )
    return results[0]
