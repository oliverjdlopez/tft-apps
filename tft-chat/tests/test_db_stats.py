from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import (
    AnalysisProcessedMatch,
    AnalysisScope,
    Base,
    BoardTrait,
    BoardUnit,
    ItemMetadata,
    ItemStatQueryTable,
    PlayerBoard,
    RawMatch,
    UnitItem,
    UnitStatQueryTable,
)
from scripts import db_stats


def _match(match_id: str, patch: str) -> RawMatch:
    return RawMatch(
        match_id=match_id,
        region="americas",
        platform="na1",
        game_datetime=100 if patch == "16.9" else 200,
        game_length=1800,
        game_version=f"Version {patch}.1",
        patch=patch,
        queue_id=1100,
        tft_set_number=15,
        ingested_at=1,
    )


def test_collect_stats_uses_numeric_latest_patch_and_counts_scope_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            old_match = _match("old", "16.9")
            latest_match = _match("latest", "16.10")
            board = PlayerBoard(match_id="latest", puuid="player")
            unit = BoardUnit(
                match_id="latest",
                puuid="player",
                unit_idx=0,
                unit_name="Carry",
                star_level=2,
                cost=4,
            )
            unit.items.append(
                UnitItem(
                    match_id="latest",
                    puuid="player",
                    unit_idx=0,
                    item_slot=0,
                    item_name="Item",
                )
            )
            trait = BoardTrait(
                match_id="latest",
                puuid="player",
                trait_name="Trait",
                style=1,
                tier_current=1,
            )
            scope = AnalysisScope(
                patch="16.10",
                queue_id=1100,
                tft_set_number=15,
                is_active=True,
                status="ready",
                universe_boards=1,
            )
            session.add_all(
                [
                    old_match,
                    latest_match,
                    board,
                    unit,
                    trait,
                    scope,
                    ItemMetadata(
                        patch="16.10",
                        tft_set_number=15,
                        item_api_name="Item",
                        item_name="Item",
                        item_type="unknown",
                    ),
                ]
            )
            session.flush()
            session.add(
                AnalysisProcessedMatch(
                    scope_id=scope.scope_id,
                    match_id="latest",
                    board_count=1,
                )
            )
            session.add_all(
                [
                    UnitStatQueryTable(
                        scope_id=scope.scope_id,
                        unit_name="Carry",
                        star_level=2,
                        tft_set_number=15,
                    ),
                    ItemStatQueryTable(
                        scope_id=scope.scope_id,
                        item_name="Item",
                        unit_name="Carry",
                        tft_set_number=15,
                    ),
                ]
            )
            session.commit()

            stats = db_stats.collect_stats(session)

        assert stats["latest_patch"] == "16.10"
        assert stats["matches"] == 1
        assert stats["participants"] == 1
        assert stats["units"] == 1
        assert stats["items"] == 1
        assert stats["item_metadata"] == 1
        assert stats["traits"] == 1
        assert stats["analysis"]["processed_matches"] == 1
        assert stats["analysis"]["query_rows"] == {
            "unit_stats": 1,
            "item_stats": 1,
            "trait_stats": 0,
            "unit_loadout_stats": 0,
        }
    finally:
        engine.dispose()


def test_collect_stats_handles_empty_database() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            stats = db_stats.collect_stats(session)
        assert stats["latest_patch"] is None
        assert stats["matches"] == 0
        assert stats["analysis"]["scopes"] == []
    finally:
        engine.dispose()
