"""Riot ladder discovery and match fetching for ingestion."""

from __future__ import annotations

import argparse
import asyncio
import logging
from random import shuffle
from typing import Any

from core.chat_tft_riot import ChatTftRiotClient, RiotAPIError
from scripts.ingestion.utils import ProgressLogger, ladder_entry_pages

logger = logging.getLogger("tft-ingest")


async def collect_ladder_puuids(
    riot: ChatTftRiotClient,
    *,
    platform: str,
    queue: str,
    tiers: list[str],
    max_new_matches: int | None,
    matches_per_player: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Collect unique players from the requested ranked ladder tiers."""
    target_players = (
        None
        if max_new_matches is None
        else max(1, (max_new_matches + matches_per_player - 1) // matches_per_player)
    )
    puuids: list[str] = []
    seen_puuids: set[str] = set()
    summaries: list[dict[str, Any]] = []

    for tier in tiers:
        if target_players is not None and len(puuids) >= target_players:
            break
        logger.info("Fetching %s ladder for %s queue=%s", tier, platform, queue)
        before_count = len(puuids)
        entry_count = 0
        try:
            async for entries in ladder_entry_pages(riot, tier, platform, queue):
                entry_count += len(entries)
                shuffle(entries)
                for entry in entries:
                    if target_players is not None and len(puuids) >= target_players:
                        break
                    puuid = entry.get("puuid")
                    if not puuid or puuid in seen_puuids:
                        continue
                    seen_puuids.add(puuid)
                    puuids.append(puuid)
                # Avoid fetching more pages once the overall player target is met.
                if target_players is not None and len(puuids) >= target_players:
                    break
        except RiotAPIError as exc:
            logger.error(
                "Ladder fetch failed for %s: %s body=%s", tier, exc, exc.body
            )
            summaries.append(
                {"tier": tier, "error": str(exc), "status": exc.status}
            )
            continue

        added = len(puuids) - before_count
        logger.info(
            "Tier %s returned %d entries; taking %d new players (%d/%s target)",
            tier,
            entry_count,
            added,
            len(puuids),
            "all" if target_players is None else target_players,
        )
        summaries.append({"tier": tier, "entries": entry_count, "taken": added})

    return puuids, summaries


async def select_new_match_ids(
    riot: ChatTftRiotClient,
    puuids: list[str],
    stored_ids: set[str],
    args: argparse.Namespace,
    region: str,
    progress: ProgressLogger | None = None,
) -> tuple[list[str], int, list[dict[str, Any]]]:
    """Fetch player histories and interleave unseen matches by recency."""
    seen_ids: set[str] = set()
    puuid_to_match_ids: dict[str, list[str]] = {}
    skipped_existing = 0
    errors: list[dict[str, Any]] = []
    concurrency = max(int(getattr(args, "fetch_concurrency", 1) or 1), 1)
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_player(
        player_idx: int,
        puuid: str,
    ) -> tuple[int, str, list[str] | None, RiotAPIError | None]:
        async with semaphore:
            logger.info(
                "Fetching match IDs for player %d/%d (%s...)",
                player_idx,
                len(puuids),
                puuid[:8],
            )
            queries: dict[str, Any] = {"start": 0, "count": args.matches_per_player}
            if args.start_time is not None:
                queries["startTime"] = args.start_time
            if args.end_time is not None:
                queries["endTime"] = args.end_time
            try:
                match_ids = await riot.get_tft_match_v1_match_ids_by_puuid(
                    region=region,
                    puuid=puuid,
                    queries=queries,
                )
                return player_idx, puuid, match_ids, None
            except RiotAPIError as exc:
                return player_idx, puuid, None, exc

    tasks = [
        asyncio.create_task(fetch_player(player_idx, puuid))
        for player_idx, puuid in enumerate(puuids, start=1)
    ]
    player_results: list[list[str] | None] = [None] * len(puuids)
    completed = 0
    try:
        for future in asyncio.as_completed(tasks):
            player_idx, puuid, player_match_ids, error = await future
            completed += 1
            if error is not None:
                logger.error(
                    "match_ids failed for %s...: %s body=%s",
                    puuid[:8],
                    error,
                    error.body,
                )
                errors.append(
                    {
                        "puuid": puuid,
                        "stage": "match_ids",
                        "status": error.status,
                        "error": str(error),
                    }
                )
            else:
                player_results[player_idx - 1] = player_match_ids
            if progress is not None:
                collected = sum(
                    len(ids) for ids in player_results if ids is not None
                )
                progress.maybe(
                    "collecting match IDs players=%d/%d raw_ids=%d errors=%d",
                    completed,
                    len(puuids),
                    collected,
                    len(errors),
                )
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    for puuid, player_match_ids in zip(puuids, player_results, strict=True):
        if player_match_ids is None:
            continue
        new_ids = [match_id for match_id in player_match_ids if match_id not in seen_ids]
        seen_ids.update(new_ids)
        puuid_to_match_ids[puuid] = new_ids

    if not puuid_to_match_ids:
        logger.warning("No match IDs collected from any ladder players.")
        return [], skipped_existing, errors

    max_history = max(len(match_ids) for match_ids in puuid_to_match_ids.values())
    selected: list[str] = []
    for match_index in range(max_history):
        if args.max_new_matches is not None and len(selected) >= args.max_new_matches:
            break
        for match_ids in puuid_to_match_ids.values():
            if args.max_new_matches is not None and len(selected) >= args.max_new_matches:
                break
            if match_index >= len(match_ids):
                continue
            match_id = match_ids[match_index]
            if match_id in stored_ids:
                skipped_existing += 1
            else:
                selected.append(match_id)

    return selected, skipped_existing, errors


async def fetch_match(
    riot: ChatTftRiotClient,
    match_id: str,
    region: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, dict[str, Any] | None, RiotAPIError | None]:
    async with semaphore:
        try:
            match = await riot.get_tft_match_v1_match(region=region, id=match_id)
            return match_id, match, None
        except RiotAPIError as exc:
            return match_id, None, exc


__all__ = ["collect_ladder_puuids", "fetch_match", "select_new_match_ids"]
