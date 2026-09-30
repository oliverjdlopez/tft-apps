"""CLI for ingesting recent TFT matches from top Riot ladder players.

The ingestion loop talks to Riot and the project database: it discovers
recent matches from the top ladder, fetches their payloads, and inserts them.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from typing import Any


from core.chat_tft_riot import ChatTftRiotClient
from core.config import load_config
from core.routing import PLATFORM_TO_REGION
from db.session import (
    database_label,
    open_db,
    db_stats,
)
from sqlalchemy.orm import Session
from scripts.ingestion.utils import (
    INGEST_DEFAULTS,
    ProgressLogger,
    PROGRESS_LOG_INTERVAL_SECONDS,
    active_ingest_filters,
    build_parser,
    filter_match_for_ingest,
    format_elapsed,
    parse_args,
)
logger = logging.getLogger("tft-ingest")
ENDLESS_ANALYTICS_CATCH_UP_INTERVAL = 10

def ingest_platforms(args: argparse.Namespace) -> list[str]:
    raw_platforms = getattr(args, "platforms", None)
    if raw_platforms:
        platforms = [
            platform.strip().lower()
            for platform in str(raw_platforms).split(",")
            if platform.strip()
        ]
    else:
        platforms = [str(args.platform).lower()]

    if not platforms:
        raise SystemExit("At least one platform is required.")

    seen: set[str] = set()
    ordered: list[str] = []
    for platform in platforms:
        if platform in seen:
            continue
        if platform not in PLATFORM_TO_REGION:
            raise SystemExit(f"Unknown platform {platform!r}")
        seen.add(platform)
        ordered.append(platform)
    return ordered



async def ingest_top_matches(
    args: argparse.Namespace, conn: Session
) -> dict[str, Any]:
    from scripts.ingestion.ingest import _ingest_top_matches

    platforms = ingest_platforms(args)
    if len(platforms) != 1:
        raise SystemExit(
            "ingest_top_matches handles one platform. Use run_ingest_platforms "
            "for multi-platform ingestion."
        )
    if not load_config().secrets.riot_api_key:
        raise SystemExit("RIOT_API_KEY is not set. Add it to .env or export it.")

    single_args = argparse.Namespace(
        **{**vars(args), "platform": platforms[0], "platforms": None}
    )
    return await _ingest_top_matches(
        single_args,
        conn,
        riot_client_factory=ChatTftRiotClient,
    )


def _combine_ingest_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if len(results) == 1:
        return results[0]

    total_keys = (
        "matches_considered",
        "inserted",
        "duplicates",
        "skipped_existing",
        "skipped_filtered",
        "riot_match_fetches",
        "error_count",
    )
    combined: dict[str, Any] = {
        key: sum(int(result.get(key) or 0) for result in results)
        for key in total_keys
    }
    combined.update(
        {
            "platform": ",".join(result["platform"] for result in results),
            "platforms": [result["platform"] for result in results],
            "regions": sorted({result["region"] for result in results}),
            "queue": results[0].get("queue"),
            "max_new_matches": results[0].get("max_new_matches"),
            "player_batch_size": results[0].get("player_batch_size"),
            "fetch_concurrency": results[0].get("fetch_concurrency"),
            "analysis_every": results[0].get("analysis_every"),
            "insert_to_db": results[0].get("insert_to_db"),
            "filters": results[0].get("filters", {}),
            "errors": [
                {**error, "platform": result["platform"]}
                for result in results
                for error in result.get("errors", [])
            ][:25],
            "ladders": {
                result["platform"]: result.get("ladders", []) for result in results
            },
            "results": results,
        }
    )
    return combined


async def run_ingest_platforms(
    args: argparse.Namespace, conn: Session | None = None
) -> dict[str, Any]:
    platforms = ingest_platforms(args)
    if not load_config().secrets.riot_api_key:
        raise SystemExit("RIOT_API_KEY is not set. Add it to .env or export it.")
    from scripts.ingestion.ingest import _ingest_platforms

    logger.info(
        "Running concurrent Riot producers for platforms=%s with one DB writer",
        ",".join(platforms),
    )
    results = await _ingest_platforms(
        args,
        platforms,
        conn,
        riot_client_factory=ChatTftRiotClient,
    )
    return _combine_ingest_results(results)


def log_run_summary(
    result: dict[str, Any], elapsed: float, after: dict[str, Any]
) -> None:
    logger.info(
        "Done in %.1fs. considered=%d inserted=%d duplicates=%d "
        "skipped_existing=%d skipped_filtered=%d riot_match_fetches=%d errors=%d",
        elapsed,
        result["matches_considered"],
        result["inserted"],
        result["duplicates"],
        result["skipped_existing"],
        result["skipped_filtered"],
        result["riot_match_fetches"],
        result["error_count"],
    )
    logger.info(
        "After: matches=%s participants=%s", after["matches"], after["participants"]
    )
    if result["errors"]:
        logger.warning("First errors: %s", result["errors"])


async def run_once(args: argparse.Namespace, conn: Session) -> int:
    started = time.perf_counter()
    before = db_stats(conn)
    logger.info(
        "Before: matches=%s participants=%s",
        before["matches"],
        before["participants"],
    )
    result = await run_ingest_platforms(args)
    log_run_summary(result, time.perf_counter() - started, db_stats(conn))
    return 0 if result["error_count"] == 0 else 1


def endless_cycle_args(args: argparse.Namespace) -> argparse.Namespace:
    """Each endless cycle walks every player in the configured tiers and takes
    their N most recent games, with no cap on matches inserted per cycle."""

    overrides: dict[str, Any] = {
        "max_new_matches": None,  # no per-cycle cap: insert every new match
        "matches_per_player": args.endless_matches_per_player,
    }
    if args.player_batch_size is None:
        # Process players in batches so insert/upload progress incrementally
        # rather than buffering every ladder player before the first fetch.
        overrides["player_batch_size"] = args.endless_player_batch_size
    return argparse.Namespace(**{**vars(args), **overrides})


def endless_analytics_catch_up_due(cycle: int) -> bool:
    """Run recovery catch-up initially and every ten endless cycles."""
    return cycle == 1 or cycle % ENDLESS_ANALYTICS_CATCH_UP_INTERVAL == 0


async def run_endless(args: argparse.Namespace, conn: Session) -> int:
    cycle_args = endless_cycle_args(args)
    logger.info(
        "Endless mode: every player in tiers=%s, %d most recent games each, "
        "no per-cycle cap (cycle_delay=%ds). Ctrl-C to stop.",
        cycle_args.tiers,
        cycle_args.matches_per_player,
        cycle_args.cycle_delay,
    )
    cycle = 0
    try:
        while True:
            cycle += 1
            started = time.perf_counter()
            before = db_stats(conn)
            logger.info(
                "=== Cycle %d === Before: matches=%s participants=%s",
                cycle,
                before["matches"],
                before["participants"],
            )
            try:
                run_args = argparse.Namespace(
                    **{
                        **vars(cycle_args),
                        "force_analytics_catch_up": (
                            endless_analytics_catch_up_due(cycle)
                        ),
                    }
                )
                result = await run_ingest_platforms(run_args)
            except SystemExit:
                raise
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Cycle %d failed; retrying after %ds", cycle, args.cycle_delay
                )
            else:
                log_run_summary(
                    result, time.perf_counter() - started, db_stats(conn)
                )

            sleep_remaining = args.cycle_delay
            idle_progress = ProgressLogger(label="tft-ingest endless idle")
            while sleep_remaining > 0:
                nap = min(sleep_remaining, PROGRESS_LOG_INTERVAL_SECONDS)
                await asyncio.sleep(nap)
                sleep_remaining -= nap
                if sleep_remaining > 0:
                    idle_progress.maybe(
                        "waiting for next cycle cycle=%d remaining_sleep=%s",
                        cycle + 1,
                        format_elapsed(sleep_remaining),
                        force=True,
                    )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Endless mode stopped after %d cycle(s).", cycle)
        return 0


async def async_main(args: argparse.Namespace) -> int:
    load_config()

    conn = open_db()
    try:
        logger.info("Database: %s", database_label())
        if args.endless:
            return await run_endless(args, conn)
        return await run_once(args, conn)
    finally:
        conn.close()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level or "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # SQLAlchemy emits a high-volume INFO/DEBUG stream while flushing each match;
    # raise its threshold so it does not drown the ingestion logs or slow the loop.
    for noisy in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.orm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
