"""Tests for the explicit item metadata maintenance migration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from constants import ItemTypes
from scripts import migrate_item_metadata as migration
from scripts.migrate_item_metadata import migrate_item_metadata


class FakeResolver:
    """Resolve one legacy display name without network access."""

    def item_api_name(self, value: str) -> str | None:
        """Return the canonical API name for the fixture item."""
        return "TFT_Item_Artifact_Fishbones" if value == "Fishbones" else None

    def item(self, value: str) -> object | None:
        """Return a marker object when the fixture item resolves."""
        return SimpleNamespace() if value == "Fishbones" else None

    def classify_item(self, value: str) -> ItemTypes:
        """Classify the fixture's canonical artifact identity."""
        if value == "TFT_Item_Artifact_Fishbones":
            return ItemTypes.ARTIFACT
        return ItemTypes.UNKNOWN


def _legacy_item_schema(session: Session) -> None:
    """Create the pre-metadata subset required by the migration test."""
    statements = (
        "CREATE TABLE raw_matches (match_id VARCHAR PRIMARY KEY, patch VARCHAR, "
        "tft_set_number INTEGER)",
        "CREATE TABLE board_units (match_id VARCHAR, puuid VARCHAR, unit_idx INTEGER, "
        "PRIMARY KEY (match_id, puuid, unit_idx))",
        "CREATE TABLE unit_items (match_id VARCHAR, puuid VARCHAR, unit_idx INTEGER, "
        "item_slot INTEGER, item_name VARCHAR NOT NULL, "
        "PRIMARY KEY (match_id, puuid, unit_idx, item_slot))",
    )
    for statement in statements:
        session.execute(text(statement))
    session.execute(
        text("INSERT INTO raw_matches VALUES ('m1', '16.12', 17)")
    )
    session.execute(text("INSERT INTO board_units VALUES ('m1', 'p1', 0)"))
    session.execute(
        text("INSERT INTO unit_items VALUES ('m1', 'p1', 0, 0, 'Fishbones')")
    )
    session.commit()


def test_item_metadata_migration_backfills_and_is_idempotent() -> None:
    """Backfill canonical identity once and leave a completed rerun unchanged."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine, expire_on_commit=False) as session:
            _legacy_item_schema(session)
            factory = lambda _patch, _set: FakeResolver()

            first = migrate_item_metadata(session, resolver_factory=factory)
            second = migrate_item_metadata(session, resolver_factory=factory)

            columns = {
                column["name"]
                for column in inspect(session.connection()).get_columns("unit_items")
            }
            raw_identity = session.scalar(
                text("SELECT item_api_name FROM unit_items")
            )
            metadata = session.execute(
                text(
                    "SELECT patch, tft_set_number, item_api_name, item_name, item_type "
                    "FROM item_metadata"
                )
            ).one()
            assert "item_api_name" in columns
            assert raw_identity == "TFT_Item_Artifact_Fishbones"
            assert tuple(metadata) == (
                "16.12",
                17,
                "TFT_Item_Artifact_Fishbones",
                "Fishbones",
                "artifact",
            )
            assert first == {
                "initial_state": "partial",
                "metadata_table_created": True,
                "schema_columns_added": 1,
                "raw_items_backfilled": 1,
                "metadata_rows_created": 1,
                "unresolved_items": 0,
                "analytics_cleared": True,
                "requires_rebuild": True,
            }
            assert second == {
                "initial_state": "current",
                "metadata_table_created": False,
                "schema_columns_added": 0,
                "raw_items_backfilled": 0,
                "metadata_rows_created": 0,
                "unresolved_items": 0,
                "analytics_cleared": False,
                "requires_rebuild": False,
            }
    finally:
        engine.dispose()


def test_item_metadata_migration_handles_an_empty_database() -> None:
    """Create metadata storage without requiring absent raw tables."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine) as session:
            result = migrate_item_metadata(
                session,
                resolver_factory=lambda _patch, _set: FakeResolver(),
            )

            assert inspect(session.connection()).has_table("item_metadata")
            assert result["initial_state"] == "empty"
            assert result["metadata_table_created"] is True
            assert result["requires_rebuild"] is False
    finally:
        engine.dispose()


def test_item_metadata_migration_rejects_a_partial_metadata_table() -> None:
    """Stop with an actionable error instead of guessing a partial schema."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine) as session:
            session.execute(text("CREATE TABLE item_metadata (patch VARCHAR)"))
            session.commit()

            with pytest.raises(RuntimeError, match="partially migrated item_metadata"):
                migrate_item_metadata(
                    session,
                    resolver_factory=lambda _patch, _set: FakeResolver(),
                )
    finally:
        engine.dispose()


def test_item_metadata_migration_persists_and_reports_unknown_items() -> None:
    """Keep unresolved completed items queryable with the unknown family."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine) as session:
            _legacy_item_schema(session)
            session.execute(text("UPDATE unit_items SET item_name = 'Mystery Item'"))
            session.commit()

            result = migrate_item_metadata(
                session,
                resolver_factory=lambda _patch, _set: FakeResolver(),
            )

            assert result["unresolved_items"] == 1
            assert session.execute(
                text("SELECT item_api_name, item_type FROM item_metadata")
            ).one() == ("Mystery Item", "unknown")
    finally:
        engine.dispose()


def test_item_metadata_migration_processes_bounded_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commit bounded keyset pages instead of retaining every item row."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine) as session:
            _legacy_item_schema(session)
            for item_slot in range(1, 5):
                session.execute(
                    text(
                        "INSERT INTO unit_items VALUES "
                        "('m1', 'p1', 0, :item_slot, 'Fishbones')"
                    ),
                    {"item_slot": item_slot},
                )
            session.commit()

            observed_batch_sizes: list[int] = []
            original = migration.iter_item_row_batches

            def record_batches(
                session_arg: Session,
                *,
                batch_size: int,
            ):  # type: ignore[no-untyped-def]
                """Record each bounded page yielded by the real paginator."""
                for rows in original(session_arg, batch_size=batch_size):
                    observed_batch_sizes.append(len(rows))
                    yield rows

            monkeypatch.setattr(migration, "iter_item_row_batches", record_batches)
            resolver = FakeResolver()
            resolve_api_name = Mock(wraps=resolver.item_api_name)
            resolve_item = Mock(wraps=resolver.item)
            classify_item = Mock(wraps=resolver.classify_item)
            monkeypatch.setattr(resolver, "item_api_name", resolve_api_name)
            monkeypatch.setattr(resolver, "item", resolve_item)
            monkeypatch.setattr(resolver, "classify_item", classify_item)

            result = migrate_item_metadata(
                session,
                resolver_factory=lambda _patch, _set: resolver,
                batch_size=2,
            )

            assert observed_batch_sizes == [2, 2, 1]
            assert resolve_api_name.call_count == 1
            assert resolve_item.call_count == 1
            assert classify_item.call_count == 1
            assert result["raw_items_backfilled"] == 5
            assert session.scalar(
                text("SELECT COUNT(*) FROM unit_items WHERE item_api_name IS NOT NULL")
            ) == 5
    finally:
        engine.dispose()


def test_item_metadata_migration_rejects_nonpositive_batch_size() -> None:
    """Reject an invalid batch size before making schema changes."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine) as session:
            with pytest.raises(ValueError, match="batch_size must be positive"):
                migrate_item_metadata(session, batch_size=0)
            assert not inspect(session.connection()).has_table("item_metadata")
    finally:
        engine.dispose()

