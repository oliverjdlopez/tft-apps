"""Shared helpers for the TFT match ingestion CLI."""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
import logging
import time
from pathlib import Path
from typing import Any

from core.chat_tft_riot import ChatTftRiotClient
from core.config import load_config
from core.models import RiotMatch
from db.utils import extract_patch

logger = logging.getLogger("tft-ingest")

FETCH_CONCURRENCY = 10
PROGRESS_LOG_INTERVAL_SECONDS = 180
# Endless mode walks every ladder player and takes their most recent games.
ENDLESS_MATCHES_PER_PLAYER = 5
ENDLESS_PLAYER_BATCH_SIZE = 50
INGEST_DEFAULTS: dict[str, Any] = {
    **asdict(load_config().ingest),
    "start_time": None,
    "end_time": None,
    "patch": None,
}
def format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{remainder:02d}s"
    if minutes:
        return f"{minutes}m{remainder:02d}s"
    return f"{remainder}s"


class ProgressLogger:
    def __init__(
        self,
        *,
        label: str,
        interval_seconds: int = PROGRESS_LOG_INTERVAL_SECONDS,
    ) -> None:
        self.label = label
        self.interval_seconds = interval_seconds
        self.started_at = time.monotonic()
        self.last_logged_at = self.started_at

    def maybe(self, message: str, *args: Any, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_logged_at < self.interval_seconds:
            return

        self.last_logged_at = now
        logger.info(
            "%s still running after %s: " + message,
            self.label,
            format_elapsed(now - self.started_at),
            *args,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest recent TFT matches from selected ranked ladder tiers."
    )
    parser.add_argument(
        "--config",
        type=Path,
        help=(
            "INI config file to read. Defaults to ~/.config/chat_tft/config.ini "
            "and ./chat_tft.ini when present."
        ),
    )
    parser.add_argument(
        "--platform",
        default=argparse.SUPPRESS,
        help="Riot platform shard, e.g. na1, euw1, kr. Default: na1.",
    )
    parser.add_argument(
        "--platforms",
        default=argparse.SUPPRESS,
        help=(
            "Comma-separated Riot platform shards to ingest. Each platform "
            "uses a concurrent Riot producer feeding the shared DB writer."
        ),
    )
    parser.add_argument(
        "--queue",
        default=argparse.SUPPRESS,
        help="Riot TFT queue. Default: RANKED_TFT.",
    )
    parser.add_argument(
        "--max-new-matches",
        type=int,
        default=argparse.SUPPRESS,
        help=(
            "Stop after this many unique new match IDs have been selected "
            "for ingestion. Default: 50."
        ),
    )
    parser.add_argument(
        "--matches-per-player",
        type=int,
        default=argparse.SUPPRESS,
        help="Recent match IDs to request for each ladder player. Default: 10.",
    )
    parser.add_argument(
        "--player-batch-size",
        type=int,
        default=argparse.SUPPRESS,
        help=(
            "Number of ladder players to process per ingestion batch. "
            "Default: all selected players in one batch."
        ),
    )
    parser.add_argument(
        "--tiers",
        default=argparse.SUPPRESS,
        help=(
            "Comma-separated ranked tiers from iron through challenger; "
            "lower tiers walk divisions I-IV. Default: challenger,grandmaster,master."
        ),
    )
    parser.add_argument(
        "--start-time",
        type=int,
        default=argparse.SUPPRESS,
        help="Unix seconds; only request matches at or after this time.",
    )
    parser.add_argument(
        "--end-time",
        type=int,
        default=argparse.SUPPRESS,
        help="Unix seconds; only request matches before this time.",
    )
    parser.add_argument(
        "--patch",
        default=argparse.SUPPRESS,
        help='Patch string to keep, e.g. "14.10". Off-patch matches are skipped after fetch.',
    )
    parser.add_argument(
        "--insert-to-db",
        dest="insert_to_db",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Insert fetched matches into the database. Default: enabled.",
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=argparse.SUPPRESS,
        help="Number of inserted matches per database commit. Default: 25.",
    )
    parser.add_argument(
        "--analysis-every",
        type=int,
        default=argparse.SUPPRESS,
        help=(
            "Number of committed matches per incremental analysis run. "
            "Default: 500; remaining matches are analyzed when ingestion ends."
        ),
    )
    parser.add_argument(
        "--fetch-concurrency",
        type=int,
        default=argparse.SUPPRESS,
        help=(
            "Maximum concurrent Riot match-ID and match-detail requests per "
            "platform."
        ),
    )
    parser.add_argument(
        "--endless",
        action="store_true",
        default=argparse.SUPPRESS,
        help=(
            "Run forever, repeatedly discovering and ingesting the most recent "
            "matches. Intended for an always-on server. Ctrl-C to stop."
        ),
    )
    parser.add_argument(
        "--cycle-delay",
        type=int,
        default=argparse.SUPPRESS,
        help="Seconds to sleep between endless-mode cycles. Default: 60.",
    )
    parser.add_argument(
        "--endless-matches-per-player",
        type=int,
        default=argparse.SUPPRESS,
        help="Recent matches per player in endless mode.",
    )
    parser.add_argument(
        "--endless-player-batch-size",
        type=int,
        default=argparse.SUPPRESS,
        help="Default player batch size in endless mode.",
    )
    parser.add_argument(
        "--log-level",
        default=argparse.SUPPRESS,
        help="Python logging level name, e.g. INFO or ERROR.",
    )
    return parser


def load_ingest_config(path: Path | None = None) -> dict[str, Any]:
    try:
        settings = load_config(path).ingest
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    values = asdict(settings)
    values.update({"start_time": None, "end_time": None, "patch": None})
    return values


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_args = build_parser().parse_args(argv)
    config_path = getattr(raw_args, "config", None)
    merged = dict(INGEST_DEFAULTS)
    merged.update(load_ingest_config(config_path))

    for key, value in vars(raw_args).items():
        if key == "config":
            continue
        merged[key] = value
    if hasattr(raw_args, "platform") and not hasattr(raw_args, "platforms"):
        # An explicit single-platform CLI override must supersede a configured
        # multi-platform list.
        merged["platforms"] = None

    merged["config"] = config_path
    return argparse.Namespace(**merged)


@dataclass(frozen=True)
class S3UploadConfig:
    bucket: str
    prefix: str = ""

    @classmethod
    def from_env(cls) -> "S3UploadConfig | None":
        s3 = load_config().s3
        if not s3.upload:
            return None
        if not s3.bucket:
            raise SystemExit(
                "CHAT_TFT_S3_BUCKET is required when CHAT_TFT_S3_UPLOAD is enabled."
            )
        return cls(bucket=s3.bucket, prefix=s3.prefix)


def active_ingest_filters(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "patch": args.patch,
            "start_time": args.start_time,
            "end_time": args.end_time,
        }.items()
        if value is not None
    }


