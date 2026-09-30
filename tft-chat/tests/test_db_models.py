"""Tests for the database model package boundaries and public catalogue."""

from __future__ import annotations

from db.models import (
    ANALYSIS_MODELS,
    COMPOSITION_MODELS,
    WORKSPACE_MODELS,
    LEGACY_MODELS,
    RAW_GRAPH_MODELS,
    RUNTIME_MODELS,
    TABLE_MODELS,
    AnalysisBoardTraitList,
    AnalysisBoardUnitList,
    Match,
    SET_17_TRAIT_COLUMNS,
    SET_17_UNIT_COLUMNS,
)
from db.models.analysis import PRIVATE_ANALYSIS_MODELS
from db.models.query_tables import QUERY_TABLE_MODELS


def test_model_catalogues_preserve_architectural_boundaries() -> None:
    """Keep runtime catalogues aligned with package groups."""
    assert ANALYSIS_MODELS == (*PRIVATE_ANALYSIS_MODELS, *QUERY_TABLE_MODELS)
    assert RUNTIME_MODELS == (
        *RAW_GRAPH_MODELS, *ANALYSIS_MODELS, *COMPOSITION_MODELS, *WORKSPACE_MODELS, Match,
    )


def test_table_catalogue_includes_each_mapping_once() -> None:
    """Expose every current and retained table through the maintenance catalogue."""
    expected_models = (*RAW_GRAPH_MODELS, *ANALYSIS_MODELS, *LEGACY_MODELS)

    assert tuple(TABLE_MODELS.values()) == expected_models
    assert len(TABLE_MODELS) == len(expected_models)


def test_set_17_wide_tables_have_every_feature_column() -> None:
    """Keep the set-specific unit and trait schemas aligned with their rosters."""
    identity_columns = {"scope_id", "board_key"}

    unit_columns = {
        column.name for column in AnalysisBoardUnitList.__table__.columns
    }
    trait_columns = {
        column.name for column in AnalysisBoardTraitList.__table__.columns
    }

    assert unit_columns - identity_columns == set(SET_17_UNIT_COLUMNS.values())
    assert trait_columns - identity_columns == set(SET_17_TRAIT_COLUMNS.values())
    assert len(SET_17_UNIT_COLUMNS) == 82
    assert len(SET_17_TRAIT_COLUMNS) == 37
