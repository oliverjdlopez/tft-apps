"""Strict API trigger for application-target ingestion."""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field, model_validator

router = APIRouter(tags=["ingest"])
logger = logging.getLogger(__name__)


class IngestionOptions(BaseModel):
    """The only request-configurable ingestion knobs; the database is not one."""

    model_config = ConfigDict(extra="forbid")

    platform: str | None = None
    platforms: str | None = None
    queue: str | None = None
    max_new_matches: int | None = Field(default=None, ge=1)
    matches_per_player: int | None = Field(default=None, ge=1)
    player_batch_size: int | None = Field(default=None, ge=1)
    tiers: str | None = None
    start_time: int | None = None
    end_time: int | None = None
    patch: str | None = None
    insert_to_db: bool | None = None
    commit_every: int | None = Field(default=None, ge=1)
    analysis_every: int | None = Field(default=None, ge=1)
    fetch_concurrency: int | None = Field(default=None, ge=1)
    endless: bool | None = None
    cycle_delay: int | None = Field(default=None, ge=1)
    endless_matches_per_player: int | None = Field(default=None, ge=1)
    endless_player_batch_size: int | None = Field(default=None, ge=1)
    log_level: str | None = None


class TriggerIngestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    options: IngestionOptions = Field(default_factory=IngestionOptions)
    time_limit_seconds: int | None = Field(default=None, gt=0, lt=86400)

    @model_validator(mode="after")
    def _require_time_limit_for_endless(self) -> "TriggerIngestBody":
        if self.options.endless and self.time_limit_seconds is None:
            raise ValueError("time_limit_seconds is required when endless=true")
        return self


def _default_args(options: IngestionOptions) -> argparse.Namespace:
    from core.config import load_config

    ingest = load_config().ingest
    values: dict[str, Any] = {
        "platform": ingest.platform,
        "platforms": ingest.platforms,
        "queue": ingest.queue,
        "max_new_matches": ingest.max_new_matches,
        "matches_per_player": ingest.matches_per_player,
        "player_batch_size": ingest.player_batch_size,
        "tiers": ingest.tiers,
        "patch_override": ingest.patch_override,
        "start_time": None,
        "end_time": None,
        "patch": None,
        "insert_to_db": ingest.insert_to_db,
        "commit_every": ingest.commit_every,
        "analysis_every": ingest.analysis_every,
        "fetch_concurrency": ingest.fetch_concurrency,
        "endless": ingest.endless,
        "cycle_delay": ingest.cycle_delay,
        "endless_matches_per_player": ingest.endless_matches_per_player,
        "endless_player_batch_size": ingest.endless_player_batch_size,
        "log_level": ingest.log_level,
        "config": None,
    }
    values.update({key: value for key, value in options.model_dump().items() if value is not None})
    if options.platform is not None and options.platforms is None:
        values["platforms"] = None
    return argparse.Namespace(**values)


async def _run_ingest(options: IngestionOptions, time_limit_seconds: int | None) -> None:
    from scripts.ingestion.main import open_db, run_endless, run_ingest_platforms

    args = _default_args(options)
    conn = None
    try:
        if args.endless and time_limit_seconds is not None:
            # Endless mode keeps this session only for cycle-level database
            # statistics. The ingestion writer opens and owns its own session.
            conn = open_db()
            try:
                await asyncio.wait_for(
                    run_endless(args, conn), timeout=time_limit_seconds
                )
            except asyncio.TimeoutError:
                logger.info("API-triggered endless ingest reached its time limit")
        else:
            result = await run_ingest_platforms(args)
            logger.info(
                "API-triggered ingest done: inserted=%d duplicates=%d errors=%d",
                result.get("inserted", 0), result.get("duplicates", 0), result.get("error_count", 0),
            )
    except Exception:
        logger.exception("API-triggered ingest failed")
    finally:
        if conn is not None:
            conn.close()


@router.post("/api/ingest/trigger", status_code=202)
async def trigger_ingest(
    body: TriggerIngestBody, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    background_tasks.add_task(_run_ingest, body.options, body.time_limit_seconds)
    return {
        "status": "accepted",
        "options": body.options.model_dump(exclude_none=True),
        "time_limit_seconds": body.time_limit_seconds,
    }


__all__ = ["IngestionOptions", "TriggerIngestBody", "router"]