def filter_match_for_ingest(
    match: dict[str, Any],
    patch: str | None,
    *,
    patch_override: str | None = None,
) -> str | None:
    """Filter one Riot match using its effective patch.

    Args:
        match: Riot match payload to inspect.
        patch: Optional patch filter selected for this ingestion run.
        patch_override: Configured patch that replaces Riot's inferred patch.

    Returns:
        A skip reason when the effective patch does not match, otherwise None.
    """
    if patch is None:
        return None

    parsed = RiotMatch.model_validate(match)
    match_patch = patch_override or extract_patch(parsed.info.game_version)
    if match_patch != patch:
        return f"patch {match_patch or 'unknown'} != {patch}"
    return None


# ---------------------------------------------------------------------------
# riot_fetch.py: ranked ladder discovery
#
# Lower tiers require division pagination instead of a single ladder response.
# ---------------------------------------------------------------------------


async def ladder_entry_pages(
    riot: ChatTftRiotClient,
    tier: str,
    platform: str,
    queue: str,
) -> AsyncIterator[list[dict[str, Any]]]:
    """Stream ranked ladder pages for ingestion across supported tiers.

    Args:
        riot: Rate-limited client shared by the ingestion producer.
        tier: Ranked tier, matched without case sensitivity.
        platform: Platform shard used for league requests.
        queue: Ranked queue whose players should be collected.

    Yields:
        A division page or the complete Master/Grandmaster/Challenger ladder.

    Raises:
        ValueError: The tier is not a supported ranked tier.
    """
    tier = tier.strip().lower()
    if tier in {"challenger", "grandmaster", "master"}:
        ladder = await riot.league_top(tier, platform, queue)
        yield ladder.get("entries") or []
        return
    if tier not in {"diamond", "emerald", "platinum", "gold", "silver", "bronze", "iron"}:
        raise ValueError(f"Unsupported ranked tier: {tier}")

    for division in ("I", "II", "III", "IV"):
        page = 1
        while True:
            logger.info("Fetching %s %s page=%d for %s", tier, division, page, platform)
            entries = await riot.get_tft_league_v1_entries_by_division(
                region=platform.lower(),
                tier=tier.upper(),
                division=division,
                queries={"page": page, "queue": queue},
            )
            if not entries:
                break
            yield entries
            page += 1
