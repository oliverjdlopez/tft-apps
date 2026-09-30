"""Typed unit, item, and trait ranking tools over TFT aggregate tables.

This module exposes model-facing unit, item, and trait rankings. Reusable input
models live in ``models.py``, module-local bounded aliases stay here, and
shared query mechanics live in ``utils.py``.
"""

from __future__ import annotations

from typing import Annotated, Any, List, Literal, Optional

from agents import function_tool
from agents.tool_context import ToolContext
from pydantic import AfterValidator, Field
from sqlalchemy import and_, func, literal, select
from sqlalchemy.orm import aliased

from constants import ItemTypes
from db.models import (
    ALL_STARS,
    ALL_TRAIT_TIERS,
    AnalysisBoard,
    AnalysisBoardTrait,
    AnalysisBoardUnit,
    ITEM_OVERALL_UNIT_NAME,
    ItemStatQueryTable,
    TraitStatQueryTable,
    UnitLoadoutStatQueryTable,
    UnitStatQueryTable,
)
from domain.types import AssistantToolGroup
from .models import StoredName, StoredNames, TraitTier
from .utils import (
    MIN_PUBLIC_BOARDS,
    TOOL_TIMEOUT_SECONDS,
    active_scope_population,
    analysis_error,
    analysis_resolution_result,
    analysis_warning,
    apply_sample_bounds,
    conditional_page,
    loadout_contains_items,
    match_score,
    order_columns,
    outcome_expressions,
    page_results,
    population_table_result,
    ranking_board_context,
    ranking_page_with_deltas,
    run_db_tool,
    sample_bounds_error,
    trait_tier_expression,
    validate_ranking_range,
)


LoadoutItemCount = Annotated[int, Field(ge=1, le=3)]
RangeIndex = Annotated[int, Field(ge=0, le=10_000)]
ResultRange = Annotated[
    List[RangeIndex],
    Field(min_length=2, max_length=2),
    AfterValidator(validate_ranking_range),
]
StarLevel = Annotated[int, Field(ge=0, le=4)]
UnitCost = Annotated[int, Field(ge=0, le=20)]
SampleSize = Annotated[int, Field(ge=1)]
SortDirection = Literal["auto", "asc", "desc"]
SortMetric = Literal["games", "avg_placement", "top4_rate", "win_rate", "pick_rate"]
ItemSortMetric = Literal[
    "boards", "holds", "avg_placement", "top4_rate", "win_rate", "pick_rate_per_board"
]
LoadoutSortMetric = Literal[
    "boards",
    "item_count",
    "avg_placement",
    "top4_rate",
    "win_rate",
    "unit_boards",
    "loadout_pick_rate",
]
UNIT_STAT_FIELDS = (
    "unit_name", "star_level", "cost", "games", "avg_placement",
    "top4_rate", "win_rate", "pick_rate", "universe_games",
)
ITEM_STAT_FIELDS = (
    "item_name", "unit_name", "holds", "boards", "avg_placement",
    "top4_rate", "win_rate", "pick_rate_per_board", "universe_games",
)
TRAIT_STAT_FIELDS = (
    "trait_name", "tier", "games", "avg_placement", "top4_rate",
    "win_rate", "pick_rate", "universe_games",
)
LOADOUT_STAT_FIELDS = (
    "unit_name", "star_level", "loadout_key", "item_count", "item_1",
    "item_2", "item_3", "boards", "avg_placement", "top4_rate",
    "win_rate", "unit_boards", "loadout_pick_rate",
)


