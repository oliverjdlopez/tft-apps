"""Bounded cohort DSL and SQLAlchemy compiler over anonymous board facts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_

from db.models import AnalysisBoard
from .models import FilterGroup
from .utils import (
    active_fact_scope,
    bounded_clauses,
    item_condition_clauses,
    trait_condition_clauses,
    unit_condition_clauses,
)


def compile_filter_group(group: FilterGroup, board: Any = AnalysisBoard) -> Any:
    """Compile one filter group to a board-grain SQL expression.

    Args:
        group: Validated all-of filter group.
        board: Anonymous board-fact model or alias.

    Returns:
        SQLAlchemy expression requiring every populated filter.
    """
    clauses = unit_condition_clauses(group.unit_conditions or [], board)
    clauses.extend(item_condition_clauses(group.item_conditions or [], board))
    clauses.extend(trait_condition_clauses(group.trait_conditions or [], board))
    if group.level is not None:
        clauses.append(board.level == group.level)
    clauses.extend(bounded_clauses(board.level, group.min_level, group.max_level))
    return and_(*clauses)


FULL_REBUILD_REQUIRED = (
    "Anonymous cohort facts are not ready for the active analysis scope; "
    "run a full tft-rebuild-tables rebuild first."
)


__all__ = [
    "FULL_REBUILD_REQUIRED",
    "active_fact_scope",
    "compile_filter_group",
]
