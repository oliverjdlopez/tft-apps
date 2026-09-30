"""Cohort-relative entity breakouts over anonymous final-board facts."""

from __future__ import annotations

from typing import Annotated, Any, List

from agents import function_tool
from agents.tool_context import ToolContext
from pydantic import AfterValidator, Field
from domain.types import AssistantToolGroup

from .cohort_query import (
    FULL_REBUILD_REQUIRED,
    active_fact_scope,
    compile_filter_group,
)
from .models import FilterGroup
from .utils import (
    MIN_PUBLIC_BOARDS,
    TOOL_TIMEOUT_SECONDS,
    analysis_error,
    entity_delta_page,
    population_table_result,
    run_db_tool,
    validate_ranking_range,
)


DeltaRangeIndex = Annotated[int, Field(ge=0, le=10_000)]
DeltaResultRange = Annotated[
    List[DeltaRangeIndex],
    Field(min_length=2, max_length=2),
    AfterValidator(validate_ranking_range),
]


@function_tool(strict_mode=True, timeout=TOOL_TIMEOUT_SECONDS)
async def get_cohort_unit_deltas(
    ctx: ToolContext[Any],
    cohort: FilterGroup,
    group_by_star_level: bool = False,
    range: DeltaResultRange = [0, 10],
) -> dict[str, Any]:
    """Break out unit frequency and placement deltas within one cohort.

    ``delta`` compares cohort boards with and without the unit row.
    ``relative_delta`` compares the unit row inside and outside the cohort.
    Star buckets are matched exactly when requested, and negative values are
    better for both metrics.

    Args:
        ctx: Agents SDK tool context.
        cohort: Structured board population to analyze.
        group_by_star_level: Whether to return one row per exact star bucket.
        range: Zero-based, end-exclusive result slice.

    Returns:
        A bounded table of unit samples, frequency, outcomes, and deltas.
    """

    def read(conn: Any) -> dict[str, Any]:
        """Execute the unit breakout in the worker-thread session.

        Args:
            conn: Worker-thread SQLAlchemy session.

        Returns:
            Validated delta table or structured unavailable-facts error.
        """
        group = (
            cohort
            if isinstance(cohort, FilterGroup)
            else FilterGroup.model_validate(cohort)
        )
        scope = active_fact_scope(conn)
        if scope is None:
            return analysis_error(
                "cohort_facts_unavailable",
                FULL_REBUILD_REQUIRED,
                retryable=False,
            )
        dimensions = ["unit_name"]
        if group_by_star_level:
            dimensions.append("star_level")
        page = entity_delta_page(
            conn,
            scope_id=scope.scope_id,
            population_condition=compile_filter_group(group),
            entity_kind="unit",
            group_by=dimensions,
            row_range=range,
            minimum_boards=MIN_PUBLIC_BOARDS,
        )
        population_boards = page.pop("population_boards")
        return population_table_result(
            page,
            population_group=group,
            population_boards=population_boards,
            group_by=dimensions,
            sort_by="games",
            sort_direction="desc",
        )

    return await run_db_tool(ctx, read)


