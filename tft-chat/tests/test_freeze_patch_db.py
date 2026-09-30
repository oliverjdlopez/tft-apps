from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

import db.build_query_tables as analytics
from core.config import AppConfig, ChatConfig, IngestConfig
from db.build_query_tables import AnalysisScopeIdentity
from db.models import (
    AnalysisProcessedMatch,
    AnalysisScope,
    Base,
    BoardTrait,
    BoardUnit,
    ItemMetadata,
    Match,
    PlayerBoard,
    RAW_GRAPH_MODELS,
    RawMatch,
    UnitItem,
)
from db.validation import PublicationValidationError, validate_patch_publication
from scripts import freeze_patch_db


def _config(*, set_number: int | None = 15) -> AppConfig:
    return AppConfig(
        chat=ChatConfig(patch="99.1", set_number=set_number),
        ingest=IngestConfig(queue="RANKED_TFT"),
    )


def _raw_match(
    match_id: str,
    *,
    patch: str = "16.10",
    queue_id: int = 1100,
    set_number: int = 15,
    boards: int = 1,
) -> RawMatch:
    match = RawMatch(
        match_id=match_id,
        region="americas",
        platform="na1",
        game_datetime=int(match_id.removeprefix("m") or 1),
        game_length=1800.0,
        game_version=f"Version {patch}.1",
        patch=patch,
        queue_id=queue_id,
        tft_set_number=set_number,
        tft_set_core_name=f"TFTSet{set_number}",
        ingested_at=1,
    )
    for index in range(boards):
        board = PlayerBoard(
            puuid=f"{match_id}-p{index}",
            placement=index + 1,
            level=8,
        )
        unit = BoardUnit(
            unit_idx=0,
            unit_name="Carry",
            star_level=2,
            cost=4,
        )
        unit.items.append(UnitItem(item_slot=0, item_name="Item"))
        board.units.append(unit)
        board.trait_rows.append(
            BoardTrait(
                trait_name="Trait",
                num_units=2,
                style=1,
                tier_current=1,
                tier_total=3,
            )
        )
        match.boards.append(board)
    return match


def _item_metadata(*, patch: str = "16.10", set_number: int = 15) -> ItemMetadata:
    """Build the canonical metadata row shared by raw item fixtures."""
    return ItemMetadata(
        patch=patch,
        tft_set_number=set_number,
        item_api_name="Item",
        item_name="Item",
        item_type="unknown",
    )


@pytest.fixture
def engines():
    source_engine = create_engine("sqlite+pysqlite:///:memory:")
    target_engine = create_engine("sqlite+pysqlite:///:memory:")

    for engine in (source_engine, target_engine):
        @event.listens_for(engine, "connect")
        def _foreign_keys(connection, _record):  # type: ignore[no-untyped-def]
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
    try:
        yield source_engine, target_engine
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_patch_identifier_and_validation() -> None:
    assert freeze_patch_db.patch_instance_identifier("10.5") == "chat_tft_patch_10_5"
    assert freeze_patch_db.normalize_patch(" 10.5 ") == "10.5"
    with pytest.raises(ValueError, match="patch must look"):
        freeze_patch_db.normalize_patch("Version 10.5")


def test_build_create_request_copies_source_settings() -> None:
    request = freeze_patch_db.build_create_request(
        {
            "DBInstanceClass": "db.t4g.medium",
            "Engine": "postgres",
            "EngineVersion": "16.4",
            "AllocatedStorage": 100,
            "MasterUsername": "admin",
            "Endpoint": {"Port": 5432},
            "StorageType": "gp3",
            "StorageEncrypted": True,
            "KmsKeyId": "kms-key",
            "MultiAZ": False,
            "PubliclyAccessible": True,
            "AutoMinorVersionUpgrade": True,
            "DBSubnetGroup": {"DBSubnetGroupName": "default"},
            "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-123"}],
        },
        instance_id="chat_tft_patch_10_5",
        password="secret",
        database_name="chat_tft",
        patch="10.5",
    )
    assert request["DBInstanceIdentifier"] == "chat_tft_patch_10_5"
    assert request["DBInstanceClass"] == "db.t4g.medium"
    assert request["MasterUsername"] == "admin"
    assert request["EngineVersion"] == "16.4"
    assert request["VpcSecurityGroupIds"] == ["sg-123"]
    assert request["Tags"][-1] == {"Key": "TFTPatch", "Value": "10.5"}


