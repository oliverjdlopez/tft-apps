"""Structured cohort tools over anonymous TFT board facts.

This module owns the model-facing cohort comparison and grouped cohort query
operations. Reusable schemas live in ``models.py``, while cohort compilation
and shared query mechanics live in ``cohort_query.py`` and ``utils.py``.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, List, Literal, Optional

from agents import function_tool
from agents.tool_context import ToolContext
from pydantic import Field
from sqlalchemy import and_, case, func, select, true
from sqlalchemy.orm import aliased

from db.models import (
    AnalysisBoard,
    AnalysisBoardItem,
    AnalysisBoardTrait,
    AnalysisBoardUnit,
)
from domain.types import AssistantToolGroup
from .cohort_query import (
    FULL_REBUILD_REQUIRED,
    active_fact_scope,
    compile_filter_group,
)
from .models import (
    AnalysisComparisonResult,
    CohortOrderRule,
    FilterGroup,
)
from .utils import (
    MIN_PUBLIC_BOARDS,
    TOOL_TIMEOUT_SECONDS,
    analysis_error,
    analysis_warning,
    describe_filter_group,
    population_table_result,
    result_cell,
    run_db_tool,
    sample_bounds_error,
    trait_tier_expression,
)


CohortRowLimit = Annotated[int, Field(ge=1, le=500)]
CohortOffset = Annotated[int, Field(ge=0, le=100_000)]
CohortSampleSize = Annotated[int, Field(ge=1)]
CohortDimension = Literal[
    "placement",
    "level",
    "board_size",
    "completed_item_count",
    "region",
    "platform",
    "unit_name",
    "unit_star_level",
    "unit_cost",
    "unit_item_count",
    "unit_loadout_key",
    "item_name",
    "item_slot",
    "trait_name",
    "trait_tier",
    "trait_style",
    "trait_contributing_unit_count",
]
CohortDimensions = Annotated[List[CohortDimension], Field(min_length=1, max_length=3)]
CohortOrderRules = Annotated[List[CohortOrderRule], Field(min_length=1, max_length=3)]


@function_tool(strict_mode=True, timeout=TOOL_TIMEOUT_SECONDS)
async def compare_cohorts(
    ctx: ToolContext[Any],
    target: FilterGroup,
    baseline: Optional[FilterGroup] = None,
    shared: Optional[FilterGroup] = None,
) -> dict[str, Any]:
    """Compare placement outcomes descriptively between two board cohorts.

    This is the workhorse for correlation questions and for isolating effects:
    define cohorts by what a final board contains, optionally condition both on
    a shared context to control a confounder, and get board-level samples,
    placement distributions, and effect sizes in one call.

    Usage patterns:
    - Board-presence association: target = boards with an item; omit
      baseline to compare against all other boards in the scoped population.
    - Shared shell: put the common units or traits in `shared`, then compare two
      board-presence cohorts inside it.
    - Head to head: give both cohorts explicitly (e.g. two carries, two traits).
      Overlapping boards are counted and reported; interpret with care.

    A name-only entity condition means board presence with its other attributes
    unconstrained. Item conditions with holder fields bind an item to its exact
    holder occurrence and can also constrain the holder's star level.

    Args:
        ctx: Agents SDK tool context.
        target: Boards satisfying every structured entity and level condition.
        baseline: Comparison cohort. Omit to use the complement of target within
            the shared/scope context (recommended for target-versus-rest reads).
        shared: Requirements applied to BOTH cohorts (the controlled context).

    Returns:
        A comparison result containing target and baseline summaries, aligned
        target-minus-baseline effects, overlap state, and structured warnings.
        Cohorts below 50 boards are suppressed. Eligible effects include
        lobby-clustered 95% confidence intervals.
    """

    def read(conn: Any) -> dict[str, Any]:
        """Execute this tool's query using the worker-thread session.

        Args:
            conn: Worker-thread SQLAlchemy session.

        Returns:
            Validated comparison or structured error result.
        """
        target_group = (
            target
            if isinstance(target, FilterGroup)
            else FilterGroup.model_validate(target)
        )
        baseline_group = (
            None
            if baseline is None
            else (
                baseline
                if isinstance(baseline, FilterGroup)
                else FilterGroup.model_validate(baseline)
            )
        )
        shared_group = (
            None
            if shared is None
            else (
                shared
                if isinstance(shared, FilterGroup)
                else FilterGroup.model_validate(shared)
            )
        )

        fact_scope = active_fact_scope(conn)
        if fact_scope is None:
            return analysis_error(
                "cohort_facts_unavailable",
                FULL_REBUILD_REQUIRED,
                retryable=False,
            )

        board_model = AnalysisBoard
        target_condition = compile_filter_group(target_group, board_model)
        baseline_condition = (
            compile_filter_group(baseline_group, board_model)
            if baseline_group is not None
            else ~target_condition
        )
        shared_condition = (
            compile_filter_group(shared_group, board_model)
            if shared_group is not None
            else true()
        )
        # Anonymous lobby keys retain within-lobby dependence for clustered
        # intervals without allowing raw identifiers into this query path.
        query = conn.query(
            board_model.lobby_key.label("lobby_key"),
            board_model.placement.label("placement"),
            func.sum(case((target_condition, 1), else_=0)).label("target_boards"),
            func.sum(case((baseline_condition, 1), else_=0)).label("baseline_boards"),
            func.sum(case((and_(target_condition, baseline_condition), 1), else_=0)).label(
                "overlap_boards"
            ),
        ).filter(
            board_model.scope_id == fact_scope.scope_id,
            board_model.placement.isnot(None),
            shared_condition,
        )
        aggregate_rows = query.group_by(
            board_model.lobby_key, board_model.placement
        ).all()

        def cohort_rows(column: str) -> list[Any]:
            """Collapse lobby-placement aggregates into cohort histogram rows.

            Args:
                column: Aggregate-row count field for the selected cohort.

            Returns:
                Placement and board-count rows for summary calculation.
            """
            histogram: dict[int, int] = {}
            # Query rows are lobby-placement aggregates. Collapse lobbies only
            # for public descriptive summaries; retain the source rows below
            # for cluster-robust uncertainty calculations.
            for row in aggregate_rows:
                count = int(getattr(row, column) or 0)
                if count:
                    place = int(row.placement)
                    histogram[place] = histogram.get(place, 0) + count
            return [
                type("CohortRow", (), {"placement": place, "boards": count})
                for place, count in histogram.items()
            ]

        def summarize(rows: list[Any]) -> dict[str, Any]:
            """Calculate reportable descriptive outcomes for one cohort.

            Args:
                rows: Placement histogram rows for the cohort.

            Returns:
                Public summary plus private intermediate comparison values.
            """
            histogram = {int(row.placement): int(row.boards) for row in rows}
            boards = sum(histogram.values())
            if boards == 0:
                return {
                    "boards": 0,
                    "suppressed": False,
                    "histogram": histogram,
                    "_boards": 0,
                }
            if boards < MIN_PUBLIC_BOARDS:
                return {
                    "boards": None,
                    "suppressed": True,
                    "minimum_boards": MIN_PUBLIC_BOARDS,
                    "_boards": boards,
                }
            total = sum(place * count for place, count in histogram.items())
            mean = total / boards
            variance = (
                sum(count * (place - mean) ** 2 for place, count in histogram.items())
                / max(boards - 1, 1)
            )
            top4 = sum(count for place, count in histogram.items() if place <= 4)
            wins = histogram.get(1, 0)
            return {
                "boards": boards,
                "suppressed": False,
                "avg_placement": round(mean, 4),
                "placement_stddev": round(math.sqrt(variance), 4),
                "top4_rate": round(top4 / boards, 4),
                "win_rate": round(wins / boards, 4),
                "histogram": {str(place): histogram.get(place, 0) for place in range(1, 9)},
                "_mean": mean,
                "_var": variance,
                "_top4": top4,
                "_wins": wins,
                "_boards": boards,
            }

        target_summary = summarize(cohort_rows("target_boards"))
        if baseline_group is not None:
            baseline_summary = summarize(cohort_rows("baseline_boards"))
            baseline_label = describe_filter_group(baseline_group)
        else:
            baseline_summary = summarize(cohort_rows("baseline_boards"))
            baseline_label = (
                f"NOT ({describe_filter_group(target_group)}) within same scope"
            )

        target_label = describe_filter_group(target_group)

        comparison: dict[str, Any] = {}
        warnings: list[dict[str, str]] = []
        if (
            baseline_group is None
            and shared_group is not None
            and target_group == shared_group
        ):
            warnings.append(
                analysis_warning(
                    "invalid_comparison_context",
                    "The target is already guaranteed by the shared context; its "
                    "complement is empty. Remove the duplicated shared requirement "
                    "or provide an explicit baseline.",
                )
            )
        n_target = target_summary["_boards"]
        n_baseline = baseline_summary["_boards"]
        reportable = (
            n_target >= MIN_PUBLIC_BOARDS and n_baseline >= MIN_PUBLIC_BOARDS
        )
        if reportable:
            delta = target_summary["_mean"] - baseline_summary["_mean"]
            p_target = target_summary["_top4"] / n_target
            p_baseline = baseline_summary["_top4"] / n_baseline
            comparison = {
                "avg_placement_delta": round(delta, 4),
                "top4_rate_delta": round(p_target - p_baseline, 4),
                "win_rate_delta": round(
                    target_summary["_wins"] / n_target
                    - baseline_summary["_wins"] / n_baseline,
                    4,
                ),
                "note": (
                    "Negative avg_placement_delta means the target places better. "
                    "Boards in one lobby are dependent; intervals are uncertainty "
                    "estimates for observational associations, not causal evidence."
                ),
            }

            lobby_count = len({str(row.lobby_key) for row in aggregate_rows})
            if n_target >= 50 and n_baseline >= 50 and lobby_count >= 30:
                def clustered_interval(metric: str) -> dict[str, Any]:
                    """Estimate a lobby-clustered confidence interval.

                    Args:
                        metric: Outcome metric to compare between cohorts.

                    Returns:
                        Estimate, robust standard error, and 95% interval.
                    """
                    if metric == "avg_placement":
                        target_mean = target_summary["_mean"]
                        baseline_mean = baseline_summary["_mean"]
                        outcome = lambda place: float(place)
                    elif metric == "top4_rate":
                        target_mean, baseline_mean = p_target, p_baseline
                        outcome = lambda place: float(place <= 4)
                    else:
                        target_mean = target_summary["_wins"] / n_target
                        baseline_mean = baseline_summary["_wins"] / n_baseline
                        outcome = lambda place: float(place == 1)
                    by_lobby: dict[str, list[float]] = {}
                    for row in aggregate_rows:
                        # Each vector holds outcome sums and counts for A/B.
                        # Keeping them joint retains covariance for overlaps.
                        values = by_lobby.setdefault(
                            str(row.lobby_key),
                            [0.0, 0.0, 0.0, 0.0],
                        )
                        target_count = int(row.target_boards or 0)
                        baseline_count = int(row.baseline_boards or 0)
                        values[0] += outcome(int(row.placement)) * target_count
                        values[1] += target_count
                        values[2] += outcome(int(row.placement)) * baseline_count
                        values[3] += baseline_count
                    influences = [
                        (target_sum - target_mean * target_count) / n_target
                        - (baseline_sum - baseline_mean * baseline_count)
                        / n_baseline
                        for (
                            target_sum,
                            target_count,
                            baseline_sum,
                            baseline_count,
                        ) in by_lobby.values()
                    ]
                    variance = lobby_count / (lobby_count - 1) * sum(
                        value * value for value in influences
                    )
                    standard_error = math.sqrt(max(variance, 0.0))
                    estimate = target_mean - baseline_mean
                    return {
                        "estimate": round(estimate, 6),
                        "cluster_robust_standard_error": round(standard_error, 6),
                        "confidence_interval_95": {
                            "lower": round(estimate - 1.96 * standard_error, 6),
                            "upper": round(estimate + 1.96 * standard_error, 6),
                        },
                    }

                comparison["clustered_95_confidence_intervals"] = {
                    metric: clustered_interval(metric)
                    for metric in ("avg_placement", "top4_rate", "win_rate")
                }
                comparison["clustered_lobbies"] = lobby_count
            else:
                warnings.append(
                    analysis_warning(
                        "confidence_interval_unavailable",
                        "Lobby-clustered intervals require at least 50 boards in each "
                        "cohort and 30 lobbies in the selected population.",
                    )
                )
        if min(n_target, n_baseline) == 0:
            warnings.append(
                analysis_warning(
                    "empty_cohort",
                    "One cohort is empty; resolve names and widen the population.",
                )
            )
        elif min(n_target, n_baseline) < MIN_PUBLIC_BOARDS:
            warnings.append(
                analysis_warning(
                    "sample_suppressed",
                    f"One or both nonempty cohorts have fewer than {MIN_PUBLIC_BOARDS} "
                    "boards; counts and outcome metrics are suppressed.",
                )
            )
        elif min(n_target, n_baseline) < 100:
            warnings.append(
                analysis_warning(
                    "small_sample",
                    "The smaller cohort has fewer than 100 boards; differences may be noise.",
                )
            )

        overlap = sum(int(row.overlap_boards or 0) for row in aggregate_rows)
        if baseline_group is not None and n_target and n_baseline:
            if overlap:
                if overlap >= MIN_PUBLIC_BOARDS:
                    warnings.append(
                        analysis_warning(
                            "cohorts_overlap",
                            f"{overlap} boards satisfy both cohorts; this is not a "
                            "disjoint head-to-head.",
                        )
                    )
                else:
                    warnings.append(
                        analysis_warning(
                            "cohorts_overlap",
                            "The cohorts overlap, but the exact overlap is below the "
                            "public reporting threshold.",
                        )
                    )
                comparison = {
                    key: value
                    for key, value in comparison.items()
                    if key
                    in {
                        "avg_placement_delta",
                        "top4_rate_delta",
                        "win_rate_delta",
                        "clustered_95_confidence_intervals",
                        "clustered_lobbies",
                    }
                }
                comparison["note"] = (
                    "Overlapping cohorts use a joint lobby influence so covariance is "
                    "retained. Intervals describe observational associations, not causation."
                )

        public_overlap: int | None = overlap
        if 0 < overlap < MIN_PUBLIC_BOARDS:
            public_overlap = None
            warnings.append(
                analysis_warning(
                    "overlap_suppressed",
                    f"Cohort overlap is nonzero but below {MIN_PUBLIC_BOARDS} boards; "
                    "the exact count is suppressed.",
                )
            )

        for summary in (target_summary, baseline_summary):
            for key in ("_mean", "_var", "_top4", "_wins", "_boards"):
                summary.pop(key, None)

        intervals = comparison.get("clustered_95_confidence_intervals", {})
        effects = []
        for metric, delta_key in (
            ("avg_placement", "avg_placement_delta"),
            ("top4_rate", "top4_rate_delta"),
            ("win_rate", "win_rate_delta"),
        ):
            if delta_key not in comparison:
                continue
            interval = intervals.get(metric)
            effects.append(
                {
                    "metric": metric,
                    "estimate": comparison[delta_key],
                    "cluster_robust_standard_error": (
                        interval.get("cluster_robust_standard_error")
                        if interval
                        else None
                    ),
                    "confidence_interval_95": (
                        interval.get("confidence_interval_95") if interval else None
                    ),
                }
            )
        return AnalysisComparisonResult(
            context={
                "shared_population": (
                    describe_filter_group(shared_group)
                    if shared_group
                    else None
                ),
                "minimum_reportable_boards": MIN_PUBLIC_BOARDS,
            },
            target={"label": target_label, **target_summary},
            baseline={"label": baseline_label, **baseline_summary},
            effects=effects,
            overlap={
                "boards": public_overlap,
                "suppressed": 0 < overlap < MIN_PUBLIC_BOARDS,
            },
            warnings=warnings,
        ).model_dump(mode="json")

    return await run_db_tool(ctx, read)


@function_tool(strict_mode=True, timeout=TOOL_TIMEOUT_SECONDS)
async def query_cohort(
    ctx: ToolContext[Any],
    cohort: FilterGroup,
    group_by: CohortDimensions,
    min_sample: Optional[CohortSampleSize] = None,
    max_sample: Optional[CohortSampleSize] = None,
    order_by: Optional[CohortOrderRules] = None,
    limit: CohortRowLimit = 100,
    offset: CohortOffset = 0,
) -> dict[str, Any]:
    """Group anonymous boards by one to three bounded analytical dimensions.

    Unit and item dimensions bind to the exact holder occurrence when combined.
    Unit/trait and item/trait dimensions represent same-board co-occurrence.

    Args:
        ctx: Agents SDK tool context.
        cohort: Board population to group.
        group_by: One to three supported analytical dimensions.
        min_sample: Optional minimum distinct-board count per grouped row.
        max_sample: Optional maximum distinct-board count per grouped row.
        order_by: Optional grouped-result ordering rules.
        limit: Maximum grouped rows to return.
        offset: Grouped-result offset.

    Returns:
        A validated table result with grouped rows, population context, and page.
    """

    def read(conn: Any) -> dict[str, Any]:
        """Execute this tool's query using the worker-thread session.

        Args:
            conn: Worker-thread SQLAlchemy session.

        Returns:
            Validated grouped table or structured error result.
        """
        if error := sample_bounds_error(min_sample, max_sample):
            return error

        group = (
            cohort
            if isinstance(cohort, FilterGroup)
            else FilterGroup.model_validate(cohort)
        )
        rules = [
            rule if isinstance(rule, CohortOrderRule) else CohortOrderRule.model_validate(rule)
            for rule in (order_by or [])
        ]
        dimensions = list(dict.fromkeys(group_by))
        if len(dimensions) != len(group_by):
            return analysis_error(
                "invalid_arguments",
                "group_by dimensions must be unique.",
                retryable=False,
            )
        scope = active_fact_scope(conn)
        if scope is None:
            return analysis_error(
                "cohort_facts_unavailable",
                FULL_REBUILD_REQUIRED,
                retryable=False,
            )

        unit_dimensions = {
            "unit_name",
            "unit_star_level",
            "unit_cost",
            "unit_item_count",
            "unit_loadout_key",
        }
        item_dimensions = {"item_name", "item_slot"}
        trait_dimensions = {
            "trait_name",
            "trait_tier",
            "trait_style",
            "trait_contributing_unit_count",
        }
        needs_unit = bool(unit_dimensions.intersection(dimensions))
        needs_item = bool(item_dimensions.intersection(dimensions))
        needs_trait = bool(trait_dimensions.intersection(dimensions))
        # Requested dimensions determine the fact joins. Cohort predicates are
        # compiled separately as board-level EXISTS clauses.
        unit = aliased(AnalysisBoardUnit)
        item = aliased(AnalysisBoardItem)
        trait = aliased(AnalysisBoardTrait)
        expressions: dict[str, Any] = {
            "placement": AnalysisBoard.placement,
            "level": AnalysisBoard.level,
            "board_size": AnalysisBoard.unit_count,
            "completed_item_count": AnalysisBoard.completed_item_count,
            "region": AnalysisBoard.region,
            "platform": AnalysisBoard.platform,
            "unit_name": unit.unit_name,
            "unit_star_level": unit.star_level,
            "unit_cost": unit.cost,
            "unit_item_count": unit.completed_item_count,
            "unit_loadout_key": unit.loadout_key,
            "item_name": item.item_name,
            "item_slot": item.item_slot,
            "trait_name": trait.trait_name,
            "trait_tier": trait_tier_expression(trait.style),
            "trait_style": trait.style,
            "trait_contributing_unit_count": trait.num_units,
        }
        selected = [expressions[name].label(name) for name in dimensions]
        base = conn.query(
            AnalysisBoard.board_key.label("board_key"),
            AnalysisBoard.lobby_key.label("lobby_key"),
            AnalysisBoard.placement.label("outcome_placement"),
            *selected,
        ).filter(
            AnalysisBoard.scope_id == scope.scope_id,
            compile_filter_group(group, AnalysisBoard),
        )
        if needs_item:
            base = base.join(
                item,
                and_(
                    item.scope_id == AnalysisBoard.scope_id,
                    item.board_key == AnalysisBoard.board_key,
                ),
            )
            if needs_unit:
                # Binding through unit_idx makes combined unit/item dimensions
                # describe the holder relationship, not board co-presence.
                base = base.join(
                    unit,
                    and_(
                        unit.scope_id == item.scope_id,
                        unit.board_key == item.board_key,
                        unit.unit_idx == item.unit_idx,
                    ),
                )
        elif needs_unit:
            base = base.join(
                unit,
                and_(
                    unit.scope_id == AnalysisBoard.scope_id,
                    unit.board_key == AnalysisBoard.board_key,
                ),
            )
        if needs_trait:
            # Traits are board facts, so combining them with unit or item
            # dimensions intentionally represents same-board co-presence.
            base = base.join(
                trait,
                and_(
                    trait.scope_id == AnalysisBoard.scope_id,
                    trait.board_key == AnalysisBoard.board_key,
                ),
            )
        # Relationship joins can fan out identical dimension combinations.
        # Restore one board/dimension row before calculating public metrics.
        grain = base.distinct().subquery()
        dimension_columns = [getattr(grain.c, name) for name in dimensions]
        distinct_boards = func.count(func.distinct(grain.c.board_key))
        distinct_lobbies = func.count(func.distinct(grain.c.lobby_key))
        avg_placement = func.avg(grain.c.outcome_placement)
        top4_rate = func.avg(
            case(
                (grain.c.outcome_placement.is_(None), None),
                (grain.c.outcome_placement <= 4, 1.0),
                else_=0.0,
            )
        )
        win_rate = func.avg(
            case(
                (grain.c.outcome_placement.is_(None), None),
                (grain.c.outcome_placement == 1, 1.0),
                else_=0.0,
            )
        )
        # Pick rate is relative to the filtered board cohort, independent of
        # dimension joins and their multiplicity.
        universe = int(
            conn.scalar(
                select(func.count())
                .select_from(AnalysisBoard)
                .where(
                    AnalysisBoard.scope_id == scope.scope_id,
                    compile_filter_group(group, AnalysisBoard),
                )
            )
            or 0
        )
        pick_rate = distinct_boards * 1.0 / max(universe, 1)
        aggregate_metrics = {
            "distinct_boards": distinct_boards,
            "distinct_lobbies": distinct_lobbies,
            "avg_placement": avg_placement,
            "top4_rate": top4_rate,
            "win_rate": win_rate,
            "pick_rate": pick_rate,
        }
        query = conn.query(
            *(column.label(name) for name, column in zip(dimensions, dimension_columns)),
            *(expression.label(name) for name, expression in aggregate_metrics.items()),
        ).select_from(grain).group_by(*dimension_columns)
        # The repository-wide privacy floor cannot be weakened by a caller's
        # requested sample range.
        minimum_boards = max(MIN_PUBLIC_BOARDS, min_sample or 0)
        query = query.having(distinct_boards >= minimum_boards)
        if max_sample is not None:
            query = query.having(distinct_boards <= max_sample)
        ordering: list[Any] = []
        for rule in rules or [CohortOrderRule(metric="distinct_boards", direction="desc")]:
            expression = aggregate_metrics[rule.metric]
            ordering.append(expression.asc() if rule.direction == "asc" else expression.desc())
        ordering.extend(column.asc() for column in dimension_columns)
        # Fetch one extra group to produce has_more without an unbounded count.
        found = query.order_by(*ordering).offset(offset).limit(limit + 1).all()
        rows = [
            {
                name: result_cell(getattr(row, name))
                for name in (*dimensions, *aggregate_metrics.keys())
            }
            for row in found[:limit]
        ]
        return population_table_result(
            {
                "results": rows,
                "offset": offset,
                "has_more": len(found) > limit,
            },
            population_group=group,
            population_boards=universe,
            group_by=dimensions,
            sort_by=(rules or [CohortOrderRule(metric="distinct_boards")])[0].metric,
            sort_direction=(
                rules or [CohortOrderRule(metric="distinct_boards")]
            )[0].direction,
        )

    return await run_db_tool(ctx, read)

COHORT_TOOL_GROUP = AssistantToolGroup(
    key="query_cohorts",
    label="Query Cohorts",
    description=(
        "Bounded cohort groupings and lobby-clustered board-cohort comparisons "
        "over anonymous final-board facts."
    ),
    tools=(
        query_cohort,
        compare_cohorts,
    ),
)


__all__ = [
    "COHORT_TOOL_GROUP",
    "compare_cohorts",
    "query_cohort",
]
