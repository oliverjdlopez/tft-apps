from __future__ import annotations

import argparse
import os
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from scripts.rebuild_tables import main as rebuild_cli


def test_rebuild_tables_uses_db_modules(monkeypatch) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    session = FakeSession()
    captured: dict[str, Any] = {}

    def fake_open_db(_dsn: str | None = None) -> FakeSession:
        return session

    def fake_db_stats(active_session: FakeSession) -> dict[str, int]:
        assert active_session is session
        return {"matches": 2, "participants": 16}

    def fake_rebuild_query_tables(
        active_session: FakeSession,
        **kwargs: Any,
    ) -> dict[str, int]:
        captured["session"] = active_session
        captured["kwargs"] = kwargs
        return {
            "matches": 3,
            "unit_stats": 4,
            "item_stats": 5,
            "trait_stats": 6,
        }

    monkeypatch.setenv("CHAT_TFT_DATABASE_URL", "postgresql:///before")
    monkeypatch.setattr(rebuild_cli, "open_db", fake_open_db)
    monkeypatch.setattr(
        rebuild_cli,
        "database_label",
        lambda _dsn=None: "postgresql:///rebuild",
    )
    monkeypatch.setattr(rebuild_cli, "db_stats", fake_db_stats)
    monkeypatch.setattr(rebuild_cli, "_drop_retired_aggregate_tables", lambda _session: [])
    monkeypatch.setattr(
        rebuild_cli,
        "_query_table_counts",
        lambda active_session: {
            "matches": 1,
            "unit_stats": 2,
            "item_stats": 3,
            "trait_stats": 4,
        },
    )
    monkeypatch.setattr(
        rebuild_cli, "rebuild_db_query_tables", fake_rebuild_query_tables
    )
    args = argparse.Namespace(
        dsn="postgresql:///override",
        match_ids="NA1_a, NA1_b",
        explain=False,
        explain_analyze=False,
    )

    result = rebuild_cli.rebuild_tables(args)

    assert result["database"] == "postgresql:///rebuild"
    assert result["before"] == {
        "raw_matches": 2,
        "raw_participants": 16,
        "raw_item_metadata": 0,
        "matches": 1,
        "unit_stats": 2,
        "item_stats": 3,
        "trait_stats": 4,
    }
    assert result["counts"] == {
        "matches": 3,
        "unit_stats": 4,
        "item_stats": 5,
        "trait_stats": 6,
    }
    assert result["matches"] == 3
    assert result["unit_stats"] == 4
    assert result["item_stats"] == 5
    assert result["trait_stats"] == 6
    assert captured == {
        "session": session,
        "kwargs": {"explain": False, "explain_analyze": False},
    }
    assert session.closed is True
    assert os.environ["CHAT_TFT_DATABASE_URL"] == "postgresql:///before"


def test_full_rebuild_drops_retired_aggregate_tables() -> None:
    """Remove obsolete physical projections through the maintenance command."""
    engine = create_engine("sqlite:///:memory:")
    try:
        with Session(engine) as session:
            session.execute(text("CREATE TABLE unit_pair_stats (scope_id INTEGER)"))
            session.execute(text("CREATE TABLE trait_unit_stats (scope_id INTEGER)"))
            session.commit()

            removed = rebuild_cli._drop_retired_aggregate_tables(session)

            assert removed == ["unit_pair_stats", "trait_unit_stats"]
            inspector = inspect(engine)
            assert not inspector.has_table("unit_pair_stats")
            assert not inspector.has_table("trait_unit_stats")
    finally:
        engine.dispose()


def test_temporary_rds_upgrade_waits_then_restores(monkeypatch) -> None:
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

    client = FakeRdsClient()
    monkeypatch.setattr(rebuild_cli, "build_rds_client", lambda: client)
    args = argparse.Namespace(
        dsn="postgresql://user@rds.example.com/chat_tft",
        rds_instance_id="chat_tft_db",
        upgrade_instance_class="db.r7g.xlarge",
        rds_poll_seconds=1,
        rds_timeout_seconds=10,
    )

    with rebuild_cli._temporary_rds_upgrade(args):
        assert client.instance_class == "db.r7g.xlarge"

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


def test_temporary_rds_upgrade_skips_explicit_local_dsn(monkeypatch) -> None:
    """Do not call AWS when an explicit DSN uses a local PostgreSQL socket."""
    monkeypatch.setattr(
        rebuild_cli,
        "build_rds_client",
        lambda: (_ for _ in ()).throw(AssertionError("AWS must not be called")),
    )
    args = argparse.Namespace(
        dsn="postgresql:///chat_tft_local",
        rds_instance_id="not-an-rds-instance",
        upgrade_instance_class="db.r7g.xlarge",
    )

    with rebuild_cli._temporary_rds_upgrade(args):
        pass


def test_temporary_rds_upgrade_skips_loopback_config(monkeypatch) -> None:
    """Do not call AWS when the configured application host is loopback."""
    monkeypatch.setattr(
        rebuild_cli,
        "load_config",
        lambda: argparse.Namespace(
            rds=argparse.Namespace(
                host="127.0.0.1",
                instance_id="local-instance-placeholder",
            )
        ),
    )
    monkeypatch.setattr(
        rebuild_cli,
        "build_rds_client",
        lambda: (_ for _ in ()).throw(AssertionError("AWS must not be called")),
    )
    args = argparse.Namespace(
        dsn=None,
        rds_instance_id=None,
        upgrade_instance_class="db.r7g.xlarge",
    )

    with rebuild_cli._temporary_rds_upgrade(args):
        pass


def test_temporary_rds_upgrade_uses_configured_instance_id(monkeypatch) -> None:
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

    client = FakeRdsClient()
    monkeypatch.setattr(rebuild_cli, "build_rds_client", lambda: client)
    monkeypatch.setattr(
        rebuild_cli,
        "load_config",
        lambda: argparse.Namespace(rds=argparse.Namespace(instance_id="configured-db")),
    )
    args = argparse.Namespace(
        dsn=None,
        rds_instance_id=None,
        upgrade_instance_class="db.r7g.xlarge",
        rds_poll_seconds=1,
        rds_timeout_seconds=10,
    )

    with rebuild_cli._temporary_rds_upgrade(args):
        assert client.instance_class == "db.r7g.xlarge"

    assert [call["modify"]["DBInstanceIdentifier"] for call in client.calls if "modify" in call] == [
        "configured-db",
        "configured-db",
    ]
