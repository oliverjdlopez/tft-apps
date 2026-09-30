"""boto3 factory and helpers for S3 raw-match payload mirroring."""

from __future__ import annotations

import gzip
import json
from typing import TYPE_CHECKING, Any

import boto3

from aws.rds import build_session

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
else:  # pragma: no cover - runtime alias
    S3Client = object


def build_s3_client(session: boto3.session.Session | None = None) -> "S3Client":
    """Return a low-level S3 client (object-level get/put/list operations)."""
    return (session or build_session()).client("s3")


def s3_match_object_key(region: str, match_id: str, *, prefix: str = "") -> str:
    """Return the deterministic object key for a raw match payload."""
    key = f"matches/{region}/{match_id}.json.gz"
    prefix = prefix.strip("/")
    return f"{prefix}/{key}" if prefix else key


def upload_match_payload(
    bucket: str,
    region: str,
    match_id: str,
    payload: Any,
    *,
    prefix: str = "",
    s3_client: "S3Client | None" = None,
) -> str:
    """Upload one raw Riot match payload as gzipped JSON; return the object key."""
    key = s3_match_object_key(region, match_id, prefix=prefix)
    body = gzip.compress(json.dumps(payload).encode("utf-8"))
    client = s3_client or build_s3_client()
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        ContentEncoding="gzip",
    )
    return key