@function_tool(strict_mode=True, timeout=TOOL_TIMEOUT_SECONDS)
async def resolve_tft_names(ctx: ToolContext[Any], names: StoredNames) -> dict[str, Any]:
    """Resolve player-language names to exact identifiers stored in analysis data.

    Named entity filters do not perform implicit fuzzy matching. Call
    this tool once with all user-mentioned units, items, and traits, then use
    the exact stored names from the returned candidates.

    Args:
        ctx: Agents SDK tool context.
        names: Bounded player-language names to resolve case-insensitively.

    Returns:
        A resolution result containing bounded candidates and suppression flags.
    """

    def read(conn: Any) -> dict[str, Any]:
        """Read reportable entity candidates from active aggregate projections.

        Args:
            conn: Worker-thread SQLAlchemy session.

        Returns:
            Validated resolution or unavailable-scope error result.
        """
        scope = active_scope_population(conn)
        if scope is None:
            return analysis_error(
                "analysis_scope_unavailable",
                "No active analysis scope is available; rebuild analytics first.",
                retryable=False,
            )
        scope_id, _ = scope
        candidates: list[tuple[str, str, int]] = []
        for name, count in (
            conn.query(UnitStatQueryTable.unit_name, UnitStatQueryTable.games)
            .filter(
                UnitStatQueryTable.scope_id == scope_id,
                UnitStatQueryTable.star_level == ALL_STARS,
            )
            .all()
        ):
            candidates.append((name, "unit", int(count)))
        for name, count in (
            conn.query(ItemStatQueryTable.item_name, ItemStatQueryTable.boards)
            .filter(
                ItemStatQueryTable.scope_id == scope_id,
                ItemStatQueryTable.unit_name == ITEM_OVERALL_UNIT_NAME,
            )
            .all()
        ):
            candidates.append((name, "item", int(count)))
        for name, count in (
            conn.query(TraitStatQueryTable.trait_name, TraitStatQueryTable.games)
            .filter(
                TraitStatQueryTable.scope_id == scope_id,
                TraitStatQueryTable.tier == ALL_TRAIT_TIERS,
            )
            .all()
        ):
            candidates.append((name, "trait", int(count)))

        entries: list[dict[str, Any]] = []
        for query_name in names:
            scored: list[dict[str, Any]] = []
            for candidate, kind, count in candidates:
                hit = match_score(query_name, candidate)
                if hit is None:
                    continue
                score, match_type = hit
                scored.append(
                    {
                        "name": candidate,
                        "kind": kind,
                        "match": match_type,
                        "boards": count if count >= MIN_PUBLIC_BOARDS else None,
                        "count_suppressed": count < MIN_PUBLIC_BOARDS,
                        "_score": score,
                        "_count": count,
                    }
                )
            # Private ranking fields provide deterministic candidate ordering
            # and are removed before contract validation.
            scored.sort(key=lambda entry: (-entry["_score"], -entry["_count"]))
            for entry in scored:
                entry.pop("_score")
                entry.pop("_count")
            entries.append(
                {
                    "query": query_name,
                    "matches": scored[:6],
                    "resolved": bool(scored),
                }
            )
        warnings = []
        if any(not entry["resolved"] for entry in entries):
            warnings.append(
                analysis_warning(
                    "unresolved_names",
                    "One or more submitted names had no matching stored identifier.",
                )
            )
        return analysis_resolution_result(entries, warnings=warnings)

    return await run_db_tool(ctx, read, log_ranking=True)