def test_copy_filters_every_raw_child_by_patch_queue_and_set(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    monkeypatch.setattr(analytics, "load_config", lambda: _config())
    source_engine, target_engine = engines
    with Session(source_engine, expire_on_commit=False) as source:
        source.add_all(
            [
                _raw_match("m1"),
                _raw_match("m2", patch="16.11"),
                _raw_match("m3", queue_id=1090),
                _raw_match("m4", set_number=16),
                _item_metadata(),
                _item_metadata(patch="16.11"),
                _item_metadata(set_number=16),
            ]
        )
        source.commit()
        with Session(target_engine, expire_on_commit=False) as target:
            scope = AnalysisScopeIdentity("16.10", 1100, 15)
            counts = freeze_patch_db.copy_patch_rows(source, target, scope=scope)

            assert counts == {
                "raw_matches": 1,
                "item_metadata": 1,
                "player_boards": 1,
                "board_units": 1,
                "unit_items": 1,
                "board_traits": 1,
            }
            for model in RAW_GRAPH_MODELS:
                rows = target.scalars(select(model)).all()
                assert len(rows) == 1
                if model is not ItemMetadata:
                    assert rows[0].match_id == "m1"


def test_scope_resolution_selects_most_represented_set_and_higher_tie(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    monkeypatch.setattr(analytics, "load_config", lambda: _config(set_number=None))
    source_engine, _ = engines
    with Session(source_engine) as source:
        source.add_all(
            [
                _raw_match("m1", set_number=14),
                _raw_match("m2", set_number=14),
                _raw_match("m3", set_number=15),
                _raw_match("m4", set_number=15),
            ]
        )
        source.commit()
        scope = analytics.resolve_configured_scope(source, patch="16.10")

    assert scope == AnalysisScopeIdentity("16.10", 1100, 15)


def test_configured_set_is_required_when_present(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    monkeypatch.setattr(analytics, "load_config", lambda: _config(set_number=16))
    source_engine, _ = engines
    with Session(source_engine) as source:
        source.add(_raw_match("m1", set_number=15))
        source.commit()
        with pytest.raises(ValueError, match="Configured TFT set 16"):
            analytics.resolve_configured_scope(source, patch="16.10")


def test_empty_board_scope_fails_before_aws_provisioning(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    monkeypatch.setattr(analytics, "load_config", lambda: _config())
    source_engine, _ = engines
    source = Session(source_engine)
    source.add(_raw_match("m1", boards=0))
    source.commit()
    monkeypatch.setattr(freeze_patch_db, "open_db", lambda *_args, **_kwargs: source)

    def fail_if_called():
        raise AssertionError("AWS provisioning was contacted")

    monkeypatch.setattr(freeze_patch_db, "build_rds_client", fail_if_called)
    with pytest.raises(ValueError, match="No player boards"):
        freeze_patch_db.freeze_patch_db(
            freeze_patch_db.FreezeOptions(
                patch="16.10",
                source_instance_id="chat_tft_dev1",
                source_dsn="postgresql:///source",
                master_user_password="secret",
            )
        )


def test_empty_match_scope_fails_before_aws_provisioning(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    monkeypatch.setattr(analytics, "load_config", lambda: _config())
    source_engine, _ = engines
    source = Session(source_engine)
    monkeypatch.setattr(freeze_patch_db, "open_db", lambda *_args, **_kwargs: source)

    def fail_if_called():
        raise AssertionError("AWS provisioning was contacted")

    monkeypatch.setattr(freeze_patch_db, "build_rds_client", fail_if_called)
    with pytest.raises(ValueError, match="Configured TFT patch"):
        freeze_patch_db.freeze_patch_db(
            freeze_patch_db.FreezeOptions(
                patch="16.10",
                source_instance_id="source-instance",
                source_dsn="postgresql:///source",
                master_user_password="secret",
            )
        )


def _publish_locally(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> tuple[Session, Session, dict[str, int], dict[str, int], dict[str, Any]]:
    monkeypatch.setattr(analytics, "load_config", lambda: _config())
    source_engine, target_engine = engines
    source = Session(source_engine, expire_on_commit=False)
    target = Session(target_engine, expire_on_commit=False)
    source.add_all(
        [_raw_match("m1", boards=2), _raw_match("m2", boards=1), _item_metadata()]
    )
    source.commit()
    scope, source_counts = freeze_patch_db.preflight_scope(source, "16.10")
    copied = freeze_patch_db.copy_patch_rows(source, target, scope=scope)
    analytics_counts = analytics.rebuild_query_tables(target, patch="16.10", batch_size=1)
    validation = validate_patch_publication(
        target,
        source_counts=source_counts,
        patch=scope.patch,
        queue_id=scope.queue_id,
        tft_set_number=scope.tft_set_number,
        analytics_counts=analytics_counts,
    )
    assert copied == source_counts
    return source, target, source_counts, analytics_counts, validation


def test_copy_rebuild_and_validation_publish_serving_ready_scope(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    source, target, source_counts, analytics_counts, validation = _publish_locally(
        monkeypatch, engines
    )
    try:
        scope = target.scalar(select(AnalysisScope))
        assert (scope.patch, scope.queue_id, scope.tft_set_number) == ("16.10", 1100, 15)
        assert scope.is_active is True
        assert scope.status == "ready"
        assert scope.universe_boards == 3
        assert target.scalar(select(func.count()).select_from(AnalysisProcessedMatch)) == 2
        assert target.scalar(select(func.count()).select_from(Match)) == 3
        assert analytics_counts["processed_matches"] == 2
        assert validation["raw_counts_match"] is True
        assert validation["projection"] == {
            "matches": 3,
            "player_boards": 3,
            "universe_boards": 3,
        }
        assert source_counts["raw_matches"] == 2
    finally:
        source.close()
        target.close()


def test_publication_validation_rejects_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    source, target, source_counts, analytics_counts, _ = _publish_locally(
        monkeypatch, engines
    )
    try:
        bad_counts = {**source_counts, "unit_items": source_counts["unit_items"] + 1}
        with pytest.raises(PublicationValidationError, match="raw-graph counts differ"):
            validate_patch_publication(
                target,
                source_counts=bad_counts,
                patch="16.10",
                queue_id=1100,
                tft_set_number=15,
                analytics_counts=analytics_counts,
            )
    finally:
        source.close()
        target.close()


def test_publication_validation_rejects_out_of_scope_rows(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    source, target, source_counts, analytics_counts, _ = _publish_locally(
        monkeypatch, engines
    )
    try:
        target.add(_raw_match("m9", patch="16.11", boards=0))
        target.commit()
        expected_counts = {
            **source_counts,
            "raw_matches": source_counts["raw_matches"] + 1,
        }
        with pytest.raises(PublicationValidationError) as caught:
            validate_patch_publication(
                target,
                source_counts=expected_counts,
                patch="16.10",
                queue_id=1100,
                tft_set_number=15,
                analytics_counts=analytics_counts,
            )
        assert "target contains raw matches outside the configured scope" in (
            caught.value.errors
        )
    finally:
        source.close()
        target.close()


def test_publication_validation_rejects_normalized_orphans(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    source, target, source_counts, analytics_counts, _ = _publish_locally(
        monkeypatch, engines
    )
    try:
        target.rollback()
        target.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")
        target.execute(
            text(
                "INSERT INTO player_boards (match_id, puuid, placement) "
                "VALUES ('missing', 'orphan', 8)"
            )
        )
        target.commit()
        expected_counts = {
            **source_counts,
            "player_boards": source_counts["player_boards"] + 1,
        }
        with pytest.raises(PublicationValidationError) as caught:
            validate_patch_publication(
                target,
                source_counts=expected_counts,
                patch="16.10",
                queue_id=1100,
                tft_set_number=15,
                analytics_counts=analytics_counts,
            )
        assert "target normalized graph contains orphan rows" in caught.value.errors
    finally:
        source.close()
        target.close()


def test_publication_validation_rejects_wrong_scope_and_lag(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    source, target, source_counts, analytics_counts, _ = _publish_locally(
        monkeypatch, engines
    )
    try:
        scope = target.scalar(select(AnalysisScope))
        scope.patch = "16.11"
        target.delete(target.scalar(select(AnalysisProcessedMatch).limit(1)))
        target.commit()
        with pytest.raises(PublicationValidationError) as caught:
            validate_patch_publication(
                target,
                source_counts=source_counts,
                patch="16.10",
                queue_id=1100,
                tft_set_number=15,
                analytics_counts=analytics_counts,
            )
        assert "active analysis scope identity or status is incorrect" in caught.value.errors
        assert "active analysis scope has processed-match lag" in caught.value.errors
    finally:
        source.close()
        target.close()


class _Waiter:
    def __init__(self, client: Any) -> None:
        self.client = client

    def wait(self, **_: Any) -> None:
        self.client.instances["chat_tft_patch_16_10"]["DBInstanceStatus"] = "available"


class _FakeRdsClient:
    def __init__(self) -> None:
        self.instances = {
            "chat_tft_dev1": {
                "DBInstanceClass": "db.t4g.medium",
                "Engine": "postgres",
                "EngineVersion": "16.4",
                "AllocatedStorage": 100,
                "MasterUsername": "admin",
                "Endpoint": {"Port": 5432},
                "DBSubnetGroup": {"DBSubnetGroupName": "default"},
                "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-123"}],
            }
        }
        self.create_calls: list[dict[str, Any]] = []

    def describe_db_instances(self, *, DBInstanceIdentifier: str) -> dict[str, Any]:  # noqa: N803
        instance = self.instances.get(DBInstanceIdentifier)
        return {"DBInstances": [instance] if instance else []}

    def create_db_instance(self, **kwargs: Any) -> None:
        self.create_calls.append(kwargs)
        self.instances[kwargs["DBInstanceIdentifier"]] = {
            **kwargs,
            "MasterUsername": kwargs["MasterUsername"],
            "Endpoint": {"Address": "frozen.example", "Port": 5432},
            "DBInstanceStatus": "creating",
        }

    def get_waiter(self, _: str) -> _Waiter:
        return _Waiter(self)


def test_provision_refuses_existing_instance_and_requires_password() -> None:
    client = _FakeRdsClient()
    client.instances["chat_tft_patch_16_10"] = {"DBInstanceStatus": "available"}
    with pytest.raises(RuntimeError, match="already exists"):
        freeze_patch_db.provision_patch_instance(
            client,
            freeze_patch_db.FreezeOptions(
                patch="16.10",
                master_user_password="secret",
            ),
        )
    with pytest.raises(ValueError, match="master password"):
        freeze_patch_db.provision_patch_instance(
            _FakeRdsClient(),
            freeze_patch_db.FreezeOptions(patch="16.10"),
        )


def test_post_provision_failure_reports_stage_and_retains_instance(
    monkeypatch: pytest.MonkeyPatch,
    engines,
) -> None:
    monkeypatch.setattr(analytics, "load_config", lambda: _config())
    source_engine, target_engine = engines
    source = Session(source_engine, expire_on_commit=False)
    target = Session(target_engine, expire_on_commit=False)
    source.add(_raw_match("m1"))
    source.commit()
    sessions = iter((source, target))
    monkeypatch.setattr(
        freeze_patch_db,
        "open_db",
        lambda *_args, **_kwargs: next(sessions),
    )
    monkeypatch.setattr(
        freeze_patch_db,
        "rebuild_query_tables",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    client = _FakeRdsClient()

    with pytest.raises(freeze_patch_db.FreezePublicationError) as caught:
        freeze_patch_db.freeze_patch_db(
            freeze_patch_db.FreezeOptions(
                patch="16.10",
                source_instance_id="chat_tft_dev1",
                source_dsn="postgresql:///source",
                master_user_password="secret",
                poll_seconds=1,
                timeout_seconds=1,
            ),
            rds_client=client,
        )

    assert caught.value.stage == "analytics-rebuild"
    assert caught.value.instance_id == "chat_tft_patch_16_10"
    assert "chat_tft_patch_16_10" in client.instances
