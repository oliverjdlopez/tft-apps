"""Reusable relational-v2 and serving-publication validation."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import and_, func, inspect, or_, select, text
from sqlalchemy.orm import Session

from .models import (
    ANALYSIS_FACT_SCHEMA_VERSION,
    AnalysisBoard,
    AnalysisBoardItem,
    AnalysisBoardTrait,
    AnalysisBoardTraitList,
    AnalysisBoardUnit,
    AnalysisBoardUnitList,
    AnalysisFactBuild,
    AnalysisProcessedMatch,
    AnalysisScope,
    BoardTrait,
    BoardUnit,
    ItemMetadata,
    ItemStatQueryTable,
    Match,
    PlayerBoard,
    RAW_GRAPH_MODELS,
    RawMatch,
    UnitItem,
)


class PublicationValidationError(RuntimeError):
    """Raised when a built patch target is not safe to serve."""

    def __init__(self, errors: list[str], validation: dict[str, Any]) -> None:
        self.errors = errors
        self.validation = validation
        super().__init__("publication validation failed: " + "; ".join(errors))


def _count(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def validate_relational_v2(session: Session) -> dict[str, Any]:
    """Return foreign-key, orphan, and analytics-ledger validation details."""
    inspector = inspect(session.connection())
    expected_fks = {
        "player_boards": 1,
        "board_units": 1,
        "unit_items": 1,
        "board_traits": 1,
        "analysis_processed_matches": 2,
        "analysis_fact_builds": 1,
        "analysis_boards": 1,
        "analysis_board_unit_lists": 1,
        "analysis_board_trait_lists": 1,
        "analysis_board_units": 1,
        "analysis_board_items": 1,
        "analysis_board_traits": 1,
        "unit_stats": 1,
        "item_stats": 1,
        "trait_stats": 1,
        "unit_loadout_stats": 1,
    }
    fk_counts = {
        table_name: len(inspector.get_foreign_keys(table_name))
        for table_name in expected_fks
        if inspector.has_table(table_name)
    }
    missing_fks = {
        name: {"expected": expected, "actual": fk_counts.get(name, 0)}
        for name, expected in expected_fks.items()
        if fk_counts.get(name, 0) < expected
    }
    unvalidated_foreign_keys: list[str] = []
    if session.get_bind().dialect.name == "postgresql":
        unvalidated_foreign_keys = list(
            session.scalars(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype = 'f' AND NOT convalidated"
                )
            )
        )

    board_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(PlayerBoard)
            .outerjoin(RawMatch, RawMatch.match_id == PlayerBoard.match_id)
            .where(RawMatch.match_id.is_(None))
        )
        or 0
    )
    unit_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(BoardUnit)
            .outerjoin(
                PlayerBoard,
                and_(
                    PlayerBoard.match_id == BoardUnit.match_id,
                    PlayerBoard.puuid == BoardUnit.puuid,
                ),
            )
            .where(PlayerBoard.match_id.is_(None))
        )
        or 0
    )
    item_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(UnitItem)
            .outerjoin(
                BoardUnit,
                and_(
                    BoardUnit.match_id == UnitItem.match_id,
                    BoardUnit.puuid == UnitItem.puuid,
                    BoardUnit.unit_idx == UnitItem.unit_idx,
                ),
            )
            .where(BoardUnit.match_id.is_(None))
        )
        or 0
    )
    trait_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(BoardTrait)
            .outerjoin(
                PlayerBoard,
                and_(
                    PlayerBoard.match_id == BoardTrait.match_id,
                    PlayerBoard.puuid == BoardTrait.puuid,
                ),
            )
            .where(PlayerBoard.match_id.is_(None))
        )
        or 0
    )
    raw_item_metadata_missing = int(
        session.scalar(
            select(func.count())
            .select_from(UnitItem)
            .join(RawMatch, RawMatch.match_id == UnitItem.match_id)
            .outerjoin(
                ItemMetadata,
                and_(
                    ItemMetadata.patch == func.coalesce(RawMatch.patch, "unknown"),
                    ItemMetadata.tft_set_number
                    == func.coalesce(RawMatch.tft_set_number, 0),
                    ItemMetadata.item_api_name == UnitItem.item_api_name,
                ),
            )
            .where(
                or_(
                    UnitItem.item_api_name == "",
                    ItemMetadata.item_api_name.is_(None),
                )
            )
        )
        or 0
    )
    raw_item_metadata_mismatched = int(
        session.scalar(
            select(func.count())
            .select_from(UnitItem)
            .join(RawMatch, RawMatch.match_id == UnitItem.match_id)
            .join(
                ItemMetadata,
                and_(
                    ItemMetadata.patch == func.coalesce(RawMatch.patch, "unknown"),
                    ItemMetadata.tft_set_number
                    == func.coalesce(RawMatch.tft_set_number, 0),
                    ItemMetadata.item_api_name == UnitItem.item_api_name,
                ),
            )
            .where(ItemMetadata.item_name != UnitItem.item_name)
        )
        or 0
    )
    fact_unit_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardUnit)
            .outerjoin(
                AnalysisBoard,
                and_(
                    AnalysisBoard.scope_id == AnalysisBoardUnit.scope_id,
                    AnalysisBoard.board_key == AnalysisBoardUnit.board_key,
                ),
            )
            .where(AnalysisBoard.board_key.is_(None))
        )
        or 0
    )
    fact_unit_list_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardUnitList)
            .outerjoin(
                AnalysisBoard,
                and_(
                    AnalysisBoard.scope_id == AnalysisBoardUnitList.scope_id,
                    AnalysisBoard.board_key == AnalysisBoardUnitList.board_key,
                ),
            )
            .where(AnalysisBoard.board_key.is_(None))
        )
        or 0
    )
    fact_trait_list_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardTraitList)
            .outerjoin(
                AnalysisBoard,
                and_(
                    AnalysisBoard.scope_id == AnalysisBoardTraitList.scope_id,
                    AnalysisBoard.board_key == AnalysisBoardTraitList.board_key,
                ),
            )
            .where(AnalysisBoard.board_key.is_(None))
        )
        or 0
    )
    fact_item_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardItem)
            .outerjoin(
                AnalysisBoardUnit,
                and_(
                    AnalysisBoardUnit.scope_id == AnalysisBoardItem.scope_id,
                    AnalysisBoardUnit.board_key == AnalysisBoardItem.board_key,
                    AnalysisBoardUnit.unit_idx == AnalysisBoardItem.unit_idx,
                ),
            )
            .where(AnalysisBoardUnit.board_key.is_(None))
        )
        or 0
    )
    fact_trait_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardTrait)
            .outerjoin(
                AnalysisBoard,
                and_(
                    AnalysisBoard.scope_id == AnalysisBoardTrait.scope_id,
                    AnalysisBoard.board_key == AnalysisBoardTrait.board_key,
                ),
            )
            .where(AnalysisBoard.board_key.is_(None))
        )
        or 0
    )

    scope_rows: list[dict[str, Any]] = []
    for scope in session.scalars(select(AnalysisScope).order_by(AnalysisScope.scope_id)):
        fact_build = session.get(AnalysisFactBuild, scope.scope_id)
        raw_count = int(
            session.scalar(
                select(func.count()).select_from(RawMatch).where(
                    RawMatch.patch == scope.patch,
                    RawMatch.queue_id == scope.queue_id,
                    func.coalesce(RawMatch.tft_set_number, 0)
                    == scope.tft_set_number,
                )
            )
            or 0
        )
        processed = int(
            session.scalar(
                select(func.count()).select_from(AnalysisProcessedMatch).where(
                    AnalysisProcessedMatch.scope_id == scope.scope_id
                )
            )
            or 0
        )
        scope_rows.append(
            {
                "scope_id": scope.scope_id,
                "patch": scope.patch,
                "queue_id": scope.queue_id,
                "tft_set_number": scope.tft_set_number,
                "status": scope.status,
                "is_active": scope.is_active,
                "universe_boards": int(scope.universe_boards),
                "raw_matches": raw_count,
                "processed_matches": processed,
                "processed_match_lag": raw_count - processed,
                "unit_list_rows": int(
                    session.scalar(
                        select(func.count())
                        .select_from(AnalysisBoardUnitList)
                        .where(AnalysisBoardUnitList.scope_id == scope.scope_id)
                    )
                    or 0
                ),
                "trait_list_rows": int(
                    session.scalar(
                        select(func.count())
                        .select_from(AnalysisBoardTraitList)
                        .where(AnalysisBoardTraitList.scope_id == scope.scope_id)
                    )
                    or 0
                ),
                "fact_build": None
                if fact_build is None
                else {
                    "schema_version": fact_build.schema_version,
                    "status": fact_build.status,
                    "processed_matches": int(fact_build.processed_match_count),
                    "lobbies": int(fact_build.lobby_count),
                    "boards": int(fact_build.board_count),
                    "units": int(fact_build.unit_count),
                    "items": int(fact_build.item_count),
                    "traits": int(fact_build.trait_count),
                },
            }
        )
    return {
        "foreign_keys": fk_counts,
        "missing_foreign_keys": missing_fks,
        "unvalidated_foreign_keys": unvalidated_foreign_keys,
        "orphans": {
            "player_boards": board_orphans,
            "board_units": unit_orphans,
            "unit_items": item_orphans,
            "board_traits": trait_orphans,
        },
        "analysis_orphans": {
            "analysis_board_unit_lists": fact_unit_list_orphans,
            "analysis_board_trait_lists": fact_trait_list_orphans,
            "analysis_board_units": fact_unit_orphans,
            "analysis_board_items": fact_item_orphans,
            "analysis_board_traits": fact_trait_orphans,
        },
        "item_metadata": {
            "raw_missing": raw_item_metadata_missing,
            "raw_mismatched": raw_item_metadata_mismatched,
        },
        "scopes": scope_rows,
    }


# Preserve the migration script's historical public name for direct imports.
validate_v2 = validate_relational_v2


def validate_patch_publication(
    session: Session,
    *,
    source_counts: Mapping[str, int],
    patch: str,
    queue_id: int,
    tft_set_number: int,
    analytics_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Validate one rebuilt target and raise if it is not serving-ready."""
    target_counts = {
        model.__tablename__: _count(session, model) for model in RAW_GRAPH_MODELS
    }
    relational = validate_relational_v2(session)
    scoped_raw_matches = int(
        session.scalar(
            select(func.count()).select_from(RawMatch).where(
                RawMatch.patch == patch,
                RawMatch.queue_id == queue_id,
                func.coalesce(RawMatch.tft_set_number, 0) == tft_set_number,
            )
        )
        or 0
    )
    board_count = _count(session, PlayerBoard)
    projection_count = _count(session, Match)
    active_scopes = [row for row in relational["scopes"] if row["is_active"]]
    active_scope = active_scopes[0] if len(active_scopes) == 1 else None

    validation: dict[str, Any] = {
        "source_raw_counts": dict(source_counts),
        "target_raw_counts": target_counts,
        "raw_counts_match": dict(source_counts) == target_counts,
        "scoped_raw_matches": scoped_raw_matches,
        "out_of_scope_raw_matches": target_counts["raw_matches"] - scoped_raw_matches,
        "relational": relational,
        "active_scope": active_scope,
        "projection": {
            "matches": projection_count,
            "player_boards": board_count,
            "universe_boards": (
                int(active_scope["universe_boards"]) if active_scope is not None else None
            ),
        },
        "analytics_counts": dict(analytics_counts or {}),
    }
    errors: list[str] = []
    if not validation["raw_counts_match"]:
        errors.append("source and target raw-graph counts differ")
    if validation["out_of_scope_raw_matches"] != 0:
        errors.append("target contains raw matches outside the configured scope")
    if relational["missing_foreign_keys"]:
        errors.append("target schema is missing normalized foreign keys")
    if relational["unvalidated_foreign_keys"]:
        errors.append("target schema has unvalidated foreign keys")
    if any(relational["orphans"].values()):
        errors.append("target normalized graph contains orphan rows")
    if any(relational["analysis_orphans"].values()):
        errors.append("target analytical facts contain orphan rows")
    if any(relational["item_metadata"].values()):
        errors.append("target raw items have missing or mismatched metadata")
    if len(relational["scopes"]) != 1 or len(active_scopes) != 1:
        errors.append("target must contain exactly one active analysis scope")
    elif (
        active_scope["patch"] != patch
        or active_scope["queue_id"] != queue_id
        or active_scope["tft_set_number"] != tft_set_number
        or active_scope["status"] != "ready"
    ):
        errors.append("active analysis scope identity or status is incorrect")
    if active_scope is None or active_scope["processed_match_lag"] != 0:
        errors.append("active analysis scope has processed-match lag")
    fact_build = active_scope.get("fact_build") if active_scope is not None else None
    if (
        fact_build is None
        or fact_build["status"] != "ready"
        or int(fact_build["schema_version"]) != ANALYSIS_FACT_SCHEMA_VERSION
        or int(fact_build["processed_matches"]) != scoped_raw_matches
        or int(fact_build["boards"]) != board_count
        or int(fact_build["units"]) != target_counts["board_units"]
        or int(fact_build["items"]) != target_counts["unit_items"]
        or int(fact_build["traits"]) != target_counts["board_traits"]
        or int(active_scope["unit_list_rows"]) != board_count
        or int(active_scope["trait_list_rows"]) != board_count
    ):
        errors.append("active anonymous fact build is not ready or current")
    if projection_count != board_count:
        errors.append("compatibility matches projection does not match scope boards")
    if active_scope is None or int(active_scope["universe_boards"]) != board_count:
        errors.append("active scope universe-board count does not match scope boards")
    if analytics_counts is not None and (
        int(analytics_counts.get("matches", -1)) != projection_count
        or int(analytics_counts.get("boards", -1)) != board_count
        or int(analytics_counts.get("processed_matches", -1))
        != scoped_raw_matches
    ):
        errors.append("analytics rebuild counts do not match the published scope")

    if errors:
        validation["errors"] = errors
        raise PublicationValidationError(errors, validation)
    validation["errors"] = []
    return validation


__all__ = [
    "PublicationValidationError",
    "validate_patch_publication",
    "validate_relational_v2",
    "validate_v2",
]