@function_tool(strict_mode=True, timeout=TOOL_TIMEOUT_SECONDS)
async def get_cohort_item_deltas(
    ctx: ToolContext[Any],
    cohort: FilterGroup,
    group_by_holder: bool = True,
    range: DeltaResultRange = [0, 10],
) -> dict[str, Any]:
    """Break out item frequency and placement deltas within one cohort.

    Item outcomes are board-weighted even when a board holds duplicate copies.
    ``delta`` compares cohort boards with and without the item row, while
    ``relative_delta`` compares the same item/holder grain inside and outside
    the cohort. Negative placement deltas are better.

    Args:
        ctx: Agents SDK tool context.
        cohort: Structured board population to analyze.
        group_by_holder: Whether to return exact item-holder rows.
        range: Zero-based, end-exclusive result slice.

    Returns:
        A bounded table of item samples, holds, frequency, outcomes, and deltas.
    """

    def read(conn: Any) -> dict[str, Any]:
        """Execute the item breakout in the worker-thread session.

        Args:
            conn: Worker-thread SQLAlchemy session.

        Returns:
            Validated delta table or structured unavailable-facts error.
        """
        group = (
            cohort
            if isinstance(cohort, FilterGroup)
            else FilterGroup.model_validate(cohort)
        )
        scope = active_fact_scope(conn)
        if scope is None:
            return analysis_error(
                "cohort_facts_unavailable",
                FULL_REBUILD_REQUIRED,
                retryable=False,
            )
        dimensions = ["item_name"]
        if group_by_holder:
            dimensions.append("unit_name")
        page = entity_delta_page(
            conn,
            scope_id=scope.scope_id,
            population_condition=compile_filter_group(group),
            entity_kind="item",
            group_by=dimensions,
            row_range=range,
            minimum_boards=MIN_PUBLIC_BOARDS,
        )
        population_boards = page.pop("population_boards")
        return population_table_result(
            page,
            population_group=group,
            population_boards=population_boards,
            group_by=dimensions,
            sort_by="boards",
            sort_direction="desc",
        )

    return await run_db_tool(ctx, read)


@function_tool(strict_mode=True, timeout=TOOL_TIMEOUT_SECONDS)
async def get_cohort_trait_deltas(
    ctx: ToolContext[Any],
    cohort: FilterGroup,
    group_by_tier: bool = True,
    range: DeltaResultRange = [0, 10],
) -> dict[str, Any]:
    """Break out active-trait frequency and placement deltas within one cohort.

    ``delta`` compares cohort boards with and without the trait row, while
    ``relative_delta`` compares the same trait/tier grain inside and outside
    the cohort. Negative placement deltas are better.

    Args:
        ctx: Agents SDK tool context.
        cohort: Structured board population to analyze.
        group_by_tier: Whether to return one row per named activation medal.
        range: Zero-based, end-exclusive result slice.

    Returns:
        A bounded table of trait samples, frequency, outcomes, and deltas.
    """

    def read(conn: Any) -> dict[str, Any]:
        """Execute the trait breakout in the worker-thread session.

        Args:
            conn: Worker-thread SQLAlchemy session.

        Returns:
            Validated delta table or structured unavailable-facts error.
        """
        group = (
            cohort
            if isinstance(cohort, FilterGroup)
            else FilterGroup.model_validate(cohort)
        )
        scope = active_fact_scope(conn)
        if scope is None:
            return analysis_error(
                "cohort_facts_unavailable",
                FULL_REBUILD_REQUIRED,
                retryable=False,
            )
        dimensions = ["trait_name"]
        if group_by_tier:
            dimensions.append("tier")
        page = entity_delta_page(
            conn,
            scope_id=scope.scope_id,
            population_condition=compile_filter_group(group),
            entity_kind="trait",
            group_by=dimensions,
            row_range=range,
            minimum_boards=MIN_PUBLIC_BOARDS,
        )
        population_boards = page.pop("population_boards")
        return population_table_result(
            page,
            population_group=group,
            population_boards=population_boards,
            group_by=dimensions,
            sort_by="games",
            sort_direction="desc",
        )

    return await run_db_tool(ctx, read)


DELTA_TOOL_GROUP = AssistantToolGroup(
    key="deltas",
    label="Cohort Deltas",
    description=(
        "Bounded entity frequency and placement delta breakouts within and "
        "outside anonymous final-board cohorts."
    ),
    tools=(
        get_cohort_unit_deltas,
        get_cohort_item_deltas,
        get_cohort_trait_deltas,
    ),
)


__all__ = [
    "DELTA_TOOL_GROUP",
    "get_cohort_item_deltas",
    "get_cohort_trait_deltas",
    "get_cohort_unit_deltas",
]
