"""boto3 factories and helpers for RDS and EC2."""

from __future__ import annotations

import ipaddress
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError
from core.config import DatabaseTarget, RdsTargetConfig, load_config, resolve_database_target

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_rds import RDSClient
else:  # pragma: no cover - runtime aliases
    EC2Client = object
    RDSClient = object


def build_session(*, region_name: str | None = None) -> boto3.session.Session:
    """Build the shared boto3 session used to construct service objects.

    ``region_name`` falls back to ``AWS_REGION`` then ``AWS_DEFAULT_REGION``;
    credentials come from boto3's default provider chain.
    """
    return boto3.session.Session(
        region_name=region_name or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
    )


def build_rds_client(session: boto3.session.Session | None = None) -> "RDSClient":
    """Return a low-level RDS control-plane client (used here for IAM auth tokens)."""
    return (session or build_session()).client("rds")


def build_ec2_client(session: boto3.session.Session | None = None) -> "EC2Client":
    """Return a low-level EC2 client (used to keep RDS ingress current)."""
    return (session or build_session()).client("ec2")


# --- RDS local-IP security-group sync ----------------------------------------


def _settings_for_target(target: DatabaseTarget | None = None) -> RdsTargetConfig:
    config = load_config()
    if target is None:
        return config.rds
    return {"app": config.rds, "eval": config.rds_eval, "test": config.rds_test}[target.purpose]


def rds_ip_sync_enabled(target: DatabaseTarget | None = None) -> bool:
    """Return whether automatic RDS ingress updates are configured.

    The sync is opt-in to avoid changing AWS networking unless the developer
    explicitly supplies the target security group.
    """
    settings = _settings_for_target(target)
    if not settings.sync_local_ip:
        return False
    return bool(settings.security_group_id)


def _rds_ip_cache_file(target: DatabaseTarget | None = None) -> Path:
    return _settings_for_target(target).ip_cache_file


def _current_public_ipv4(url: str = "https://checkip.amazonaws.com") -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        value = response.read().decode("utf-8").strip()
    address = ipaddress.ip_address(value)
    if address.version != 4:
        raise ValueError(f"RDS security group sync requires an IPv4 address: {value!r}")
    return str(address)


def sync_rds_security_group_ip(
    *,
    target: DatabaseTarget | None = None,
    ec2_client: "EC2Client | None" = None,
    current_ip: str | None = None,
) -> str | None:
    """Ensure the configured RDS security group allows this machine's IP.

    Configure with ``RDS_SECURITY_GROUP_ID``. Optional knobs are
    ``RDS_SECURITY_GROUP_RULE_DESCRIPTION`` (default
    ``chat_tft_rds_local_ip``), ``RDS_PORT`` (default ``5432``),
    ``RDS_IP_CACHE_FILE``, and ``RDS_SYNC_LOCAL_IP=0`` to disable. Returns the
    allowed CIDR when a sync is configured, otherwise ``None``.
    """
    if not rds_ip_sync_enabled(target):
        return None

    settings = _settings_for_target(target)
    security_group_id = settings.security_group_id
    port = settings.port
    description = settings.security_group_rule_description
    cache_file = _rds_ip_cache_file(target)

    cidr = f"{(current_ip or _current_public_ipv4(settings.ip_check_url)).strip()}/32"
    last_cidr = cache_file.read_text().strip() if cache_file.exists() else ""

    client = ec2_client or build_ec2_client()
    rules = client.describe_security_group_rules(
        Filters=[
            {"Name": "group-id", "Values": [security_group_id]},
        ]
    ).get("SecurityGroupRules", [])
    matching_rule = next(
        (
            rule
            for rule in rules
            if not rule.get("IsEgress", False)
            and rule.get("Description") == description
            and rule.get("IpProtocol") == "tcp"
            and int(rule.get("FromPort", -1)) == port
            and int(rule.get("ToPort", -1)) == port
        ),
        None,
    )
    # Another rule may already allow this CIDR. Modifying the managed rule to
    # the same tuple would make AWS reject the request as a duplicate.
    desired_rule_exists = any(
        not rule.get("IsEgress", False)
        and rule.get("IpProtocol") == "tcp"
        and int(rule.get("FromPort", -1)) == port
        and int(rule.get("ToPort", -1)) == port
        and rule.get("CidrIpv4") == cidr
        for rule in rules
    )

    if desired_rule_exists:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(cidr)
        return cidr

    if cidr == last_cidr and matching_rule is not None:
        return cidr

    if matching_rule is not None:
        client.modify_security_group_rules(
            GroupId=security_group_id,
            SecurityGroupRules=[
                {
                    "SecurityGroupRuleId": matching_rule["SecurityGroupRuleId"],
                    "SecurityGroupRule": {
                        "IpProtocol": "tcp",
                        "FromPort": port,
                        "ToPort": port,
                        "CidrIpv4": cidr,
                        "Description": description,
                    },
                }
            ],
        )
    else:
        try:
            client.authorize_security_group_ingress(
                GroupId=security_group_id,
                IpPermissions=[
                    {
                        "IpProtocol": "tcp",
                        "FromPort": port,
                        "ToPort": port,
                        "IpRanges": [{"CidrIp": cidr, "Description": description}],
                    }
                ],
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "InvalidPermission.Duplicate":
                raise

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(cidr)
    return cidr


# --- RDS IAM authentication --------------------------------------------------


@dataclass(frozen=True)
class RdsConnectionInfo:
    """Connection coordinates for the IAM-authenticated RDS Postgres instance."""

    host: str
    port: int
    user: str
    dbname: str

    @classmethod
    def from_target(cls, target: DatabaseTarget) -> "RdsConnectionInfo":
        return cls(host=target.host, port=target.port, user=target.admin, dbname=target.database)


def build_rds_database_url(
    info: RdsConnectionInfo,
    database: str,
    *,
    password: str = "",
) -> str:
    """Build a PostgreSQL URL from RDS connection coordinates."""
    credentials = quote(info.user)
    if password:
        credentials = f"{credentials}:{quote(password, safe='')}"
    return f"postgresql://{credentials}@{info.host}:{info.port}/{database}"


def rds_connection_info(target: DatabaseTarget | None = None) -> RdsConnectionInfo:
    """Return RDS coordinates for a resolved target."""
    return RdsConnectionInfo.from_target(target or resolve_database_target("app"))


def generate_rds_auth_token(
    info: RdsConnectionInfo, *, session: boto3.session.Session | None = None
) -> str:
    """Return a short-lived (~15 min) IAM auth token for the RDS endpoint."""
    client = build_rds_client(session)
    return client.generate_db_auth_token(
        DBHostname=info.host, Port=info.port, DBUsername=info.user
    )
