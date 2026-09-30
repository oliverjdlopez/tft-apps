from __future__ import annotations

from typing import Any

from scripts import rds_upgrade


def test_temporary_upgrade_holds_then_restores(monkeypatch) -> None:
    class FakeRdsClient:
        def __init__(self) -> None:
            self.instance_class = "db.t4g.medium"
            self.calls: list[dict[str, Any]] = []

        def describe_db_instances(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append({"describe": kwargs})
            return {
                "DBInstances": [
                    {
                        "DBInstanceStatus": "available",
                        "DBInstanceClass": self.instance_class,
                    }
                ]
            }

        def modify_db_instance(self, **kwargs: Any) -> None:
            self.calls.append({"modify": kwargs})
            self.instance_class = kwargs["DBInstanceClass"]

    sleeps: list[float] = []
    client = FakeRdsClient()
    monkeypatch.setattr(rds_upgrade.time, "sleep", sleeps.append)

    rds_upgrade.temporary_upgrade(
        client=client,
        instance_id="chat_tft_db",
        upgrade_instance_class="db.r7g.xlarge",
        minutes=15,
        poll_seconds=1,
        timeout_seconds=10,
    )

    assert sleeps == [900]
    assert client.instance_class == "db.t4g.medium"
    assert [call["modify"] for call in client.calls if "modify" in call] == [
        {
            "DBInstanceIdentifier": "chat_tft_db",
            "DBInstanceClass": "db.r7g.xlarge",
            "ApplyImmediately": True,
        },
        {
            "DBInstanceIdentifier": "chat_tft_db",
            "DBInstanceClass": "db.t4g.medium",
            "ApplyImmediately": True,
        },
    ]


def test_temporary_upgrade_requires_positive_duration() -> None:
    try:
        rds_upgrade.temporary_upgrade(
            client=object(),
            instance_id="chat_tft_db",
            upgrade_instance_class="db.r7g.xlarge",
            minutes=0,
        )
    except ValueError as exc:
        assert str(exc) == "minutes must be positive"
    else:
        raise AssertionError("expected ValueError")
