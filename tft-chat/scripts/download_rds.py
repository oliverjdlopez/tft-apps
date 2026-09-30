"""Download the configured application RDS database into local PostgreSQL."""

from __future__ import annotations

import argparse
import sys
from urllib.parse import quote

from aws.rds import (
    generate_rds_auth_token,
    rds_connection_info,
    sync_rds_security_group_ip,
)
from core.config import DatabaseTarget, resolve_database_target
from scripts.copy_rds import CopyOptions, copy_rds_database


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the local RDS download command.

    Returns:
        Parser accepting the local database name and restore controls.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Download the configured application RDS database into a local "
            "PostgreSQL database. Requires pg_dump and pg_restore on PATH."
        )
    )
    parser.add_argument(
        "--local-database",
        help="Local database name. Defaults to the configured RDS database name.",
    )
    parser.add_argument(
        "--drop-existing-objects",
        action="store_true",
        help="Drop matching local objects before restoring them.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Parallel pg_restore jobs. Defaults to 1.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable pg_dump and pg_restore verbose output.",
    )
    return parser


def download_rds_database(
    source: DatabaseTarget,
    *,
    local_database: str | None = None,
    drop_existing_objects: bool = False,
    jobs: int = 1,
    verbose: bool = False,
) -> str:
    """Copy one configured RDS database into a local PostgreSQL database.

    The destination uses the local Unix-domain socket and the current libpq
    user settings. It is created when absent. Existing objects are preserved
    unless the caller explicitly requests cleanup.

    Args:
        source: Resolved application RDS target to download.
        local_database: Destination database name, defaulting to the RDS name.
        drop_existing_objects: Whether pg_restore should clean matching local
            objects before restoring them.
        jobs: Number of parallel pg_restore workers.
        verbose: Whether PostgreSQL client commands should emit verbose output.

    Returns:
        Credential-safe local PostgreSQL destination URL.

    Raises:
        ValueError: If the source is not a configured RDS target or the local
            database name is empty.
    """
    if source.auth_mode not in {"iam", "password"} or not source.host:
        raise ValueError("source must be a configured RDS target")

    destination_name = local_database if local_database is not None else source.database
    if not destination_name.strip():
        raise ValueError("local database name must not be empty")
    if jobs < 1:
        raise ValueError("--jobs must be a positive integer")

    # Match the runtime connection boundary: update optional developer ingress
    # first, then mint a short-lived IAM token immediately before pg_dump.
    sync_rds_security_group_ip(target=source)
    source_password = source.password
    if source.auth_mode == "iam":
        source_password = generate_rds_auth_token(rds_connection_info(source))

    source_dsn = f"{source.credential_safe_url}?sslmode=require"
    destination_dsn = f"postgresql:///{quote(destination_name, safe='')}"
    copy_rds_database(
        CopyOptions(
            source=source_dsn,
            destination=destination_dsn,
            create_destination=True,
            drop_existing_objects=drop_existing_objects,
            jobs=jobs,
            verbose=verbose,
        ),
        source_password=source_password,
    )
    return destination_dsn


def main(argv: list[str] | None = None) -> None:
    """Run the configured RDS-to-local download command.

    Args:
        argv: Optional command arguments excluding the executable name.
    """
    args = build_parser().parse_args(argv)
    try:
        source = resolve_database_target("app")
        destination = download_rds_database(
            source,
            local_database=args.local_database,
            drop_existing_objects=args.drop_existing_objects,
            jobs=args.jobs,
            verbose=args.verbose,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary translates failures.
        print(f"download failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Downloaded {source.credential_safe_url} to {destination}")


if __name__ == "__main__":
    main()
