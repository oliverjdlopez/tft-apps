"""Copy one PostgreSQL/RDS database into another with pg_dump and pg_restore."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import psycopg
from psycopg import sql


class CommandRunner(Protocol):
    """Callable interface used to substitute subprocess execution in tests."""

    def __call__(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        """Run one PostgreSQL client command.

        Args:
            args: Credential-safe command arguments.
            **kwargs: Options forwarded to ``subprocess.run``.

        Returns:
            Completed subprocess result used to inspect the exit status.
        """


@dataclass(frozen=True)
class CopyOptions:
    """Describe a controlled PostgreSQL source-to-destination copy.

    Attributes:
        source: Source PostgreSQL DSN consumed by pg_dump.
        destination: Destination PostgreSQL DSN consumed by pg_restore.
        create_destination: Whether to create the destination when absent.
        drop_existing_objects: Whether to clean matching destination objects.
        jobs: Number of parallel pg_restore workers.
        verbose: Whether PostgreSQL clients emit verbose progress.
    """

    source: str
    destination: str
    create_destination: bool = False
    drop_existing_objects: bool = False
    jobs: int = 1
    verbose: bool = False


def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the generic database copy command.

    Returns:
        Parser accepting explicit source and destination DSNs.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Copy a PostgreSQL/RDS source database to a destination database. "
            "Requires pg_dump and pg_restore on PATH."
        )
    )
    parser.add_argument("--source", required=True, help="Source PostgreSQL DSN.")
    parser.add_argument("--destination", required=True, help="Destination PostgreSQL DSN.")
    parser.add_argument(
        "--create-destination",
        action="store_true",
        help="Create the destination database first using the destination DSN credentials.",
    )
    parser.add_argument(
        "--drop-existing-objects",
        action="store_true",
        help="Pass --clean --if-exists to pg_restore before restoring objects.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Parallel pg_restore jobs. Defaults to 1.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable pg_dump/pg_restore verbose output.")
    return parser


def copy_rds_database(
    options: CopyOptions,
    *,
    source_password: str = "",
    destination_password: str = "",
    run: CommandRunner = subprocess.run,
) -> None:
    """Stream a pg_dump custom-format backup from source into destination.

    Args:
        options: Source, destination, and restore behavior for the copy.
        source_password: Optional source password supplied to libpq without
            embedding it in the subprocess argument list.
        destination_password: Optional destination password supplied to libpq
            without embedding it in the subprocess argument list.
        run: Subprocess runner, injectable for focused tests.
    """
    _require_tool("pg_dump")
    _require_tool("pg_restore")
    if options.jobs < 1:
        raise ValueError("--jobs must be a positive integer")
    if options.create_destination:
        create_database_from_dsn(options.destination)

    dump_cmd = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        options.source,
    ]
    restore_cmd = [
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        options.destination,
    ]
    if options.drop_existing_objects:
        restore_cmd.extend(["--clean", "--if-exists"])
    if options.jobs > 1:
        restore_cmd.extend(["--jobs", str(options.jobs)])
    if options.verbose:
        dump_cmd.append("--verbose")
        restore_cmd.append("--verbose")

    if options.jobs > 1:
        _copy_via_temp_archive(
            dump_cmd,
            restore_cmd,
            source_password=source_password,
            destination_password=destination_password,
            run=run,
        )
        return

    dump_kwargs: dict[str, object] = {"stdout": subprocess.PIPE}
    if source_password:
        dump_kwargs["env"] = {**os.environ, "PGPASSWORD": source_password}
    restore_kwargs: dict[str, object] = {"stdin": None, "check": False}
    if destination_password:
        restore_kwargs["env"] = {**os.environ, "PGPASSWORD": destination_password}

    dump_proc = subprocess.Popen(dump_cmd, **dump_kwargs)
    assert dump_proc.stdout is not None
    try:
        restore_kwargs["stdin"] = dump_proc.stdout
        restore_result = run(restore_cmd, **restore_kwargs)
    finally:
        dump_proc.stdout.close()
    dump_returncode = dump_proc.wait()

    if dump_returncode != 0:
        raise subprocess.CalledProcessError(dump_returncode, _redact_dsn_args(dump_cmd))
    if restore_result.returncode != 0:
        raise subprocess.CalledProcessError(restore_result.returncode, _redact_dsn_args(restore_cmd))


def _copy_via_temp_archive(
    dump_cmd: list[str],
    restore_cmd: list[str],
    *,
    source_password: str = "",
    destination_password: str = "",
    run: CommandRunner,
) -> None:
    """Copy through a temporary archive so pg_restore can use parallel jobs.

    Args:
        dump_cmd: Credential-safe pg_dump command arguments.
        restore_cmd: Credential-safe pg_restore command arguments.
        source_password: Optional source password passed through the process
            environment.
        destination_password: Optional destination password passed through the
            process environment.
        run: Subprocess runner, injectable for focused tests.
    """
    fd, archive_path = tempfile.mkstemp(prefix="tft-rds-copy-", suffix=".dump")
    os.close(fd)
    try:
        dump_kwargs: dict[str, object] = {"check": False}
        if source_password:
            dump_kwargs["env"] = {**os.environ, "PGPASSWORD": source_password}
        dump_result = run([*dump_cmd, "--file", archive_path], **dump_kwargs)
        if dump_result.returncode != 0:
            raise subprocess.CalledProcessError(dump_result.returncode, _redact_dsn_args(dump_cmd))
        restore_kwargs: dict[str, object] = {"check": False}
        if destination_password:
            restore_kwargs["env"] = {**os.environ, "PGPASSWORD": destination_password}
        restore_result = run([*restore_cmd, archive_path], **restore_kwargs)
        if restore_result.returncode != 0:
            raise subprocess.CalledProcessError(restore_result.returncode, _redact_dsn_args(restore_cmd))
    finally:
        try:
            os.unlink(archive_path)
        except FileNotFoundError:
            pass


def create_database_from_dsn(destination_dsn: str) -> None:
    """Create a missing destination through the postgres maintenance DB.

    Args:
        destination_dsn: PostgreSQL URL whose path names the desired database.
    """
    database_name = _database_name(destination_dsn)
    maintenance_dsn = _dsn_with_database(destination_dsn, "postgres")
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database_name,),
            )
            if cursor.fetchone():
                return
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))


def _database_name(dsn: str) -> str:
    """Extract the decoded database name used by the creation step.

    Args:
        dsn: PostgreSQL URL containing a database path.

    Returns:
        Decoded database name.

    Raises:
        ValueError: If the URL does not name a database.
    """
    parsed = urlsplit(dsn)
    name = unquote(parsed.path.lstrip("/"))
    if not name:
        raise ValueError("destination DSN must include a database name")
    return name


def _dsn_with_database(dsn: str, database: str) -> str:
    """Replace a PostgreSQL URL's database path for maintenance access.

    Args:
        dsn: Original PostgreSQL URL.
        database: Replacement database name.

    Returns:
        URL retaining the original connection coordinates and query string.
    """
    parsed = urlsplit(dsn)
    database_path = f"/{quote(database, safe='')}"
    if parsed.netloc:
        return urlunsplit(parsed._replace(path=database_path))

    # urllib collapses PostgreSQL URLs with an empty authority into a one-slash
    # form. Build the local Unix-socket form explicitly so libpq continues to
    # recognize it as a URI rather than a keyword/value string.
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{parsed.scheme}://{database_path}{query}{fragment}"


def _require_tool(name: str) -> None:
    """Require a PostgreSQL client executable before beginning a copy.

    Args:
        name: Executable name expected on PATH.

    Raises:
        RuntimeError: If the executable cannot be found.
    """
    if shutil.which(name) is None:
        raise RuntimeError(f"{name} is required but was not found on PATH")


def _redact_dsn_args(args: list[str]) -> list[str]:
    """Hide DSN arguments before attaching commands to raised errors.

    Args:
        args: PostgreSQL client command arguments.

    Returns:
        Copy of the arguments with every ``--dbname`` value redacted.
    """
    redacted = list(args)
    for index, value in enumerate(redacted[:-1]):
        if value == "--dbname":
            redacted[index + 1] = "<redacted>"
    return redacted


def main(argv: list[str] | None = None) -> None:
    """Run the explicit PostgreSQL/RDS copy command.

    Args:
        argv: Optional command arguments excluding the executable name.
    """
    args = build_parser().parse_args(argv)
    try:
        copy_rds_database(
            CopyOptions(
                source=args.source,
                destination=args.destination,
                create_destination=args.create_destination,
                drop_existing_objects=args.drop_existing_objects,
                jobs=args.jobs,
                verbose=args.verbose,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"copy failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
