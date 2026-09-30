"""Standalone connectivity checks for the project's AWS dependencies.

Two functions confirm that this machine can actually reach the services the
app relies on:

* :func:`connect_to_s3` — opens an S3 client and performs a real request.
* :func:`connect_to_rds` — opens a Postgres connection and runs ``SELECT 1``.

Both reuse the environment variables already documented in ``.env.example`` so
this script stays in sync with the rest of the codebase. Credentials and region
resolve through boto3's default provider chain (``AWS_ACCESS_KEY_ID`` /
``AWS_SECRET_ACCESS_KEY`` / ``AWS_REGION`` env vars, shared credentials files,
or an instance role).

Configuration
-------------
S3:
  * ``CHAT_TFT_S3_BUCKET`` (optional) — when set, the check runs
    ``head_bucket`` against it to confirm access to that specific bucket.
    When unset, it falls back to ``list_buckets`` to confirm credentials and
    connectivity.

RDS / Postgres:
  * The application target is built from ``RDS_HOST``, ``RDS_PORT`` (default
    ``5432``), ``RDS_ADMIN`` and ``RDS_DB``. A short-lived IAM auth token is
    minted per connection when ``RDS_PASSWORD`` is absent, and TLS is required.

Run as a script to execute both checks back to back::

    python connectivity_check.py
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "app" / "backend" / "src"))

import boto3
import psycopg

from core.config import load_config, resolve_database_target
from aws.rds import build_rds_client, build_session


def _aws_session() -> boto3.session.Session:
    """Build a boto3 session, resolving region from the standard env vars."""
    return build_session()


def connect_to_s3() -> bool:
    """Confirm connectivity to S3.

    Builds an S3 client and issues a real request: ``head_bucket`` against
    ``CHAT_TFT_S3_BUCKET`` when configured, otherwise ``list_buckets``. Returns
    ``True`` on success; raises the underlying boto3 exception on failure.
    """
    client = _aws_session().client("s3")

    bucket = os.environ.get("CHAT_TFT_S3_BUCKET", "").strip()
    if bucket:
        client.head_bucket(Bucket=bucket)
        print(f"[s3] OK — reached bucket {bucket!r}")
    else:
        response = client.list_buckets()
        count = len(response.get("Buckets", []))
        print(f"[s3] OK — credentials valid, {count} bucket(s) visible")
    return True


def _rds_dsn_and_kwargs() -> tuple[str, dict[str, str]]:
    """Resolve the Postgres DSN and libpq connect kwargs.

    Builds a DSN for the configured application RDS endpoint and mints a fresh
    IAM auth token when password authentication is not configured.
    """
    load_config()
    target = resolve_database_target("app")
    if target.auth_mode == "iam":
        token = build_rds_client(build_session()).generate_db_auth_token(
            DBHostname=target.host, Port=target.port, DBUsername=target.admin
        )
        return target.connect_url, {"password": token, "sslmode": "require"}
    return target.connect_url, {}


def connect_to_rds() -> bool:
    """Confirm connectivity to the RDS/Postgres database.

    Opens a connection (using an IAM auth token when no full DSN is provided)
    and runs ``SELECT 1``. Returns ``True`` on success; raises the underlying
    exception on failure.
    """
    dsn, connect_kwargs = _rds_dsn_and_kwargs()
    with psycopg.connect(dsn, connect_timeout=10, **connect_kwargs) as conn:
        result = conn.execute("SELECT 1").fetchone()
        if result != (1,):
            raise RuntimeError(f"Unexpected result from SELECT 1: {result!r}")
        version = conn.execute("SELECT version()").fetchone()[0]
    print(f"[rds] OK — connected and queried ({version.split(',')[0]})")
    return True


def main() -> int:
    """Run both connectivity checks back to back; return a process exit code."""
    # Load .env before the S3 check: that path reads AWS and S3 settings
    # directly from os.environ, while the RDS path resolves configuration
    # lazily inside _rds_dsn_and_kwargs().
    load_config()
    checks = (("S3", connect_to_s3), ("RDS", connect_to_rds))
    failures = []
    for name, check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - report and continue to next check
            failures.append(name)
            print(f"[{name.lower()}] FAILED — {type(exc).__name__}: {exc}")

    if failures:
        print(f"\nConnectivity check FAILED for: {', '.join(failures)}")
        return 1
    print("\nConnectivity check PASSED for S3 and RDS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
