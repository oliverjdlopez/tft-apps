from __future__ import annotations

import argparse
import os
from typing import Any

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from scripts.rebuild_tables import main as rebuild_cli


@pytest.mark.parametrize("full_rebuild", [False, True])
def test_rebuild_tables_uses_db_modules(monkeypatch, full_rebuild: bool) -> None:
    """Use catch-up by default and clear projections only for an explicit rebuild."""
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
        assert full_rebuild
        captured["session"] = active_session
        captured["kwargs"] = kwargs
        return {
            "matches": 3,
            "unit_stats": 4,
            "item_stats": 5,
            "trait_stats": 6,
        }

    def fake_catch_up_query_tables(
        active_session: FakeSession,
        **kwargs: Any,
    ) -> dict[str, int]:
        """Report newly processed matches while retaining existing aggregate totals."""
        assert not full_rebuild
        captured["session"] = active_session
        captured["kwargs"] = kwargs
        return {"processed_matches": 1, "boards": 8, "remaining_matches": 0}

    dropped: list[FakeSession] = []

    def fake_drop_retired(active_session: FakeSession) -> list[str]:
        """Record destructive cleanup so default catch-up cannot invoke it."""
        dropped.append(active_session)
        return []

    monkeypatch.setenv("CHAT_TFT_DATABASE_URL", "postgresql:///before")
    monkeypatch.setattr(rebuild_cli, "open_db", fake_open_db)
    monkeypatch.setattr(
        rebuild_cli,
        "database_label",
        lambda _dsn=None: "postgresql:///rebuild",
    )
    monkeypatch.setattr(rebuild_cli, "db_stats", fake_db_stats)
    monkeypatch.setattr(rebuild_cli, "_drop_retired_aggregate_tables", fake_drop_retired)
    query_counts = iter([
        {"matches": 1, "unit_stats": 2, "item_stats": 3, "trait_stats": 4},
        {"matches": 3, "unit_stats": 4, "item_stats": 5, "trait_stats": 6},
    ])
    monkeypatch.setattr(
        rebuild_cli,
        "_query_table_counts",
        lambda active_session: next(query_counts),
    )
    monkeypatch.setattr(
        rebuild_cli, "rebuild_db_query_tables", fake_rebuild_query_tables
    )
    monkeypatch.setattr(rebuild_cli, "catch_up_query_tables", fake_catch_up_query_tables)
    args = rebuild_cli.parse_args(
        ["--dsn", "postgresql:///override", "--patch", "17.1"]
        + (["--full-rebuild"] if full_rebuild else [])
    )

    result = rebuild_cli.rebuild_tables(args)

    assert result["database"] == "postgresql:///rebuild"
    assert result["mode"] == ("full_rebuild" if full_rebuild else "catch_up")
    assert dropped == ([session] if full_rebuild else [])
    assert result["before"] == {
        "raw_matches": 2,
        "raw_participants": 16,
        "raw_item_metadata": 0,
        "matches": 1,
        "unit_stats": 2,
        "item_stats": 3,
        "trait_stats": 4,
    }
    expected_counts = {
        "matches": 3,
        "unit_stats": 4,
        "item_stats": 5,
        "trait_stats": 6,
    }
    if not full_rebuild:
        expected_counts.update(processed_matches=1, boards=8, remaining_matches=0)
    assert result["counts"] == expected_counts
    assert result["matches"] == 3
    assert result["unit_stats"] == 4
    assert result["item_stats"] == 5
    assert result["trait_stats"] == 6
    assert captured == {
        "session": session,
        "kwargs": {
            "patch": "17.1",
            **({"explain": False, "explain_analyze": False} if full_rebuild else {}),
        },
    }
    assert session.closed is True
    assert os.environ["CHAT_TFT_DATABASE_URL"] == "postgresql:///before"


@pytest.mark.parametrize("flag", ["--explain", "--explain-analyze"])
def test_planner_profiling_requires_full_rebuild(flag: str, capsys) -> None:
    """Reject profiling flags instead of silently ignoring them during catch-up."""
    with pytest.raises(SystemExit, match="2"):
        rebuild_cli.parse_args([flag])
    assert "require --full-rebuild" in capsys.readouterr().err
    args = rebuild_cli.parse_args(["--full-rebuild", flag])
    assert args.full_rebuild is True
    assert getattr(args, flag[2:].replace("-", "_")) is True


def test_catch_up_failure_closes_session_without_full_rebuild(monkeypatch) -> None:
    """Keep dirty scopes on the explicit repair path and close failed sessions."""
    class FakeSession:
        """Track session cleanup after a maintenance failure."""

        closed = False

        def close(self) -> None:
            """Record session closure."""
            self.closed = True

    session = FakeSession()

    def fail_catch_up(active_session, **kwargs):
        """Simulate the catch-up builder refusing a dirty projection."""
        assert active_session is session
        assert kwargs == {}
        raise RuntimeError("analysis scope is dirty and requires a full rebuild")

    def reject_full_rebuild(*args, **kwargs):
        """Prevent an implicit destructive fallback on failure."""
        raise AssertionError("full rebuild must be explicitly requested")

    monkeypatch.setattr(rebuild_cli, "open_db", lambda _dsn: session)
    monkeypatch.setattr(rebuild_cli, "database_label", lambda _dsn: "local test")
    monkeypatch.setattr(rebuild_cli, "db_stats", lambda _session: {"matches": 1, "participants": 8})
    monkeypatch.setattr(rebuild_cli, "_query_table_counts", lambda _session: {})
    monkeypatch.setattr(rebuild_cli, "catch_up_query_tables", fail_catch_up)
    monkeypatch.setattr(rebuild_cli, "rebuild_db_query_tables", reject_full_rebuild)
    monkeypatch.setattr(rebuild_cli, "_drop_retired_aggregate_tables", reject_full_rebuild)

    with pytest.raises(RuntimeError, match="dirty.*full rebuild"):
        rebuild_cli.rebuild_tables(rebuild_cli.parse_args(["--dsn", "postgresql:///test"]))
    assert session.closed is True


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
