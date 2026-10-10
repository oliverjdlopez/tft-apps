"""Named implementation utilities for database-backed analysis tools."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
from importlib import import_module
from itertools import permutations
import logging
import os
import re
import time
from difflib import SequenceMatcher
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import and_, case, exists, func, literal, or_, select, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError, TimeoutError as PoolTimeoutError
from sqlalchemy.orm import aliased

from common.serialization import to_jsonable
from db.models import (
    ANALYSIS_FACT_SCHEMA_VERSION,
    AnalysisBoard,
    AnalysisFactBuild,
    AnalysisBoardItem,
    AnalysisBoardTrait,
    AnalysisBoardUnit,
    AnalysisScope,
    RawMatch,
)
from db.session import (
    AnalysisCallState,
    current_analysis_call,
    open_db,
    pool_state,
    reset_analysis_call,
    set_analysis_call,
)

if TYPE_CHECKING:
    from agents.tool_context import ToolContext


# =============================================================================
# Helpers belonging to models.py
# These validators stay dependency-free so Pydantic model construction can
# import them without pulling query modules into the schema layer.
# Keep future model-only helpers in this section of the shared utility module.
# =============================================================================


def validate_range(minimum: Any, maximum: Any, label: str) -> None:
    """Reject a range whose minimum exceeds its maximum.

    Args:
        minimum: Optional lower bound.
        maximum: Optional upper bound.
        label: Human-readable range name used in validation errors.

    Raises:
        ValueError: If both bounds exist and the minimum is greater.
    """
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"Minimum {label} cannot exceed maximum {label}.")


def has_filter_group_predicates(group: Any) -> bool:
    """Report whether a filter group contains any supported predicate.

    Args:
        group: Filter group to inspect.

    Returns:
        True when at least one structured entity or level filter is present.
    """
    return any(
        getattr(group, name, None)
        for name in (
            "unit_conditions",
            "item_conditions",
            "trait_conditions",
            "level",
            "min_level",
            "max_level",
        )
    )


def count_filter_group_predicates(group: Any) -> int:
    """Count every leaf predicate in one filter group.

    Args:
        group: Filter group to inspect.

    Returns:
        Total bounded predicates, including populated level fields.
    """
    count = sum(
        len(getattr(group, name) or [])
        for name in (
            "unit_conditions",
            "item_conditions",
            "trait_conditions",
        )
    )
    count += sum(
        getattr(group, name, None) is not None
        for name in ("level", "min_level", "max_level")
    )
    return count


def describe_filter_group(group: Any) -> str:
    """Build a bounded human-readable description of a filter group.

    Args:
        group: Validated filter group.

    Returns:
        Compact description of the populated filters.
    """
    parts: list[str] = []
    for kind in ("unit_conditions", "item_conditions", "trait_conditions"):
        if values := getattr(group, kind, None):
            descriptions = "+".join(
                describe_entity_condition(value) for value in values
            )
            parts.append(f"{kind}={descriptions}")
    if (level := getattr(group, "level", None)) is not None:
        parts.append(f"level={level}")
    minimum = getattr(group, "min_level", None)
    maximum = getattr(group, "max_level", None)
    if minimum is not None or maximum is not None:
        parts.append(
            f"level_range={minimum if minimum is not None else '*'}"
            f"..{maximum if maximum is not None else '*'}"
        )
    return " ".join(parts)


def describe_entity_condition(condition: Any) -> str:
    """Describe every effective constraint in one entity condition.

    Default values are included because they affect cohort membership: unit
    and item conditions require at least one copy, while trait conditions
    require an active trait unless explicitly configured otherwise.

    Args:
        condition: Validated unit, item, or trait condition.

    Returns:
        Entity name followed by its effective non-null constraints.
    """
    values = condition.model_dump(exclude_none=True)
    name = values.pop("name")
    constraints = ",".join(
        f"{key}={str(value).lower() if isinstance(value, bool) else value}"
        for key, value in values.items()
    )
    return f"{name}[{constraints}]" if constraints else name


# =============================================================================
# Helpers belonging to cohort_query.py
# Keep small SQL-expression builders here so the purpose module remains focused
# on first-class cohort compilation operations.
# =============================================================================


def bounded_clauses(expression: Any, minimum: Any, maximum: Any) -> list[Any]:
    """Build inclusive SQLAlchemy clauses for optional numeric bounds.

    Args:
        expression: SQLAlchemy expression to constrain.
        minimum: Optional inclusive lower bound.
        maximum: Optional inclusive upper bound.

    Returns:
        Zero, one, or two SQLAlchemy comparison clauses.
    """
    clauses: list[Any] = []
    if minimum is not None:
        clauses.append(expression >= minimum)
    if maximum is not None:
        clauses.append(expression <= maximum)
    return clauses


def unit_condition_clauses(conditions: list[Any], board: Any) -> list[Any]:
    """Compile unit conditions into board-correlated count clauses.

    Args:
        conditions: Validated unit conditions to compile.
        board: Anonymous board-fact model or alias to correlate against.

    Returns:
        Inclusive copy-bound clauses for matching unit occurrences.
    """
    clauses: list[Any] = []
    for condition in conditions:
        unit = aliased(AnalysisBoardUnit)
        predicates = [
            unit.scope_id == board.scope_id,
            unit.board_key == board.board_key,
            unit.unit_name == condition.name,
        ]
        if condition.star_level is not None:
            predicates.append(unit.star_level == condition.star_level)
        predicates.extend(
            bounded_clauses(
                unit.completed_item_count,
                condition.min_completed_items,
                condition.max_completed_items,
            )
        )
        # Counting matching rows enforces copy bounds without widening the
        # outer board-grain query or exposing individual unit occurrences.
        copies = (
            select(func.count())
            .select_from(unit)
            .where(*predicates)
            .correlate(board)
            .scalar_subquery()
        )
        clauses.extend(
            bounded_clauses(
                copies,
                condition.min_copies,
                condition.max_copies,
            )
        )
    return clauses


def item_condition_clauses(conditions: list[Any], board: Any) -> list[Any]:
    """Compile item conditions into board-correlated count clauses.

    Args:
        conditions: Validated item conditions to compile.
        board: Anonymous board-fact model or alias to correlate against.

    Returns:
        Inclusive copy-bound clauses for exact item-holder occurrences.
    """
    clauses: list[Any] = []
    for condition in conditions:
        item = aliased(AnalysisBoardItem)
        unit = aliased(AnalysisBoardUnit)
        query = (
            select(func.count())
            .select_from(item)
            .join(
                unit,
                and_(
                    unit.scope_id == item.scope_id,
                    unit.board_key == item.board_key,
                    unit.unit_idx == item.unit_idx,
                ),
            )
            .where(
                item.scope_id == board.scope_id,
                item.board_key == board.board_key,
                item.item_name == condition.name,
            )
        )
        if condition.holder is not None:
            query = query.where(unit.unit_name == condition.holder)
        if condition.holder_star_level is not None:
            query = query.where(unit.star_level == condition.holder_star_level)
        copies = query.correlate(board).scalar_subquery()
        clauses.extend(
            bounded_clauses(
                copies,
                condition.min_copies,
                condition.max_copies,
            )
        )
    return clauses


def trait_tier_expression(style: Any) -> Any:
    """Translate stored activation styles into medal names for bounded queries.

    Args:
        style: SQL expression containing the Riot activation style.

    Returns:
        A SQL expression that preserves inactive and unrecognized styles as
        explicit labels instead of inferring a medal from a breakpoint index.
    """
    # These are Riot match styles persisted by ingestion. Community Dragon's
    # effect styles use a different numbering and must not be substituted.
    return case(
        {0: "Inactive", 1: "Bronze", 2: "Silver", 3: "Unique", 4: "Gold", 5: "Prismatic"},
        value=func.coalesce(style, 0),
        else_="Unknown",
    )


def trait_condition_clauses(conditions: list[Any], board: Any) -> list[Any]:
    """Compile trait conditions into board-correlated presence clauses.

    Args:
        conditions: Validated trait conditions to compile.
        board: Anonymous board-fact model or alias to correlate against.

    Returns:
        One existence clause covering activation, tier, style, and unit bounds.
    """
    clauses: list[Any] = []
    for condition in conditions:
        trait = aliased(AnalysisBoardTrait)
        predicates = [
            trait.scope_id == board.scope_id,
            trait.board_key == board.board_key,
            trait.trait_name == condition.name,
        ]
        if condition.active:
            # Activation requires both ingest signals; nulls represent inactive
            # data rather than an unknown active state.
            predicates.extend(
                (
                    func.coalesce(trait.style, 0) > 0,
                    func.coalesce(trait.tier_current, 0) > 0,
                )
            )
        else:
            predicates.append(
                or_(
                    func.coalesce(trait.style, 0) <= 0,
                    func.coalesce(trait.tier_current, 0) <= 0,
                )
            )
        if condition.tier is not None:
            predicates.append(trait_tier_expression(trait.style) == condition.tier)
        if condition.style is not None:
            predicates.append(trait.style == condition.style)
        if condition.total_tier is not None:
            predicates.append(trait.tier_total == condition.total_tier)
        predicates.extend(
            bounded_clauses(
                trait.num_units,
                condition.min_contributing_units,
                condition.max_contributing_units,
            )
        )
        clauses.append(exists().where(*predicates))
    return clauses


# =============================================================================
# Entity-delta helpers shared by deltas.py and ranking_tools.py
# Both public surfaces use one entity-agnostic aggregation pipeline so their
# placement baselines and privacy behavior cannot drift apart over time. The
# callers separately own cohort investigation and discovery ranking schemas.
# =============================================================================


def entity_delta_page(
    session: Any,
    *,
    scope_id: int,
    population_condition: Any,
    entity_kind: str,
    group_by: list[str],
    row_range: list[int],
    minimum_boards: int,
    entity_keys: list[tuple[Any, ...]] | None = None,
    held_item: str | None = None,
    required_items: list[str] | None = None,
) -> dict[str, Any]:
    """Build one bounded entity-delta page for a board population.

    The delta is the cohort's average placement with the entity minus its
    average without the entity. The relative delta is the entity's average
    placement inside the cohort minus its average outside the cohort. Entity
    rows and every baseline remain board-weighted, while item holds retain
    their separate instance count.

    Args:
        session: Worker-thread SQLAlchemy session.
        scope_id: Private active analysis scope identifier.
        population_condition: Compiled board-grain cohort predicate.
        entity_kind: One of ``unit``, ``item``, ``trait``, or
            ``unit_loadout``.
        group_by: Effective entity dimensions for the requested result grain.
        row_range: Zero-based, end-exclusive result slice.
        minimum_boards: Required public sample size for each returned row.
        entity_keys: Optional exact result-grain keys to retain.
        held_item: Optional item that each unit occurrence must hold.
        required_items: Optional items that each loadout must contain in
            distinct slots.

    Returns:
        Internal page plus its private cohort population size.

    Raises:
        ValueError: If ``entity_kind`` is unsupported.
    """
    population = (
        session.query(
            func.count(AnalysisBoard.board_key).label("boards"),
            func.sum(AnalysisBoard.placement).label("placement_sum"),
            func.count(AnalysisBoard.placement).label("outcome_count"),
        )
        .filter(
            AnalysisBoard.scope_id == scope_id,
            population_condition,
        )
        .one()
    )
    universe = int(population.boards or 0)
    cohort_placement_sum = float(population.placement_sum or 0)
    cohort_outcome_count = int(population.outcome_count or 0)
    start, end = row_range
    width = end - start
    if universe == 0 or cohort_outcome_count == 0:
        return {
            "results": [],
            "offset": start,
            "has_more": False,
            "population_boards": universe,
        }

    dimensions = list(group_by)
    presence_extras: list[Any]
    # Collapse duplicate entity occurrences to one board/entity grain before
    # outcome aggregation. Item holds are retained as a separate count because
    # duplicate copies must not overweight placement, top-four, or win rates.
    if entity_kind == "unit":
        unit = aliased(AnalysisBoardUnit)
        group_columns = [unit.scope_id, unit.board_key, unit.unit_name]
        selected_columns = [
            unit.scope_id.label("scope_id"),
            unit.board_key.label("board_key"),
            unit.unit_name.label("unit_name"),
        ]
        if "star_level" in dimensions:
            group_columns.append(unit.star_level)
            selected_columns.append(unit.star_level.label("star_level"))
        unit_conditions = [unit.scope_id == scope_id]
        if held_item is not None:
            unit_conditions.append(
                loadout_contains_items(
                    (unit.item_1, unit.item_2, unit.item_3),
                    [held_item],
                )
            )
        presence = (
            select(
                *selected_columns,
                func.max(unit.cost).label("cost"),
            )
            .where(*unit_conditions)
            .group_by(*group_columns)
            .subquery()
        )
        presence_extras = [func.max(presence.c.cost).label("cost")]
        sample_field = "games"
        frequency_field = "pick_rate"
    elif entity_kind == "item":
        item = aliased(AnalysisBoardItem)
        holder = aliased(AnalysisBoardUnit)
        group_columns = [item.scope_id, item.board_key, item.item_name]
        selected_columns = [
            item.scope_id.label("scope_id"),
            item.board_key.label("board_key"),
            item.item_name.label("item_name"),
        ]
        if "unit_name" in dimensions:
            group_columns.append(holder.unit_name)
            selected_columns.append(holder.unit_name.label("unit_name"))
        presence = (
            select(
                *selected_columns,
                func.count().label("holds"),
            )
            .select_from(item)
            .join(
                holder,
                and_(
                    holder.scope_id == item.scope_id,
                    holder.board_key == item.board_key,
                    holder.unit_idx == item.unit_idx,
                ),
            )
            .where(item.scope_id == scope_id)
            .group_by(*group_columns)
            .subquery()
        )
        presence_extras = [func.sum(presence.c.holds).label("holds")]
        sample_field = "boards"
        frequency_field = "pick_rate_per_board"
    elif entity_kind == "trait":
        trait = aliased(AnalysisBoardTrait)
        group_columns = [trait.scope_id, trait.board_key, trait.trait_name]
        selected_columns = [
            trait.scope_id.label("scope_id"),
            trait.board_key.label("board_key"),
            trait.trait_name.label("trait_name"),
        ]
        if "tier" in dimensions:
            medal = trait_tier_expression(trait.style)
            group_columns.append(medal)
            selected_columns.append(medal.label("tier"))
        presence = (
            select(*selected_columns)
            .where(
                trait.scope_id == scope_id,
                func.coalesce(trait.style, 0) > 0,
                func.coalesce(trait.tier_current, 0) > 0,
            )
            .group_by(*group_columns)
            .subquery()
        )
        presence_extras = []
        sample_field = "games"
        frequency_field = "pick_rate"
    elif entity_kind == "unit_loadout":
        unit = aliased(AnalysisBoardUnit)
        group_columns = [
            unit.scope_id,
            unit.board_key,
            unit.unit_name,
            unit.loadout_key,
        ]
        selected_columns = [
            unit.scope_id.label("scope_id"),
            unit.board_key.label("board_key"),
            unit.unit_name.label("unit_name"),
            unit.loadout_key.label("loadout_key"),
        ]
        if "star_level" in dimensions:
            group_columns.append(unit.star_level)
            selected_columns.append(unit.star_level.label("star_level"))
        loadout_conditions = [
            unit.scope_id == scope_id,
            unit.completed_item_count > 0,
        ]
        if required_items:
            loadout_conditions.append(
                loadout_contains_items(
                    (unit.item_1, unit.item_2, unit.item_3),
                    required_items,
                )
            )
        presence = (
            select(*selected_columns)
            .where(*loadout_conditions)
            .group_by(*group_columns)
            .subquery()
        )
        presence_extras = []
        sample_field = "boards"
        frequency_field = "loadout_pick_rate"
    else:
        raise ValueError(f"Unsupported entity delta kind: {entity_kind}")

    dimension_columns = [getattr(presence.c, name) for name in dimensions]
    avg_placement, top4_rate, win_rate = outcome_expressions(
        AnalysisBoard.placement
    )
    board_count = func.count()
    # Build reportable cohort rows first. The public floor applies to every
    # breakout row independently, even when the parent cohort is reportable.
    cohort_rows = (
        session.query(
            *(column.label(name) for name, column in zip(dimensions, dimension_columns)),
            *presence_extras,
            board_count.label(sample_field),
            avg_placement.label("avg_placement"),
            func.sum(AnalysisBoard.placement).label("placement_sum"),
            func.count(AnalysisBoard.placement).label("outcome_count"),
            top4_rate.label("top4_rate"),
            win_rate.label("win_rate"),
            (board_count * 1.0 / max(universe, 1)).label(frequency_field),
        )
        .select_from(AnalysisBoard)
        .join(
            presence,
            and_(
                presence.c.scope_id == AnalysisBoard.scope_id,
                presence.c.board_key == AnalysisBoard.board_key,
            ),
        )
        .filter(
            AnalysisBoard.scope_id == scope_id,
            population_condition,
        )
        .group_by(*dimension_columns)
        .having(board_count >= minimum_boards)
        .subquery()
    )
    overall_dimension_columns = [
        getattr(presence.c, name) for name in dimensions
    ]
    # The active-scope aggregate matches the exact requested entity grain; its
    # cohort contribution is subtracted to form the disjoint outside baseline.
    overall_rows = (
        session.query(
            *(
                column.label(name)
                for name, column in zip(dimensions, overall_dimension_columns)
            ),
            func.count().label("overall_boards"),
            func.sum(AnalysisBoard.placement).label("overall_placement_sum"),
            func.count(AnalysisBoard.placement).label("overall_outcome_count"),
        )
        .select_from(AnalysisBoard)
        .join(
            presence,
            and_(
                presence.c.scope_id == AnalysisBoard.scope_id,
                presence.c.board_key == AnalysisBoard.board_key,
            ),
        )
        .filter(AnalysisBoard.scope_id == scope_id)
        .group_by(*overall_dimension_columns)
        .subquery()
    )
    join_condition = and_(
        *(
            getattr(overall_rows.c, name) == getattr(cohort_rows.c, name)
            for name in dimensions
        )
    )
    extra_fields = (
        ["cost"]
        if entity_kind == "unit"
        else ["holds"]
        if entity_kind == "item"
        else []
    )
    cohort_without_entity_boards = (
        universe - getattr(cohort_rows.c, sample_field)
    )
    cohort_without_entity_outcomes = (
        cohort_outcome_count - cohort_rows.c.outcome_count
    )
    cohort_without_entity_avg = (
        (cohort_placement_sum - cohort_rows.c.placement_sum)
        * 1.0
        / func.nullif(cohort_without_entity_outcomes, 0)
    )
    cohort_comparison_reportable = (
        cohort_without_entity_boards >= minimum_boards
    )
    public_cohort_without_entity_boards = case(
        (cohort_without_entity_boards == 0, 0),
        (cohort_comparison_reportable, cohort_without_entity_boards),
        else_=None,
    )
    public_cohort_without_entity_avg = case(
        (cohort_comparison_reportable, cohort_without_entity_avg),
        else_=None,
    )
    entity_outside_cohort_boards = (
        overall_rows.c.overall_boards - getattr(cohort_rows.c, sample_field)
    )
    entity_outside_cohort_outcomes = (
        overall_rows.c.overall_outcome_count - cohort_rows.c.outcome_count
    )
    entity_outside_cohort_avg = (
        (
            overall_rows.c.overall_placement_sum
            - cohort_rows.c.placement_sum
        )
        * 1.0
        / func.nullif(entity_outside_cohort_outcomes, 0)
    )
    relative_comparison_reportable = (
        entity_outside_cohort_boards >= minimum_boards
    )
    public_entity_outside_cohort_boards = case(
        (entity_outside_cohort_boards == 0, 0),
        (relative_comparison_reportable, entity_outside_cohort_boards),
        else_=None,
    )
    public_entity_outside_cohort_avg = case(
        (relative_comparison_reportable, entity_outside_cohort_avg),
        else_=None,
    )
    result_fields = [
        *dimensions,
        *extra_fields,
        sample_field,
        "avg_placement",
        "cohort_without_entity_boards",
        "cohort_without_entity_avg_placement",
        "delta",
        "entity_outside_cohort_boards",
        "entity_outside_cohort_avg_placement",
        "relative_delta",
        "top4_rate",
        "win_rate",
        frequency_field,
    ]
    # Both deltas are calculated from disjoint board samples in SQL so their
    # cohort membership and weighting cannot drift during serialization.
    query = session.query(
        *(getattr(cohort_rows.c, name).label(name) for name in dimensions),
        *(getattr(cohort_rows.c, name).label(name) for name in extra_fields),
        getattr(cohort_rows.c, sample_field).label(sample_field),
        cohort_rows.c.avg_placement.label("avg_placement"),
        public_cohort_without_entity_boards.label(
            "cohort_without_entity_boards"
        ),
        public_cohort_without_entity_avg.label(
            "cohort_without_entity_avg_placement"
        ),
        case(
            (
                cohort_comparison_reportable,
                cohort_rows.c.avg_placement - cohort_without_entity_avg,
            ),
            else_=None,
        ).label("delta"),
        public_entity_outside_cohort_boards.label(
            "entity_outside_cohort_boards"
        ),
        public_entity_outside_cohort_avg.label(
            "entity_outside_cohort_avg_placement"
        ),
        case(
            (
                relative_comparison_reportable,
                cohort_rows.c.avg_placement - entity_outside_cohort_avg,
            ),
            else_=None,
        ).label("relative_delta"),
        cohort_rows.c.top4_rate.label("top4_rate"),
        cohort_rows.c.win_rate.label("win_rate"),
        getattr(cohort_rows.c, frequency_field).label(frequency_field),
    ).join(overall_rows, join_condition)
    if entity_keys:
        query = query.filter(
            or_(
                *(
                    and_(
                        *(
                            getattr(cohort_rows.c, name) == value
                            for name, value in zip(dimensions, key)
                        )
                    )
                    for key in entity_keys
                )
            )
        )
    ordering = [
        getattr(cohort_rows.c, sample_field).desc(),
        *(getattr(cohort_rows.c, name).asc() for name in dimensions),
    ]
    found = query.order_by(*ordering).offset(start).limit(width + 1).all()
    return {
        "results": [
            {name: result_cell(getattr(row, name)) for name in result_fields}
            for row in found[:width]
        ],
        "offset": start,
        "has_more": len(found) > width,
        "population_boards": universe,
    }


MIN_PUBLIC_BOARDS = 50
TOOL_TIMEOUT_SECONDS = 30.0
ANALYSIS_STATEMENT_TIMEOUT_MS = 40_000
# The image's source directory is read-only; diagnostic state has its own mount.
RANKING_LOG_PATH = (
    Path(os.environ["XDG_STATE_HOME"]) / "tft-chat" / "ranking_tools.log"
    if os.environ.get("XDG_STATE_HOME") else Path(__file__).with_name("ranking_tools.log")
)
if os.environ.get("XDG_STATE_HOME"):
    RANKING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
_DB_TOOL_EXECUTOR = ThreadPoolExecutor(thread_name_prefix="tft-db-tool")
db_logger = logging.getLogger("tft.analysis.db")
ranking_logger = logging.getLogger("tft.analysis.ranking_tools")
ranking_logger.setLevel(logging.DEBUG)
ranking_logger.propagate = False
# Module reloads and test imports may execute this block repeatedly. Reuse the
# existing file handler so each event is written once, and delay opening the
# log until the first event until the first event; only the state directory is prepared at import.
if not any(
    isinstance(handler, RotatingFileHandler)
    and Path(handler.baseFilename) == RANKING_LOG_PATH
    for handler in ranking_logger.handlers
):
    ranking_log_handler = RotatingFileHandler(
        RANKING_LOG_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
        delay=True,
    )
    ranking_log_handler.setLevel(logging.DEBUG)
    ranking_log_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    ranking_logger.addHandler(ranking_log_handler)


def minimum_public_boards() -> int:
    """Return the active public sample-suppression threshold.

    Returns:
        Minimum reportable anonymous-board sample.
    """
    return MIN_PUBLIC_BOARDS


def analysis_warning(code: str, message: str) -> dict[str, str]:
    """Build one validated structured investigation warning.

    Args:
        code: Stable machine-readable warning code.
        message: Concise model-facing interpretation guidance.

    Returns:
        JSON-compatible warning object.
    """
    model = import_module(f"{__package__}.models").AnalysisWarning
    return model(code=code, message=message).model_dump(mode="json")


def analysis_error(
    code: str,
    message: str,
    *,
    retryable: bool,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Build one validated error result in the investigation contract.

    Args:
        code: Stable machine-readable failure code.
        message: Bounded model-facing failure description.
        retryable: Whether retrying the same investigation may succeed.
        timeout_seconds: Optional timeout associated with the failure.

    Returns:
        JSON-compatible error result.
    """
    model = import_module(f"{__package__}.models").AnalysisErrorResult
    return model(
        error={
            "code": code,
            "message": message,
            "retryable": retryable,
            "timeout_seconds": timeout_seconds,
        }
    ).model_dump(mode="json", exclude_none=True)


