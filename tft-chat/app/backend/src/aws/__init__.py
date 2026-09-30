"""AWS integration layer.

Houses the boto3 object factories and helpers ChatTFT uses to talk to AWS.
"""

from __future__ import annotations

from aws.rds import (
    RdsConnectionInfo,
    build_rds_database_url,
    build_rds_client,
    build_session,
    generate_rds_auth_token,
    rds_connection_info,
    rds_ip_sync_enabled,
    sync_rds_security_group_ip,
)
from aws.s3 import (
    build_s3_client,
    s3_match_object_key,
    upload_match_payload,
)

__all__ = [
    "RdsConnectionInfo",
    "build_rds_database_url",
    "build_session",
    "build_s3_client",
    "build_rds_client",
    "rds_connection_info",
    "generate_rds_auth_token",
    "rds_ip_sync_enabled",
    "sync_rds_security_group_ip",
    "s3_match_object_key",
    "upload_match_payload",
]
