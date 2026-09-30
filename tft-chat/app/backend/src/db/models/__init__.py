"""Public catalogue of relational TFT match and analytics ORM models.

The package groups mappings by architectural role while retaining the former
``db.models`` import surface for application, maintenance, and test callers.
"""

from __future__ import annotations

from .analysis import (
    ANALYSIS_FACT_SCHEMA_VERSION,
    PRIVATE_ANALYSIS_MODELS,
    AnalysisBoard,
    AnalysisBoardItem,
    AnalysisBoardTrait,
    AnalysisBoardTraitList,
    AnalysisBoardUnit,
    AnalysisBoardUnitList,
    AnalysisFactBuild,
    AnalysisProcessedMatch,
    AnalysisScope,
    SET_17_TRAIT_COLUMNS,
    SET_17_UNIT_COLUMNS,
)
from .base import Base, TextArray, metadata, utc_now
from .compositions import (
    COMPOSITION_MODELS,
    CompositionSnapshot,
    CompositionSnapshotSummary,
    CompositionExperiment,
)
from .legacy import (
    LEGACY_MODELS,
    AllMatch,
    LegacyPlayerBoard,
    LegacyPlayerItem,
    LegacyPlayerUnit,
    Match,
)
from .query_tables import (
    ALL_STARS,
    ALL_TRAIT_TIERS,
    ITEM_OVERALL_UNIT_NAME,
    QUERY_TABLE_MODELS,
    ItemStatQueryTable,
    TraitStatQueryTable,
    UnitLoadoutStatQueryTable,
    UnitStatQueryTable,
)
from .workspaces import WORKSPACE_MODELS, DevFlowchartGroup, DevWorkspace
from .raw import (
    RAW_GRAPH_MODELS,
    BoardTrait,
    BoardUnit,
    ItemMetadata,
    PlayerBoard,
    PlayerItem,
    PlayerUnit,
    RawMatch,
    UnitItem,
)

ANALYSIS_MODELS = (*PRIVATE_ANALYSIS_MODELS, *QUERY_TABLE_MODELS)
RUNTIME_MODELS = (
    *RAW_GRAPH_MODELS, *ANALYSIS_MODELS, *COMPOSITION_MODELS, *WORKSPACE_MODELS, Match,
)

TABLE_MODELS: dict[str, type[Base]] = {
    model.__tablename__: model
    for model in (*RAW_GRAPH_MODELS, *ANALYSIS_MODELS, *LEGACY_MODELS)
}

__all__ = [
    "COMPOSITION_MODELS",
    "CompositionSnapshot",
    "CompositionSnapshotSummary",
    "CompositionExperiment",
    "DevFlowchartGroup",
    "DevWorkspace",
    "WORKSPACE_MODELS",
    "ANALYSIS_FACT_SCHEMA_VERSION",
    "ALL_STARS",
    "ALL_TRAIT_TIERS",
    "ANALYSIS_MODELS",
    "AllMatch",
    "AnalysisBoard",
    "AnalysisBoardItem",
    "AnalysisBoardTrait",
    "AnalysisBoardTraitList",
    "AnalysisBoardUnit",
    "AnalysisBoardUnitList",
    "AnalysisFactBuild",
    "AnalysisProcessedMatch",
    "AnalysisScope",
    "Base",
    "BoardTrait",
    "BoardUnit",
    "ITEM_OVERALL_UNIT_NAME",
    "ItemMetadata",
    "ItemStatQueryTable",
    "LEGACY_MODELS",
    "LegacyPlayerBoard",
    "LegacyPlayerItem",
    "LegacyPlayerUnit",
    "Match",
    "PlayerBoard",
    "PlayerItem",
    "PlayerUnit",
    "PRIVATE_ANALYSIS_MODELS",
    "QUERY_TABLE_MODELS",
    "RAW_GRAPH_MODELS",
    "RUNTIME_MODELS",
    "RawMatch",
    "SET_17_TRAIT_COLUMNS",
    "SET_17_UNIT_COLUMNS",
    "TABLE_MODELS",
    "TextArray",
    "TraitStatQueryTable",
    "UnitItem",
    "UnitLoadoutStatQueryTable",
    "UnitStatQueryTable",
    "metadata",
    "utc_now",
]