def analysis_table_result(
    page: dict[str, Any],
    *,
    population: str,
    population_boards: int | None,
    group_by: list[str],
    sort_by: str,
    sort_direction: str,
    warnings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Wrap one internal page in the validated tabular result contract.

    Args:
        page: Internal page containing results, offset, and continuation state.
        population: Human-readable population description.
        population_boards: Reportable population size, or None when suppressed.
        group_by: Effective row-grain dimensions.
        sort_by: Effective primary sort metric.
        sort_direction: Explicit or automatic requested direction.
        warnings: Optional structured interpretation warnings.

    Returns:
        JSON-compatible table result.
    """
    model = import_module(f"{__package__}.models").AnalysisTableResult
    direction = (
        "asc"
        if sort_direction == "asc"
        or (sort_direction == "auto" and sort_by == "avg_placement")
        else "desc"
    )
    result_warnings = list(warnings or [])
    if not page["results"] and not any(
        warning.get("code") == "no_results" for warning in result_warnings
    ):
        result_warnings.append(
            analysis_warning(
                "no_results",
                "No reportable rows matched the requested filters and page.",
            )
        )
    return model(
        context={
            "population": population,
            "population_boards": population_boards,
            "group_by": group_by,
            "sort": [{"metric": sort_by, "direction": direction}],
            "minimum_reportable_boards": MIN_PUBLIC_BOARDS,
        },
        # SQL aggregate expressions commonly return Decimal values. Convert
        # them before validation because the result rows are deliberately
        # typed as Any and Pydantic otherwise serializes those leaves as text.
        results=to_jsonable(page["results"]),
        page={
            "offset": page["offset"],
            "count": len(page["results"]),
            "has_more": page["has_more"],
        },
        warnings=result_warnings,
    ).model_dump(mode="json")


def analysis_resolution_result(
    entries: list[dict[str, Any]],
    *,
    warnings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a validated stored-name resolution result.

    Args:
        entries: One bounded resolution entry per submitted query.
        warnings: Optional structured interpretation warnings.

    Returns:
        JSON-compatible resolution result.
    """
    model = import_module(f"{__package__}.models").AnalysisResolutionResult
    return model(
        context={"minimum_reportable_boards": MIN_PUBLIC_BOARDS},
        results=entries,
        warnings=warnings or [],
    ).model_dump(mode="json")


def population_table_result(
    page: dict[str, Any],
    *,
    population_group: Any | None = None,
    population: str | None = None,
    population_boards: int,
    group_by: list[str],
    sort_by: str,
    sort_direction: str,
    warnings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a table result while enforcing population-count suppression.

    Args:
        page: Internal bounded page.
        population_group: Optional validated cohort filter group.
        population: Optional explicit population description for non-cohort
            ranking conditions.
        population_boards: Private population size used for suppression.
        group_by: Effective result dimensions.
        sort_by: Effective primary sort metric.
        sort_direction: Requested primary sort direction.
        warnings: Optional pre-existing structured warnings.

    Returns:
        JSON-compatible table result with no sub-threshold count disclosure.
    """
    result_warnings = list(warnings or [])
    reportable_boards: int | None = population_boards
    if 0 < population_boards < MIN_PUBLIC_BOARDS:
        reportable_boards = None
        result_warnings.append(
            analysis_warning(
                "population_suppressed",
                f"The population contains fewer than {MIN_PUBLIC_BOARDS} boards; "
                "its exact size is suppressed.",
            )
        )
    if population is not None and population_group is not None:
        raise ValueError("Provide either population or population_group, not both.")
    return analysis_table_result(
        page,
        population=(
            population
            or (
                describe_filter_group(population_group)
                if population_group is not None
                else "active analysis scope"
            )
        ),
        population_boards=reportable_boards,
        group_by=group_by,
        sort_by=sort_by,
        sort_direction=sort_direction,
        warnings=result_warnings,
    )


async def run_db_tool(
    ctx: ToolContext[Any],
    operation: Any,
    *,
    log_ranking: bool = False,
) -> dict[str, Any]:
    """Execute one complete read-only database tool operation.

    This is the single execution boundary for model-facing database tools. It
    owns call metadata, worker-thread dispatch, the session and transaction,
    database error translation, cancellation, and optional ranking lifecycle
    diagnostics before invoking the supplied operation exactly once.

    Args:
        ctx: Agents SDK tool context containing tool and call identifiers.
        operation: Synchronous tool operation that receives one database session.
        log_ranking: Whether to emit structured-ranking lifecycle diagnostics.

    Returns:
        The callback's JSON-compatible result.
    """
    state = AnalysisCallState(
        tool=ctx.tool_name,
        call_id=ctx.tool_call_id or uuid4().hex,
    )
    token = set_analysis_call(state)

    def execute() -> dict[str, Any]:
        """Open the read-only session and execute the tool operation.

        Returns:
            The operation result or a bounded retryable database error.
        """
        session = None
        outcome = "success"
        ranking_started_at: float | None = None
        try:
            state.acquire_started_at = time.monotonic()
            session = open_db()
            connection = session.connection()
            if getattr(connection.dialect, "name", None) == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(
                    text(
                        f"SET LOCAL statement_timeout = "
                        f"{ANALYSIS_STATEMENT_TIMEOUT_MS}"
                    )
                )
            state.query_started_at = time.monotonic()
            ranking_started_at = state.query_started_at
            if log_ranking:
                debug_ranking_event("ranking_start")
            try:
                result = operation(session)
            except Exception as exc:
                if log_ranking:
                    debug_ranking_event(
                        "ranking_error",
                        elapsed_ms=round(
                            (time.monotonic() - ranking_started_at) * 1000,
                            3,
                        ),
                        error_type=type(exc).__name__,
                    )
                raise
            state.query_finished_at = time.monotonic()
            if log_ranking:
                debug_ranking_event(
                    "ranking_complete",
                    elapsed_ms=round(
                        (state.query_finished_at - ranking_started_at) * 1000,
                        3,
                    ),
                    result_count=(result.get("page") or {}).get("count"),
                    returned_error=result.get("kind") == "error",
                )
            if state.cancellation_requested:
                outcome = "cancellation"
            elif state.outcome_override is not None:
                outcome = state.outcome_override
            return result
        except PoolTimeoutError:
            outcome = "pool_timeout"
            db_logger.info(
                "analysis_pool %s",
                json.dumps(
                    {
                        "event": "checkout_failure",
                        "tool": state.tool,
                        "call_id": state.call_id,
                        "reason": "pool_timeout",
                    },
                    sort_keys=True,
                ),
            )
            return analysis_error(
                "database_pool_timeout",
                "Database connection pool checkout timed out; retry the analysis.",
                retryable=True,
                timeout_seconds=5,
            )
        except DBAPIError as exc:
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            if sqlstate == "57014":
                outcome = "database_timeout"
                return analysis_error(
                    "database_timeout",
                    "Database query exceeded the analysis statement timeout.",
                    retryable=True,
                    timeout_seconds=ANALYSIS_STATEMENT_TIMEOUT_MS / 1000,
                )
            outcome = "database_error"
            return analysis_error(
                "database_error",
                "Database analysis failed.",
                retryable=True,
            )
        except SQLAlchemyError:
            outcome = "database_error"
            return analysis_error(
                "database_error",
                "Database analysis failed.",
                retryable=True,
            )
        except Exception:
            outcome = "other_error"
            raise
        finally:
            if session is not None:
                try:
                    session.rollback()
                finally:
                    session.close()
            now = time.monotonic()
            query_start = state.query_started_at
            query_end = state.query_finished_at or now
            bind = getattr(session, "bind", None) if session is not None else None
            snapshot = (
                pool_state(bind)
                if bind is not None
                else {
                    "size": None,
                    "checked_out": None,
                    "overflow": None,
                    "available": None,
                }
            )
            payload = {
                "event": "complete",
                "tool": state.tool,
                "call_id": state.call_id,
                "outcome": outcome,
                "acquisition_ms": round(
                    max(
                        0.0,
                        (
                            (state.acquired_at or now)
                            - (state.acquire_started_at or state.started_at)
                        )
                        * 1000,
                    ),
                    3,
                ),
                "execution_ms": (
                    round(max(0.0, (query_end - query_start) * 1000), 3)
                    if query_start is not None
                    else 0.0
                ),
                "total_ms": round(
                    max(0.0, (now - state.started_at) * 1000),
                    3,
                ),
                "checkouts": state.checkouts,
                "checkins": state.checkins,
                **snapshot,
            }
            db_logger.info("analysis_db_call %s", json.dumps(payload, sort_keys=True))
            if state.checkouts != state.checkins:
                db_logger.warning(
                    "analysis_pool_unbalanced %s",
                    json.dumps(
                        {
                            "tool": state.tool,
                            "call_id": state.call_id,
                            "checkouts": state.checkouts,
                            "checkins": state.checkins,
                        },
                        sort_keys=True,
                    ),
                )

    try:
        loop = asyncio.get_running_loop()
        context = copy_context()
        task = loop.run_in_executor(_DB_TOOL_EXECUTOR, context.run, execute)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            state.cancellation_requested = True
            task.add_done_callback(
                lambda done: done.exception() if not done.cancelled() else None
            )
            return analysis_error(
                "cancelled",
                "Analysis call was cancelled before completion.",
                retryable=True,
                timeout_seconds=30,
            )
    finally:
        reset_analysis_call(token)


ENTITY_PREFIX_RE = re.compile(r"^tft\d*_(item_)?", re.IGNORECASE)


def normalize_name(value: str) -> str:
    """Normalize a TFT entity name for fuzzy comparison.

    Args:
        value: Stored or player-language name.

    Returns:
        Lowercase alphanumeric comparison form.
    """
    return re.sub(r"[^a-z0-9]", "", value.lower())


def strip_entity_prefix(value: str) -> str:
    """Remove the common TFT API prefix from a stored entity name.

    Args:
        value: Stored TFT entity identifier.

    Returns:
        Identifier without its set or item prefix.
    """
    return ENTITY_PREFIX_RE.sub("", value)


def match_score(query: str, candidate: str) -> tuple[float, str] | None:
    """Score a stored entity identifier against a player-language name.

    Args:
        query: Player-supplied name.
        candidate: Stored entity identifier.

    Returns:
        Match score and match kind, or None below the fuzzy threshold.
    """
    query_name = normalize_name(query)
    full_name = normalize_name(candidate)
    core_name = normalize_name(strip_entity_prefix(candidate))
    if not query_name or not full_name:
        return None
    if query_name in (full_name, core_name):
        return 1.0, "exact"
    if core_name.startswith(query_name) or query_name in full_name:
        return 0.9, "substring"
    ratio = max(
        SequenceMatcher(None, query_name, core_name).ratio(),
        SequenceMatcher(None, query_name, full_name).ratio(),
    )
    if ratio >= 0.72:
        return ratio, "fuzzy"
    return None


def active_scope_population(conn: Any) -> tuple[int, int] | None:
    """Return private identity and public population for the active scope.

    Args:
        conn: SQLAlchemy session.

    Returns:
        Scope identifier and universe-board count, or None when unavailable.
    """
    row = timed_call(
        lambda: conn.execute(
            select(AnalysisScope.scope_id, AnalysisScope.universe_boards).where(
                AnalysisScope.is_active.is_(True)
            )
        ).one_or_none(),
        stage="active_scope",
    )
    if row is None:
        return None
    return int(row.scope_id), int(row.universe_boards)


def debug_ranking_event(event: str, **details: Any) -> None:
    """Write one bounded structured-ranking diagnostic event.

    Args:
        event: Stable diagnostic event name.
        **details: JSON-compatible event details.
    """
    state = current_analysis_call()
    payload = {
        "event": event,
        "tool": state.tool if state is not None else None,
        "call_id": state.call_id if state is not None else None,
        **details,
    }
    ranking_logger.debug(json.dumps(payload, default=str, sort_keys=True))


def query_details(query: Any) -> tuple[str, dict[str, Any]]:
    """Render bounded SQL and bind values without database credentials.

    Args:
        query: SQLAlchemy query or statement.

    Returns:
        Truncated SQL text and bounded bind parameters.
    """
    statement = getattr(query, "statement", query)
    compiled = statement.compile()
    rendered = str(compiled)
    # Diagnostics must stay bounded because they run for every model-facing
    # query and may contain large IN-list bind values.
    sql = (
        rendered
        if len(rendered) <= 20_000
        else f"{rendered[:20_000]}...<truncated>"
    )
    parameters = {
        key: (
            value[:24]
            if isinstance(value, list)
            else value[:200]
            if isinstance(value, str)
            else value
        )
        for key, value in compiled.params.items()
    }
    return sql, parameters


def timed_all(query: Any, *, stage: str) -> list[Any]:
    """Execute ``query.all`` and log bounded timing diagnostics.

    Args:
        query: SQLAlchemy ORM query.
        stage: Diagnostic stage name.

    Returns:
        Materialized query rows.
    """
    started_at = time.monotonic()
    sql, parameters = query_details(query)
    debug_ranking_event("query_start", stage=stage, sql=sql, parameters=parameters)
    try:
        rows = query.all()
    except Exception as exc:
        debug_ranking_event(
            "query_error",
            stage=stage,
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 3),
            error_type=type(exc).__name__,
        )
        raise
    debug_ranking_event(
        "query_complete",
        stage=stage,
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 3),
        row_count=len(rows),
    )
    return rows


def timed_scalar(conn: Any, statement: Any, *, stage: str) -> Any:
    """Execute a scalar statement and log bounded timing diagnostics.

    Args:
        conn: SQLAlchemy session.
        statement: SQLAlchemy scalar statement.
        stage: Diagnostic stage name.

    Returns:
        Scalar result.
    """
    started_at = time.monotonic()
    sql, parameters = query_details(statement)
    debug_ranking_event("query_start", stage=stage, sql=sql, parameters=parameters)
    try:
        value = conn.scalar(statement)
    except Exception as exc:
        debug_ranking_event(
            "query_error",
            stage=stage,
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 3),
            error_type=type(exc).__name__,
        )
        raise
    debug_ranking_event(
        "query_complete",
        stage=stage,
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 3),
        has_value=value is not None,
    )
    return value


def timed_call(operation: Any, *, stage: str) -> Any:
    """Execute an arbitrary operation and log bounded timing diagnostics.

    Args:
        operation: Zero-argument callable.
        stage: Diagnostic stage name.

    Returns:
        Operation result.
    """
    started_at = time.monotonic()
    debug_ranking_event("operation_start", stage=stage)
    try:
        value = operation()
    except Exception as exc:
        debug_ranking_event(
            "operation_error",
            stage=stage,
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 3),
            error_type=type(exc).__name__,
        )
        raise
    debug_ranking_event(
        "operation_complete",
        stage=stage,
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 3),
        has_value=value is not None,
    )
    return value


def active_fact_scope(session: Any) -> AnalysisScope | None:
    """Return the active scope only when anonymous facts are current.

    Ranking and investigation tools share this readiness gate before reading
    the anonymous board-grain layer.

    Args:
        session: SQLAlchemy session.

    Returns:
        Ready active analysis scope, or None when a rebuild is required.
    """
    raw_match_count = (
        select(func.count())
        .select_from(RawMatch)
        .where(
            RawMatch.patch == AnalysisScope.patch,
            RawMatch.queue_id == AnalysisScope.queue_id,
            func.coalesce(RawMatch.tft_set_number, 0) == AnalysisScope.tft_set_number,
        )
        .correlate(AnalysisScope)
        .scalar_subquery()
    )
    # A ready marker alone becomes stale when new source matches arrive.
    return (
        session.query(AnalysisScope)
        .join(AnalysisFactBuild, AnalysisFactBuild.scope_id == AnalysisScope.scope_id)
        .filter(
            AnalysisScope.is_active.is_(True),
            AnalysisFactBuild.status == "ready",
            AnalysisFactBuild.schema_version == ANALYSIS_FACT_SCHEMA_VERSION,
            AnalysisFactBuild.processed_match_count == raw_match_count,
        )
        .one_or_none()
    )


def sample_bounds_error(
    min_sample: int | None,
    max_sample: int | None,
) -> dict[str, Any] | None:
    """Return a structured error for an inverted sample-size range.

    Args:
        min_sample: Optional lower sample-size bound.
        max_sample: Optional upper sample-size bound.

    Returns:
        Invalid-argument result when the bounds are inverted, otherwise None.
    """
    if (
        min_sample is not None
        and max_sample is not None
        and min_sample > max_sample
    ):
        return analysis_error(
            "invalid_arguments",
            "min_sample cannot exceed max_sample.",
            retryable=False,
        )
    return None


def apply_sample_bounds(
    query: Any,
    model: Any,
    min_sample: int | None,
    max_sample: int | None,
    *,
    sample_column: str,
) -> Any:
    """Apply the public floor and optional sample bounds to a query.

    Args:
        query: SQLAlchemy ORM query.
        model: Aggregate projection model.
        min_sample: Optional caller-requested minimum sample.
        max_sample: Optional caller-requested maximum sample.
        sample_column: Attribute holding the reportable sample.

    Returns:
        Constrained ORM query.
    """
    sample = getattr(model, sample_column)
    query = query.filter(sample >= max(MIN_PUBLIC_BOARDS, min_sample or 0))
    if max_sample is not None:
        query = query.filter(sample <= max_sample)
    return query


def order_columns(
    model: Any, sort_by: str, sort_direction: str, *tie_breakers: Any
) -> tuple[Any, ...]:
    """Build one primary aggregate ordering plus stable tie breakers.

    Args:
        model: Aggregate projection model or subquery columns.
        sort_by: Metric attribute name.
        sort_direction: Explicit direction or placement-aware automatic mode.
        *tie_breakers: Additional ordering expressions.

    Returns:
        SQLAlchemy ordering expressions.
    """
    column = getattr(model, sort_by)
    ascending = sort_direction == "asc" or (
        sort_direction == "auto" and sort_by == "avg_placement"
    )
    return ((column.asc() if ascending else column.desc()), *tie_breakers)


def validate_ranking_range(value: list[int]) -> list[int]:
    """Validate one zero-based, end-exclusive ranking slice.

    Args:
        value: Two integer indexes supplied by a ranking tool caller.

    Returns:
        The validated indexes unchanged.

    Raises:
        ValueError: If the end precedes the start or the slice exceeds the
            bounded 100-row response width.
    """
    start, end = value
    if end < start:
        raise ValueError("range end must be greater than or equal to its start")
    if end - start > 100:
        raise ValueError("range may request at most 100 rows")
    return value


def page_results(
    query: Any,
    fields: tuple[str, ...],
    ordering: tuple[Any, ...],
    row_range: list[int],
) -> dict[str, Any]:
    """Materialize one bounded aggregate result slice.

    Args:
        query: SQLAlchemy ORM query.
        fields: Returned row attributes.
        ordering: Deterministic ordering expressions.
        row_range: Requested zero-based, end-exclusive result slice.

    Returns:
        JSON-compatible results and the fulfilled slice.
    """
    start, end = row_range
    width = end - start
    found = timed_all(
        query.order_by(*ordering).offset(start).limit(width + 1),
        stage="aggregate_page",
    )
    return {
        "results": [
            {field: getattr(row, field) for field in fields} for row in found[:width]
        ],
        "offset": start,
        "has_more": len(found) > width,
    }


# =============================================================================
# Helpers belonging to ranking_tools.py
# Ranking conditions intentionally stay scalar and bypass the cohort DSL. The
# anonymous board facts remain the source for the few cross-entity relations
# that cannot be answered from one precomputed ranking projection.
# =============================================================================


def ranking_board_context(
    conn: Any,
    *,
    unit: str | None = None,
    item: str | None = None,
    trait: str | None = None,
) -> tuple[Any, int, str, Any, int] | dict[str, Any]:
    """Build a board universe from simple exact-name ranking conditions.

    Args:
        conn: SQLAlchemy session.
        unit: Optional unit that must exist on each board.
        item: Optional item that must exist somewhere on each board.
        trait: Optional active trait that must exist on each board.

    Returns:
        Anonymous board subquery, private universe size, public population
        description, board predicate, and scope identifier; or a readiness
        error.
    """
    scope = timed_call(
        lambda: active_fact_scope(conn), stage="active_fact_scope"
    )
    if scope is None:
        return analysis_error(
            "analysis_facts_unavailable",
            "Anonymous analysis facts are not ready for the active analysis "
            "scope; run a full tft-rebuild-tables rebuild first.",
            retryable=False,
        )

    conditions: list[Any] = []
    labels: list[str] = []
    if unit is not None:
        conditions.append(
            exists(
                select(1).where(
                    AnalysisBoardUnit.scope_id == AnalysisBoard.scope_id,
                    AnalysisBoardUnit.board_key == AnalysisBoard.board_key,
                    AnalysisBoardUnit.unit_name == unit,
                )
            )
        )
        labels.append(f"unit={unit}")
    if item is not None:
        conditions.append(
            exists(
                select(1).where(
                    AnalysisBoardItem.scope_id == AnalysisBoard.scope_id,
                    AnalysisBoardItem.board_key == AnalysisBoard.board_key,
                    AnalysisBoardItem.item_name == item,
                )
            )
        )
        labels.append(f"item={item}")
    if trait is not None:
        conditions.append(
            exists(
                select(1).where(
                    AnalysisBoardTrait.scope_id == AnalysisBoard.scope_id,
                    AnalysisBoardTrait.board_key == AnalysisBoard.board_key,
                    AnalysisBoardTrait.trait_name == trait,
                    func.coalesce(AnalysisBoardTrait.style, 0) > 0,
                    func.coalesce(AnalysisBoardTrait.tier_current, 0) > 0,
                )
            )
        )
        labels.append(f"active_trait={trait}")

    population_condition = and_(*conditions) if conditions else literal(True)
    boards = (
        select(
            AnalysisBoard.scope_id,
            AnalysisBoard.board_key,
            AnalysisBoard.placement,
        )
        .where(AnalysisBoard.scope_id == scope.scope_id, population_condition)
        .subquery()
    )
    universe = int(
        timed_scalar(
            conn,
            select(func.count()).select_from(boards),
            stage="ranking_universe",
        )
        or 0
    )
    population = "active analysis scope"
    if labels:
        population = f"{population} where {' and '.join(labels)}"
    debug_ranking_event(
        "ranking_population_ready",
        population=population,
        universe=universe,
    )
    return boards, universe, population, population_condition, scope.scope_id


def loadout_contains_items(columns: tuple[Any, ...], items: list[str]) -> Any:
    """Match item terms to distinct loadout slots without order sensitivity.

    Args:
        columns: Ordered SQL columns containing canonical loadout items.
        items: One or two exact stored item names to match.

    Returns:
        SQL expression requiring every term in a distinct loadout slot.
    """
    assignments = (
        and_(*(column == item for column, item in zip(ordering, items)))
        for ordering in permutations(columns, len(items))
    )
    return or_(*assignments)


def ranking_page_with_deltas(
    session: Any,
    page: dict[str, Any],
    *,
    scope_id: int,
    population_condition: Any,
    entity_kind: str,
    group_by: list[str],
    held_item: str | None = None,
    required_items: list[str] | None = None,
) -> dict[str, Any]:
    """Add placement delta fields to one already-sliced ranking page.

    The ranking query remains responsible for metrics, filters, sorting, and
    pagination. This helper calculates both disjoint placement comparisons only
    for the returned entity keys, preserving the delta tools' definitions while
    avoiding a second unbounded entity result.

    Args:
        session: Worker-thread SQLAlchemy session.
        page: Internal ranking page whose rows will be enriched in place.
        scope_id: Private active analysis scope identifier.
        population_condition: Board predicate defining the ranking population.
        entity_kind: Entity presence strategy used by the delta pipeline.
        group_by: Effective entity dimensions for matching ranking rows.
        held_item: Optional item bound to ranked unit occurrences.
        required_items: Optional distinct-slot loadout item conditions.

    Returns:
        The ranking page with ``delta`` and ``relative_delta`` on every row.
    """
    rows = page["results"]
    if not rows:
        return page
    keys = [tuple(row[name] for name in group_by) for row in rows]
    delta_page = entity_delta_page(
        session,
        scope_id=scope_id,
        population_condition=population_condition,
        entity_kind=entity_kind,
        group_by=group_by,
        row_range=[0, len(keys)],
        minimum_boards=MIN_PUBLIC_BOARDS,
        entity_keys=keys,
        held_item=held_item,
        required_items=required_items,
    )
    delta_by_key = {
        tuple(row[name] for name in group_by): row
        for row in delta_page["results"]
    }
    for row, key in zip(rows, keys):
        delta_row = delta_by_key.get(key)
        row["delta"] = delta_row["delta"] if delta_row is not None else None
        row["relative_delta"] = (
            delta_row["relative_delta"] if delta_row is not None else None
        )
    return page


def conditional_page(
    conn: Any,
    statement: Any,
    fields: tuple[str, ...],
    *,
    sample_field: str,
    min_sample: int | None,
    max_sample: int | None,
    sort_by: str,
    sort_direction: str,
    tie_fields: tuple[str, ...],
    row_range: list[int],
) -> dict[str, Any]:
    """Filter, order, and slice a conditional aggregate statement.

    Args:
        conn: SQLAlchemy session.
        statement: Aggregate select over an anonymous cohort.
        fields: Returned column names.
        sample_field: Field containing the reportable sample.
        min_sample: Optional caller-requested minimum sample.
        max_sample: Optional caller-requested maximum sample.
        sort_by: Default sort metric.
        sort_direction: Default sort direction.
        tie_fields: Stable tie-breaker fields.
        row_range: Requested zero-based, end-exclusive result slice.

    Returns:
        JSON-compatible conditional result slice.
    """
    rows = statement.subquery()
    query = conn.query(*(getattr(rows.c, name) for name in fields))
    sample = getattr(rows.c, sample_field)
    query = query.filter(sample >= max(MIN_PUBLIC_BOARDS, min_sample or 0))
    if max_sample is not None:
        query = query.filter(sample <= max_sample)
    ordering = list(order_columns(rows.c, sort_by, sort_direction))
    ordering.extend(getattr(rows.c, name).asc() for name in tie_fields)
    start, end = row_range
    width = end - start
    found = timed_all(
        query.order_by(*ordering).offset(start).limit(width + 1),
        stage="conditional_page",
    )
    return {
        "results": [
            {field: getattr(row, field) for field in fields} for row in found[:width]
        ],
        "offset": start,
        "has_more": len(found) > width,
    }


def outcome_expressions(placement: Any) -> tuple[Any, Any, Any]:
    """Build placement, top-four, and win aggregate expressions.

    Args:
        placement: SQLAlchemy placement expression.

    Returns:
        Average placement, top-four rate, and win-rate expressions.
    """
    return (
        func.avg(placement),
        func.avg(case((placement.is_(None), None), (placement <= 4, 1.0), else_=0.0)),
        func.avg(case((placement.is_(None), None), (placement == 1, 1.0), else_=0.0)),
    )


def result_cell(value: Any) -> Any:
    """Convert a database result value to JSON-compatible data.

    Args:
        value: Scalar, sequence, mapping, or database-native value.

    Returns:
        JSON-compatible value.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [result_cell(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)
