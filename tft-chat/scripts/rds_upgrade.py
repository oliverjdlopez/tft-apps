#!/usr/bin/env python3
"""Temporarily resize an RDS instance, then restore its original class.

Example:

    uv run tft-rds-upgrade 30 \
      --rds-instance-id chat_tft_db \
      --upgrade-instance-class db.r7g.xlarge

The requested duration starts only after RDS reports the upgraded class as
available. The script waits for the restore operation before exiting.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any


# Make this script runnable directly from a checkout as well as through its
# installed console command.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "backend" / "src"))

from aws.rds import build_rds_client
from core.config import load_config


logger = logging.getLogger("tft-rds-upgrade")
DEFAULT_POLL_SECONDS = 30
DEFAULT_TIMEOUT_SECONDS = 90 * 60


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Temporarily resize an RDS instance and restore its original class."
    )
    parser.add_argument(
        "minutes",
        nargs="?",
        type=float,
        default=30,
        help="How long to keep the upgraded instance available, in minutes (default: %(default)s).",
    )
    parser.add_argument(
        "--rds-instance-id",
        default=None,
        help="RDS DB instance identifier to resize.",
    )
    parser.add_argument(
        "--upgrade-instance-class",
        default="db.r7g.xlarge",
        help="Temporary DB instance class, for example db.r7g.xlarge (default: %(default)s).",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=DEFAULT_POLL_SECONDS,
        help="Seconds between RDS status polls (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Maximum seconds to wait for each resize (default: %(default)s).",
    )
    return parser


def _instance_details(client: Any, instance_id: str) -> dict[str, Any]:
    instances = client.describe_db_instances(DBInstanceIdentifier=instance_id).get(
        "DBInstances", []
    )
    if len(instances) != 1:
        raise RuntimeError(f"RDS instance {instance_id!r} was not found uniquely.")
    return instances[0]


def _wait_for_class(
    client: Any,
    *,
    instance_id: str,
    target_class: str,
    poll_seconds: int,
    timeout_seconds: int,
) -> None:
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    deadline = time.monotonic() + timeout_seconds
    while True:
        instance = _instance_details(client, instance_id)
        status = instance.get("DBInstanceStatus")
        instance_class = instance.get("DBInstanceClass")
        pending_class = (instance.get("PendingModifiedValues") or {}).get(
            "DBInstanceClass"
        )
        if status == "available" and instance_class == target_class:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Timed out waiting for RDS instance "
                f"{instance_id!r} to become available as {target_class!r}; "
                f"last status={status!r}, class={instance_class!r}, "
                f"pending_class={pending_class!r}."
            )
        logger.info(
            "Waiting for RDS instance=%s status=%s class=%s pending_class=%s target_class=%s",
            instance_id,
            status,
            instance_class,
            pending_class or "none",
            target_class,
        )
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))


def _resize(client: Any, *, instance_id: str, instance_class: str) -> None:
    logger.info("Requesting RDS resize instance=%s target_class=%s", instance_id, instance_class)
    client.modify_db_instance(
        DBInstanceIdentifier=instance_id,
        DBInstanceClass=instance_class,
        ApplyImmediately=True,
    )


def temporary_upgrade(
    *,
    client: Any,
    instance_id: str,
    upgrade_instance_class: str,
    minutes: float,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Resize, hold the upgraded class for ``minutes``, and restore it."""
    if minutes <= 0:
        raise ValueError("minutes must be positive")

    original_class = _instance_details(client, instance_id).get("DBInstanceClass")
    if not original_class:
        raise RuntimeError(f"RDS instance {instance_id!r} did not report DBInstanceClass.")
    # if original_class == upgrade_instance_class:
    #     raise ValueError(
    #         f"RDS instance {instance_id!r} already uses {upgrade_instance_class!r}; "
    #         "choose a different upgrade class."
    #     )

    logger.info(
        "RDS upgrade plan instance=%s original_class=%s upgrade_class=%s duration_minutes=%s",
        instance_id,
        original_class,
        upgrade_instance_class,
        minutes,
    )
    _resize(client, instance_id=instance_id, instance_class=upgrade_instance_class)
    try:
        _wait_for_class(
            client,
            instance_id=instance_id,
            target_class=upgrade_instance_class,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
        )
        logger.info("RDS instance upgraded; holding for %s minutes", minutes)
        time.sleep(minutes * 60)
    finally:
        logger.info("Restoring RDS instance=%s class=%s", instance_id, original_class)
        _resize(client, instance_id=instance_id, instance_class=original_class)
        _wait_for_class(
            client,
            instance_id=instance_id,
            target_class=original_class,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
        )
        logger.info("RDS instance restore complete instance=%s class=%s", instance_id, original_class)


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    temporary_upgrade(
        client=build_rds_client(),
        instance_id=args.rds_instance_id or config.rds_upgrade.instance_id or config.rds.instance_id,
        upgrade_instance_class=args.upgrade_instance_class,
        minutes=args.minutes,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
