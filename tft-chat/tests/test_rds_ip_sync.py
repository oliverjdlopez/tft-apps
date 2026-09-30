from __future__ import annotations

from pathlib import Path

from botocore.exceptions import ClientError

from aws.rds import rds_ip_sync_enabled, sync_rds_security_group_ip


class FakeEc2Client:
    def __init__(self, rules: list[dict] | None = None) -> None:
        self.rules = rules or []
        self.filters: list[dict] = []
        self.modified: list[dict] = []
        self.authorized: list[dict] = []
        self.authorize_error: ClientError | None = None

    def describe_security_group_rules(self, Filters: list[dict]) -> dict:  # noqa: N803
        self.filters = Filters
        return {"SecurityGroupRules": self.rules}

    def modify_security_group_rules(self, **kwargs) -> None:
        self.modified.append(kwargs)

    def authorize_security_group_ingress(self, **kwargs) -> None:
        self.authorized.append(kwargs)
        if self.authorize_error is not None:
            raise self.authorize_error


def test_rds_ip_sync_is_opt_in(monkeypatch) -> None:
    # Keep dotenv from repopulating local developer credentials.
    monkeypatch.setenv("RDS_SECURITY_GROUP_ID", "")
    monkeypatch.setenv("RDS_SYNC_LOCAL_IP", "")

    assert rds_ip_sync_enabled() is False
    assert (
        sync_rds_security_group_ip(
            ec2_client=FakeEc2Client(), current_ip="203.0.113.5"
        )
        is None
    )


def test_sync_rds_security_group_ip_authorizes_new_rule(
    monkeypatch, tmp_path: Path
) -> None:
    cache_file = tmp_path / "rds-ip.txt"
    monkeypatch.setenv("RDS_SECURITY_GROUP_ID", "sg-123")
    monkeypatch.setenv("RDS_PORT", "5432")
    monkeypatch.setenv("RDS_SECURITY_GROUP_RULE_DESCRIPTION", "dev-local-postgres")
    monkeypatch.setenv("RDS_IP_CACHE_FILE", str(cache_file))
    client = FakeEc2Client()

    cidr = sync_rds_security_group_ip(ec2_client=client, current_ip="203.0.113.5")

    assert cidr == "203.0.113.5/32"
    assert client.filters == [
        {"Name": "group-id", "Values": ["sg-123"]},
    ]
    assert cache_file.read_text() == "203.0.113.5/32"
    assert client.modified == []
    assert client.authorized == [
        {
            "GroupId": "sg-123",
            "IpPermissions": [
                {
                    "IpProtocol": "tcp",
                    "FromPort": 5432,
                    "ToPort": 5432,
                    "IpRanges": [
                        {
                            "CidrIp": "203.0.113.5/32",
                            "Description": "dev-local-postgres",
                        }
                    ],
                }
            ],
        }
    ]


def test_sync_rds_security_group_ip_modifies_existing_rule(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RDS_SECURITY_GROUP_ID", "sg-123")
    monkeypatch.setenv("RDS_PORT", "5432")
    monkeypatch.setenv("RDS_SECURITY_GROUP_RULE_DESCRIPTION", "dev-local-postgres")
    monkeypatch.setenv("RDS_IP_CACHE_FILE", str(tmp_path / "rds-ip.txt"))
    client = FakeEc2Client(
        [
            {
                "SecurityGroupRuleId": "sgr-wrong-port",
                "IsEgress": False,
                "Description": "dev-local-postgres",
                "IpProtocol": "tcp",
                "FromPort": 5433,
                "ToPort": 5433,
            },
            {
                "SecurityGroupRuleId": "sgr-123",
                "IsEgress": False,
                "Description": "dev-local-postgres",
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
            }
        ]
    )

    cidr = sync_rds_security_group_ip(ec2_client=client, current_ip="203.0.113.6")

    assert cidr == "203.0.113.6/32"
    assert client.authorized == []
    assert client.modified == [
        {
            "GroupId": "sg-123",
            "SecurityGroupRules": [
                {
                    "SecurityGroupRuleId": "sgr-123",
                    "SecurityGroupRule": {
                        "IpProtocol": "tcp",
                        "FromPort": 5432,
                        "ToPort": 5432,
                        "CidrIpv4": "203.0.113.6/32",
                        "Description": "dev-local-postgres",
                    },
                }
            ],
        }
    ]


def test_sync_rds_security_group_ip_accepts_existing_duplicate_cidr(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RDS_SECURITY_GROUP_ID", "sg-123")
    monkeypatch.setenv("RDS_PORT", "5432")
    monkeypatch.setenv("RDS_SECURITY_GROUP_RULE_DESCRIPTION", "dev-local-postgres")
    cache_file = tmp_path / "rds-ip.txt"
    monkeypatch.setenv("RDS_IP_CACHE_FILE", str(cache_file))
    client = FakeEc2Client(
        [
            {
                "SecurityGroupRuleId": "sgr-managed",
                "IsEgress": False,
                "Description": "dev-local-postgres",
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
                "CidrIpv4": "198.51.100.10/32",
            },
            {
                "SecurityGroupRuleId": "sgr-existing",
                "IsEgress": False,
                "Description": "another-rule",
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
                "CidrIpv4": "203.0.113.5/32",
            },
        ]
    )

    cidr = sync_rds_security_group_ip(ec2_client=client, current_ip="203.0.113.5")

    assert cidr == "203.0.113.5/32"
    assert cache_file.read_text() == "203.0.113.5/32"
    assert client.modified == []
    assert client.authorized == []


def test_sync_rds_security_group_ip_uses_cache_when_rule_matches(
    monkeypatch, tmp_path: Path
) -> None:
    cache_file = tmp_path / "rds-ip.txt"
    cache_file.write_text("203.0.113.6/32")
    monkeypatch.setenv("RDS_SECURITY_GROUP_ID", "sg-123")
    monkeypatch.setenv("RDS_SECURITY_GROUP_RULE_DESCRIPTION", "dev-local-postgres")
    monkeypatch.setenv("RDS_IP_CACHE_FILE", str(cache_file))
    client = FakeEc2Client(
        [
            {
                "SecurityGroupRuleId": "sgr-123",
                "IsEgress": False,
                "Description": "dev-local-postgres",
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
            }
        ]
    )

    cidr = sync_rds_security_group_ip(ec2_client=client, current_ip="203.0.113.6")

    assert cidr == "203.0.113.6/32"
    assert client.authorized == []
    assert client.modified == []


def test_sync_rds_security_group_ip_treats_duplicate_authorize_as_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cache_file = tmp_path / "rds-ip.txt"
    monkeypatch.setenv("RDS_SECURITY_GROUP_ID", "sg-123")
    monkeypatch.setenv("RDS_PORT", "5432")
    monkeypatch.setenv("RDS_SECURITY_GROUP_RULE_DESCRIPTION", "dev-local-postgres")
    monkeypatch.setenv("RDS_IP_CACHE_FILE", str(cache_file))
    client = FakeEc2Client()
    client.authorize_error = ClientError(
        {
            "Error": {
                "Code": "InvalidPermission.Duplicate",
                "Message": "the specified rule already exists",
            }
        },
        "AuthorizeSecurityGroupIngress",
    )

    cidr = sync_rds_security_group_ip(ec2_client=client, current_ip="203.0.113.5")

    assert cidr == "203.0.113.5/32"
    assert cache_file.read_text() == "203.0.113.5/32"
    assert client.modified == []
    assert len(client.authorized) == 1