@function_tool(strict_mode=True, timeout=TOOL_TIMEOUT_SECONDS)
async def rank_units(
    ctx: ToolContext[Any],
    star_level: Optional[StarLevel] = None,
    group_by_star_level: bool = False,
    cost: Optional[UnitCost] = None,
    min_cost: Optional[UnitCost] = None,
    max_cost: Optional[UnitCost] = None,
    item: Optional[StoredName] = None,
    trait: Optional[StoredName] = None,
    min_sample: Optional[SampleSize] = None,
    max_sample: Optional[SampleSize] = None,
    sort_by: SortMetric = "games",
    sort_direction: SortDirection = "auto",
    range: ResultRange = [0, 10],
) -> dict[str, Any]:
    """Rank units with star, cost, item, trait, and sample-size controls.

    By default results use the across-stars rollup. Set
    ``group_by_star_level`` to rank every exact star bucket, or provide
    ``star_level`` for one exact bucket.
    Rows include lower-is-better ``delta`` within the selected population and
    ``relative_delta`` for the same unit grain inside versus outside it.

    Args:
        ctx: Agents SDK tool context.
        star_level: Optional exact star bucket.
        group_by_star_level: Whether to return exact-star rows.
        cost: Optional exact unit cost.
        min_cost: Optional minimum unit cost.
        max_cost: Optional maximum unit cost.
        item: Optional item that every ranked unit occurrence must hold.
        trait: Optional active trait required on the same board.
        min_sample: Optional minimum contributing board count.
        max_sample: Optional maximum contributing board count.
        sort_by: Default ranking metric.
        sort_direction: Default ranking direction.
        range: Zero-based, end-exclusive result slice.

    Returns:
        A validated table result with unit rows, context, warnings, and page.
    """

    def read(conn: Any) -> dict[str, Any]:
        """Execute the unit ranking against the selected aggregate source.

        Args:
            conn: Worker-thread SQLAlchemy session.

        Returns:
            Validated unit table or structured error result.
        """
        if error := sample_bounds_error(min_sample, max_sample):
            return error

        context = ranking_board_context(conn, item=item, trait=trait)
        if isinstance(context, dict):
            return context
        boards, universe, population, population_condition, scope_id = context
        dimensions = ["unit_name"]
        if star_level is not None or group_by_star_level:
            dimensions.append("star_level")
        if item is not None or trait is not None:
            unit = aliased(AnalysisBoardUnit)
            # Anonymous board facts have no rollup rows. Project the sentinel so
            # conditional results retain the same grain as stored aggregates.
            chosen_star = (
                unit.star_level
                if star_level is not None or group_by_star_level
                else literal(ALL_STARS)
            )
            grain_query = (
                select(
                    boards.c.board_key,
                    boards.c.placement,
                    unit.unit_name,
                    chosen_star.label("star_level"),
                    unit.cost,
                )
                .join(
                    unit,
                    and_(
                        unit.scope_id == boards.c.scope_id,
                        unit.board_key == boards.c.board_key,
                    ),
                )
            )
            if star_level is not None:
                grain_query = grain_query.where(unit.star_level == star_level)
            if cost is not None:
                grain_query = grain_query.where(unit.cost == cost)
            if min_cost is not None:
                grain_query = grain_query.where(unit.cost >= min_cost)
            if max_cost is not None:
                grain_query = grain_query.where(unit.cost <= max_cost)
            if item is not None:
                grain_query = grain_query.where(
                    loadout_contains_items(
                        (unit.item_1, unit.item_2, unit.item_3),
                        [item],
                    )
                )
            grain = grain_query.distinct().subquery()
            avg_placement, top4_rate, win_rate = outcome_expressions(
                grain.c.placement
            )
            games = func.count(func.distinct(grain.c.board_key))
            statement = select(
                grain.c.unit_name,
                grain.c.star_level,
                func.max(grain.c.cost).label("cost"),
                games.label("games"),
                avg_placement.label("avg_placement"),
                top4_rate.label("top4_rate"),
                win_rate.label("win_rate"),
                (games * 1.0 / max(universe, 1)).label("pick_rate"),
                literal(universe).label("universe_games"),
            ).group_by(grain.c.unit_name, grain.c.star_level)
            page = ranking_page_with_deltas(
                conn,
                conditional_page(
                    conn,
                    statement,
                    UNIT_STAT_FIELDS,
                    sample_field="games",
                    min_sample=min_sample,
                    max_sample=max_sample,
                    sort_by=sort_by,
                    sort_direction=sort_direction,
                    tie_fields=("unit_name", "star_level"),
                    row_range=range,
                ),
                scope_id=scope_id,
                population_condition=population_condition,
                entity_kind="unit",
                group_by=dimensions,
                held_item=item,
            )
            return population_table_result(
                page,
                population=population,
                population_boards=universe,
                group_by=dimensions,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
        query = conn.query(UnitStatQueryTable).filter(
            UnitStatQueryTable.scope_id == scope_id
        )
        # Sentinel rows are materialized rollups, while non-sentinel rows are
        # the mutually exclusive exact-star buckets.
        if star_level is not None:
            query = query.filter(UnitStatQueryTable.star_level == star_level)
        elif group_by_star_level:
            query = query.filter(UnitStatQueryTable.star_level != ALL_STARS)
        else:
            query = query.filter(UnitStatQueryTable.star_level == ALL_STARS)
        if cost is not None:
            query = query.filter(UnitStatQueryTable.cost == cost)
        if min_cost is not None:
            query = query.filter(UnitStatQueryTable.cost >= min_cost)
        if max_cost is not None:
            query = query.filter(UnitStatQueryTable.cost <= max_cost)
        query = apply_sample_bounds(
            query,
            UnitStatQueryTable,
            min_sample,
            max_sample,
            sample_column="games",
        )
        ordering = order_columns(
            UnitStatQueryTable,
            sort_by,
            sort_direction,
            UnitStatQueryTable.unit_name.asc(),
            UnitStatQueryTable.star_level.asc(),
        )
        page = ranking_page_with_deltas(
            conn,
            page_results(query, UNIT_STAT_FIELDS, ordering, range),
            scope_id=scope_id,
            population_condition=population_condition,
            entity_kind="unit",
            group_by=dimensions,
        )
        return population_table_result(
            page,
            population_boards=universe,
            group_by=dimensions,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    return await run_db_tool(ctx, read, log_ranking=True)


@function_tool(strict_mode=True, timeout=TOOL_TIMEOUT_SECONDS)
async def rank_items(
    ctx: ToolContext[Any],
    item_type: Optional[ItemTypes] = None,
    holder: Optional[StoredName] = None,
    group_by_holder: bool = False,
    min_sample: Optional[SampleSize] = None,
    max_sample: Optional[SampleSize] = None,
    sort_by: ItemSortMetric = "boards",
    sort_direction: SortDirection = "auto",
    range: ResultRange = [0, 10],
) -> dict[str, Any]:
    """Rank items by family, overall, or for one exact stored holder name.

    Omit ``holder`` for item-overall rows. Set ``group_by_holder`` to rank all
    holder-specific rows; a supplied holder always selects holder rows. Set
    ``item_type`` to restrict the ranking to one classified item family.
    Rows include lower-is-better ``delta`` within the active population and
    ``relative_delta`` for the same item grain inside versus outside it.

    Args:
        ctx: Agents SDK tool context.
        item_type: Optional exact item-family classification.
        holder: Optional exact stored holder name.
        group_by_holder: Whether to return holder-specific rows.
        min_sample: Optional minimum contributing board count.
        max_sample: Optional maximum contributing board count.
        sort_by: Default ranking metric.
        sort_direction: Default ranking direction.
        range: Zero-based, end-exclusive result slice.

    Returns:
        A validated table result with item rows, context, warnings, and page.
    """

    def read(conn: Any) -> dict[str, Any]:
        """Execute the item ranking against the selected aggregate source.

        Args:
            conn: Worker-thread SQLAlchemy session.

        Returns:
            Validated item table or structured error result.
        """
        if error := sample_bounds_error(min_sample, max_sample):
            return error

        context = ranking_board_context(conn)
        if isinstance(context, dict):
            return context
        _, universe, _, population_condition, scope_id = context
        dimensions = ["item_name"]
        if holder is not None or group_by_holder:
            dimensions.append("unit_name")
        query = conn.query(ItemStatQueryTable).filter(
            ItemStatQueryTable.scope_id == scope_id
        )
        if item_type is not None:
            query = query.filter(ItemStatQueryTable.item_type == str(item_type))
        # Holder-specific and all-holder rows coexist in one projection. Keep
        # them mutually exclusive so a ranking never mixes grains.
        if holder:
            query = query.filter(
                ItemStatQueryTable.unit_name != ITEM_OVERALL_UNIT_NAME,
            )
            query = query.filter(ItemStatQueryTable.unit_name == holder)
        elif group_by_holder:
            query = query.filter(
                ItemStatQueryTable.unit_name != ITEM_OVERALL_UNIT_NAME
            )
        else:
            query = query.filter(
                ItemStatQueryTable.unit_name == ITEM_OVERALL_UNIT_NAME
            )
        query = apply_sample_bounds(
            query,
            ItemStatQueryTable,
            min_sample,
            max_sample,
            sample_column="boards",
        )
        ordering = order_columns(
            ItemStatQueryTable,
            sort_by,
            sort_direction,
            ItemStatQueryTable.item_name.asc(),
            ItemStatQueryTable.unit_name.asc(),
        )
        page = ranking_page_with_deltas(
            conn,
            page_results(query, ITEM_STAT_FIELDS, ordering, range),
            scope_id=scope_id,
            population_condition=population_condition,
            entity_kind="item",
            group_by=dimensions,
        )
        return population_table_result(
            page,
            population_boards=universe,
            group_by=dimensions,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    return await run_db_tool(ctx, read, log_ranking=True)


@function_tool(strict_mode=True, timeout=TOOL_TIMEOUT_SECONDS)
async def rank_traits(
    ctx: ToolContext[Any],
    tier: Optional[TraitTier] = None,
    group_by_tier: bool = False,
    unit: Optional[StoredName] = None,
    min_sample: Optional[SampleSize] = None,
    max_sample: Optional[SampleSize] = None,
    sort_by: SortMetric = "games",
    sort_direction: SortDirection = "auto",
    range: ResultRange = [0, 10],
) -> dict[str, Any]:
    """Rank trait rollups or medal tiers on boards with an optional unit.

    By default results use the across-tiers rollup. Set ``group_by_tier`` to
    rank every medal tier, or provide ``tier`` for one medal.
    Rows include lower-is-better ``delta`` within the selected population and
    ``relative_delta`` for the same trait grain inside versus outside it.

    Args:
        ctx: Agents SDK tool context.
        tier: Optional named activation tier (Bronze, Silver, Unique, Gold,
            or Prismatic). Inactive traits are excluded from rankings.
        group_by_tier: Whether to return separate medal-tier rows.
        unit: Optional unit required on the same board. The unit need not
            contribute to a ranked trait.
        min_sample: Optional minimum contributing board count.
        max_sample: Optional maximum contributing board count.
        sort_by: Default ranking metric.
        sort_direction: Default ranking direction.
        range: Zero-based, end-exclusive result slice.

    Returns:
        A validated table result with trait rows, context, warnings, and page.
    """

    def read(conn: Any) -> dict[str, Any]:
        """Execute the trait ranking against the selected aggregate source.

        Args:
            conn: Worker-thread SQLAlchemy session.

        Returns:
            Validated trait table or structured error result.
        """
        if error := sample_bounds_error(min_sample, max_sample):
            return error

        context = ranking_board_context(conn, unit=unit)
        if isinstance(context, dict):
            return context
        boards, universe, population, population_condition, scope_id = context
        dimensions = ["trait_name"]
        if tier is not None or group_by_tier:
            dimensions.append("tier")
        if unit is not None or tier is not None or group_by_tier:
            trait = aliased(AnalysisBoardTrait)
            # Medal tiers must come from styles on anonymous facts: different
            # breakpoint indices can share a medal, even for the same trait.
            chosen_tier = (
                trait_tier_expression(trait.style)
                if tier is not None or group_by_tier
                else literal("All")
            )
            grain_query = (
                select(
                    boards.c.board_key,
                    boards.c.placement,
                    trait.trait_name,
                    chosen_tier.label("tier"),
                )
                .join(
                    trait,
                    and_(
                        trait.scope_id == boards.c.scope_id,
                        trait.board_key == boards.c.board_key,
                    ),
                )
                # Only activated traits belong in public trait statistics.
                .where(
                    func.coalesce(trait.style, 0) > 0,
                    func.coalesce(trait.tier_current, 0) > 0,
                )
            )
            if tier is not None:
                grain_query = grain_query.where(trait_tier_expression(trait.style) == tier)
            grain = grain_query.distinct().subquery()
            avg_placement, top4_rate, win_rate = outcome_expressions(
                grain.c.placement
            )
            games = func.count(func.distinct(grain.c.board_key))
            statement = select(
                grain.c.trait_name,
                grain.c.tier,
                games.label("games"),
                avg_placement.label("avg_placement"),
                top4_rate.label("top4_rate"),
                win_rate.label("win_rate"),
                (games * 1.0 / max(universe, 1)).label("pick_rate"),
                literal(universe).label("universe_games"),
            ).group_by(grain.c.trait_name, grain.c.tier)
            page = ranking_page_with_deltas(
                conn,
                conditional_page(
                    conn,
                    statement,
                    TRAIT_STAT_FIELDS,
                    sample_field="games",
                    min_sample=min_sample,
                    max_sample=max_sample,
                    sort_by=sort_by,
                    sort_direction=sort_direction,
                    tie_fields=("trait_name", "tier"),
                    row_range=range,
                ),
                scope_id=scope_id,
                population_condition=population_condition,
                entity_kind="trait",
                group_by=dimensions,
            )
            return population_table_result(
                page,
                population=population,
                population_boards=universe,
                group_by=dimensions,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
        query = conn.query(TraitStatQueryTable).filter(
            TraitStatQueryTable.scope_id == scope_id
        )
        # Only the all-tier rollup can use the breakpoint-based projection.
        query = query.filter(TraitStatQueryTable.tier == ALL_TRAIT_TIERS)
        query = apply_sample_bounds(
            query,
            TraitStatQueryTable,
            min_sample,
            max_sample,
            sample_column="games",
        )
        ordering = order_columns(
            TraitStatQueryTable,
            sort_by,
            sort_direction,
            TraitStatQueryTable.trait_name.asc(),
            TraitStatQueryTable.tier.asc(),
        )
        page = ranking_page_with_deltas(
            conn,
            page_results(query, TRAIT_STAT_FIELDS, ordering, range),
            scope_id=scope_id,
            population_condition=population_condition,
            entity_kind="trait",
            group_by=dimensions,
        )
        for row in page["results"]:
            row["tier"] = "All"
        return population_table_result(
            page,
            population_boards=universe,
            group_by=dimensions,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    return await run_db_tool(ctx, read, log_ranking=True)


@function_tool(strict_mode=True, timeout=TOOL_TIMEOUT_SECONDS)
async def rank_unit_loadouts(
    ctx: ToolContext[Any],
    unit: Optional[StoredName] = None,
    item_1: Optional[StoredName] = None,
    item_2: Optional[StoredName] = None,
    trait: Optional[StoredName] = None,
    item_count: Optional[LoadoutItemCount] = None,
    star_level: Optional[StarLevel] = None,
    group_by_star_level: bool = False,
    min_sample: Optional[SampleSize] = None,
    max_sample: Optional[SampleSize] = None,
    sort_by: LoadoutSortMetric = "boards",
    sort_direction: SortDirection = "auto",
    range: ResultRange = [0, 10],
) -> dict[str, Any]:
    """Rank canonical loadouts using only exact stored entity names.

    Each supplied item must match a distinct loadout slot, so duplicate terms
    can find duplicate-item builds. A trait restricts results to boards where
    that trait is active. Omit ``star_level`` for the across-stars rollup, or
    set ``group_by_star_level`` for exact-star rows.
    Rows include lower-is-better ``delta`` within the selected population and
    ``relative_delta`` for the same loadout grain inside versus outside it.

    Args:
        ctx: Agents SDK tool context.
        unit: Optional exact stored holder name.
        item_1: Optional first exact stored item condition.
        item_2: Optional second exact stored item condition.
        trait: Optional active trait required on the same board.
        item_count: Optional exact completed-item count.
        star_level: Optional exact holder star bucket.
        group_by_star_level: Whether to return exact-star rows.
        min_sample: Optional minimum contributing board count.
        max_sample: Optional maximum contributing board count.
        sort_by: Default ranking metric.
        sort_direction: Default ranking direction.
        range: Zero-based, end-exclusive result slice.

    Returns:
        A validated table result with loadout rows, context, warnings, and page.
    """

    def read(conn: Any) -> dict[str, Any]:
        """Execute the loadout ranking against the selected aggregate source.

        Args:
            conn: Worker-thread SQLAlchemy session.

        Returns:
            Validated loadout table or structured error result.
        """
        if error := sample_bounds_error(min_sample, max_sample):
            return error

        context = ranking_board_context(conn, trait=trait)
        if isinstance(context, dict):
            return context
        boards, universe, population, population_condition, scope_id = context
        dimensions = ["unit_name", "loadout_key"]
        if star_level is not None or group_by_star_level:
            dimensions.insert(1, "star_level")
        requested_items = [item for item in (item_1, item_2) if item is not None]
        if trait is not None:
            unit_fact = aliased(AnalysisBoardUnit)
            # Project the rollup sentinel over anonymous board facts so filtered
            # and precomputed results expose the same star-level key.
            chosen_star = (
                unit_fact.star_level
                if star_level is not None or group_by_star_level
                else literal(ALL_STARS)
            )
            unit_grain_query = select(
                boards.c.board_key,
                unit_fact.unit_name,
                chosen_star.label("star_level"),
            ).join(
                unit_fact,
                and_(
                    unit_fact.scope_id == boards.c.scope_id,
                    unit_fact.board_key == boards.c.board_key,
                ),
            )
            if star_level is not None:
                unit_grain_query = unit_grain_query.where(unit_fact.star_level == star_level)
            if unit:
                unit_grain_query = unit_grain_query.where(unit_fact.unit_name == unit)
            unit_grain = unit_grain_query.distinct().subquery()
            # Count all eligible boards before item filters are applied;
            # otherwise loadout frequency would divide by the matched build.
            denominators = (
                select(
                    unit_grain.c.unit_name,
                    unit_grain.c.star_level,
                    func.count().label("unit_boards"),
                )
                .group_by(unit_grain.c.unit_name, unit_grain.c.star_level)
                .subquery()
            )
            loadout_query = (
                select(
                    boards.c.board_key,
                    boards.c.placement,
                    unit_fact.unit_name,
                    chosen_star.label("star_level"),
                    unit_fact.loadout_key,
                    unit_fact.completed_item_count.label("item_count"),
                    unit_fact.item_1,
                    unit_fact.item_2,
                    unit_fact.item_3,
                )
                .join(
                    unit_fact,
                    and_(
                        unit_fact.scope_id == boards.c.scope_id,
                        unit_fact.board_key == boards.c.board_key,
                    ),
                )
                .where(unit_fact.completed_item_count > 0)
            )
            if unit:
                loadout_query = loadout_query.where(unit_fact.unit_name == unit)
            if star_level is not None:
                loadout_query = loadout_query.where(unit_fact.star_level == star_level)
            if item_count is not None:
                loadout_query = loadout_query.where(unit_fact.completed_item_count == item_count)
            if requested_items:
                columns = (unit_fact.item_1, unit_fact.item_2, unit_fact.item_3)
                loadout_query = loadout_query.where(
                    loadout_contains_items(columns, requested_items)
                )
            grain = loadout_query.distinct().subquery()
            avg_placement, top4_rate, win_rate = outcome_expressions(
                grain.c.placement
            )
            board_count = func.count(func.distinct(grain.c.board_key))
            statement = (
                select(
                    grain.c.unit_name,
                    grain.c.star_level,
                    grain.c.loadout_key,
                    grain.c.item_count,
                    grain.c.item_1,
                    grain.c.item_2,
                    grain.c.item_3,
                    board_count.label("boards"),
                    avg_placement.label("avg_placement"),
                    top4_rate.label("top4_rate"),
                    win_rate.label("win_rate"),
                    denominators.c.unit_boards,
                    (
                        board_count * 1.0 / func.nullif(denominators.c.unit_boards, 0)
                    ).label(
                        "loadout_pick_rate"
                    ),
                )
                .join(
                    denominators,
                    and_(
                        denominators.c.unit_name == grain.c.unit_name,
                        denominators.c.star_level == grain.c.star_level,
                    ),
                )
                .group_by(
                    grain.c.unit_name,
                    grain.c.star_level,
                    grain.c.loadout_key,
                    grain.c.item_count,
                    grain.c.item_1,
                    grain.c.item_2,
                    grain.c.item_3,
                    denominators.c.unit_boards,
                )
            )
            page = ranking_page_with_deltas(
                conn,
                conditional_page(
                    conn,
                    statement,
                    LOADOUT_STAT_FIELDS,
                    sample_field="boards",
                    min_sample=min_sample,
                    max_sample=max_sample,
                    sort_by=sort_by,
                    sort_direction=sort_direction,
                    tie_fields=("unit_name", "star_level", "loadout_key"),
                    row_range=range,
                ),
                scope_id=scope_id,
                population_condition=population_condition,
                entity_kind="unit_loadout",
                group_by=dimensions,
                required_items=requested_items,
            )
            return population_table_result(
                page,
                population=population,
                population_boards=universe,
                group_by=dimensions,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
        query = conn.query(UnitLoadoutStatQueryTable).filter(
            UnitLoadoutStatQueryTable.scope_id == scope_id
        )
        if unit:
            query = query.filter(UnitLoadoutStatQueryTable.unit_name == unit)
        if star_level is not None:
            query = query.filter(UnitLoadoutStatQueryTable.star_level == star_level)
        elif group_by_star_level:
            query = query.filter(UnitLoadoutStatQueryTable.star_level != ALL_STARS)
        else:
            query = query.filter(UnitLoadoutStatQueryTable.star_level == ALL_STARS)
        if item_count is not None:
            query = query.filter(UnitLoadoutStatQueryTable.item_count == item_count)
        if requested_items:
            item_columns = (
                UnitLoadoutStatQueryTable.item_1,
                UnitLoadoutStatQueryTable.item_2,
                UnitLoadoutStatQueryTable.item_3,
            )
            query = query.filter(
                loadout_contains_items(item_columns, requested_items)
            )
        query = apply_sample_bounds(
            query,
            UnitLoadoutStatQueryTable,
            min_sample,
            max_sample,
            sample_column="boards",
        )
        ordering = order_columns(
            UnitLoadoutStatQueryTable,
            sort_by,
            sort_direction,
            UnitLoadoutStatQueryTable.unit_name.asc(),
            UnitLoadoutStatQueryTable.star_level.asc(),
            UnitLoadoutStatQueryTable.loadout_key.asc(),
        )
        page = ranking_page_with_deltas(
            conn,
            page_results(query, LOADOUT_STAT_FIELDS, ordering, range),
            scope_id=scope_id,
            population_condition=population_condition,
            entity_kind="unit_loadout",
            group_by=dimensions,
            required_items=requested_items,
        )
        return population_table_result(
            page,
            population_boards=universe,
            group_by=dimensions,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    return await run_db_tool(ctx, read, log_ranking=True)


RANKING_TOOL_GROUP = AssistantToolGroup(
    key="ranking",
    label="Ranking Tools",
    description=(
        "Bounded name resolution and rankings over units, items, and traits."
    ),
    tools=(
        resolve_tft_names,
        rank_units,
        rank_items,
        rank_traits,
        rank_unit_loadouts,
    ),
)

__all__ = [
    "RANKING_TOOL_GROUP",
    "rank_items",
    "rank_traits",
    "rank_unit_loadouts",
    "rank_units",
    "resolve_tft_names",
]
