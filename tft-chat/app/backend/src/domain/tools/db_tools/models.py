"""Validated input models and bounded type aliases for database tools."""

from __future__ import annotations

from typing import Annotated, Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .utils import (
    count_filter_group_predicates,
    has_filter_group_predicates,
    validate_range,
)


StoredName = Annotated[str, Field(min_length=1, max_length=160)]
StoredNames = Annotated[List[StoredName], Field(min_length=1, max_length=24)]
TraitTier = Literal["Bronze", "Silver", "Unique", "Gold", "Prismatic"]
MAX_FILTER_GROUP_PREDICATES = 64
ANALYSIS_RESULT_CONTRACT = "analysis.v1"


class StrictToolModel(BaseModel):
    """Reject unknown fields for every database-tool request model.

    This base model is applied to cohort filters so model-generated arguments
    cannot silently introduce unsupported query dimensions.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StrictResultModel(BaseModel):
    """Reject undeclared fields in model-facing investigation results.

    Database tools construct these models immediately before returning so
    compatibility fields and private query metadata cannot cross the
    model-facing boundary.
    """

    model_config = ConfigDict(extra="forbid")


class AnalysisWarning(StrictResultModel):
    """Describe one non-fatal condition affecting result interpretation."""

    code: str
    message: str


class AnalysisSort(StrictResultModel):
    """Describe one effective ordering rule for a tabular result."""

    metric: str
    direction: Literal["asc", "desc"]


class AnalysisPage(StrictResultModel):
    """Describe one bounded zero-based result page."""

    offset: int = Field(ge=0)
    count: int = Field(ge=0)
    has_more: bool


class AnalysisTableContext(StrictResultModel):
    """Explain the population, grain, ordering, and privacy floor of a table."""

    population: str
    population_boards: Optional[int] = Field(default=None, ge=0)
    group_by: List[str]
    sort: List[AnalysisSort]
    minimum_reportable_boards: int = Field(ge=1)


class AnalysisTableResult(StrictResultModel):
    """Return object-keyed rows with stable context and pagination metadata."""

    kind: Literal["table"] = "table"
    context: AnalysisTableContext
    results: List[dict[str, Any]]
    page: AnalysisPage
    warnings: List[AnalysisWarning] = Field(default_factory=list)


class AnalysisResolutionContext(StrictResultModel):
    """Describe privacy behavior for stored-name candidate counts."""

    minimum_reportable_boards: int = Field(ge=1)


class AnalysisResolutionMatch(StrictResultModel):
    """Describe one stored TFT identifier matching a player-language query."""

    name: str
    kind: Literal["unit", "item", "trait"]
    match: Literal["exact", "substring", "fuzzy"]
    boards: Optional[int] = Field(default=None, ge=0)
    count_suppressed: bool


class AnalysisResolutionEntry(StrictResultModel):
    """Return candidates and resolution status for one submitted name."""

    query: str
    matches: List[AnalysisResolutionMatch]
    resolved: bool


class AnalysisResolutionResult(StrictResultModel):
    """Return bounded stored-name resolutions through the shared result family."""

    kind: Literal["resolution"] = "resolution"
    context: AnalysisResolutionContext
    results: List[AnalysisResolutionEntry]
    warnings: List[AnalysisWarning] = Field(default_factory=list)


class AnalysisConfidenceInterval(StrictResultModel):
    """Represent the lower and upper bounds of a 95 percent interval."""

    lower: float
    upper: float


class AnalysisEffect(StrictResultModel):
    """Describe one target-minus-baseline cohort effect estimate."""

    metric: Literal["avg_placement", "top4_rate", "win_rate"]
    estimate: float
    cluster_robust_standard_error: Optional[float] = Field(default=None, ge=0)
    confidence_interval_95: Optional[AnalysisConfidenceInterval] = None


class AnalysisCohortSummary(StrictResultModel):
    """Describe reportable placement outcomes for one comparison cohort."""

    label: str
    boards: Optional[int] = Field(default=None, ge=0)
    suppressed: bool
    minimum_boards: Optional[int] = Field(default=None, ge=1)
    avg_placement: Optional[float] = None
    placement_stddev: Optional[float] = Field(default=None, ge=0)
    top4_rate: Optional[float] = Field(default=None, ge=0, le=1)
    win_rate: Optional[float] = Field(default=None, ge=0, le=1)
    histogram: Optional[dict[str, int]] = None


class AnalysisOverlap(StrictResultModel):
    """Describe whether and how many boards satisfy both explicit cohorts."""

    boards: Optional[int] = Field(default=None, ge=0)
    suppressed: bool


class AnalysisComparisonContext(StrictResultModel):
    """Explain comparison scope and effect-estimate semantics."""

    shared_population: Optional[str] = None
    effect_operation: Literal["target_minus_baseline"] = "target_minus_baseline"
    analysis_type: Literal["observational_association"] = "observational_association"
    minimum_reportable_boards: int = Field(ge=1)


class AnalysisComparisonResult(StrictResultModel):
    """Return cohort summaries and aligned effect estimates."""

    kind: Literal["comparison"] = "comparison"
    context: AnalysisComparisonContext
    target: AnalysisCohortSummary
    baseline: AnalysisCohortSummary
    effects: List[AnalysisEffect]
    overlap: AnalysisOverlap
    warnings: List[AnalysisWarning] = Field(default_factory=list)


class AnalysisErrorDetail(StrictResultModel):
    """Describe one bounded investigation failure and retry policy."""

    code: str
    message: str
    retryable: bool
    timeout_seconds: Optional[float] = Field(default=None, ge=0)


class AnalysisErrorResult(StrictResultModel):
    """Return a machine-readable failure through the investigation contract."""

    kind: Literal["error"] = "error"
    context: dict[str, Any] = Field(default_factory=dict)
    error: AnalysisErrorDetail
    warnings: List[AnalysisWarning] = Field(default_factory=list)


AnalysisResult = (
    AnalysisTableResult
    | AnalysisResolutionResult
    | AnalysisComparisonResult
    | AnalysisErrorResult
)


class UnitCondition(StrictToolModel):
    """Require a named unit and optionally constrain its board occurrences.

    ``FilterGroup`` uses this model in ``compare_cohorts`` and
    ``query_cohort``. A condition with only ``name`` populated means the unit
    must appear at least once; its star level, item count, and additional
    copies remain unconstrained.
    """

    name: StoredName = Field(
        description=(
            "Exact stored unit name. By itself, requires at least one copy at "
            "any star level and with any completed-item count."
        )
    )
    star_level: Optional[Annotated[int, Field(ge=1, le=4)]] = None
    min_copies: Annotated[int, Field(ge=0, le=16)] = 1
    max_copies: Optional[Annotated[int, Field(ge=0, le=16)]] = None
    min_completed_items: Optional[Annotated[int, Field(ge=0, le=3)]] = None
    max_completed_items: Optional[Annotated[int, Field(ge=0, le=3)]] = None

    @model_validator(mode="after")
    def validate_ranges(self) -> "UnitCondition":
        """Reject inverted copy and completed-item ranges.

        Returns:
            The validated unit condition.
        """
        validate_range(self.min_copies, self.max_copies, "unit copies")
        validate_range(
            self.min_completed_items,
            self.max_completed_items,
            "unit completed items",
        )
        return self


class ItemCondition(StrictToolModel):
    """Require a named item and optionally constrain its holder or copies.

    Cohort tools apply this model to anonymous board-item facts, optionally
    joined to a named holder and star level. A
    condition with only ``name`` populated means the item must appear at least
    once on any holder at any star level.
    """

    name: StoredName = Field(
        description=(
            "Exact stored item name. By itself, requires at least one copy on "
            "any holder at any star level."
        )
    )
    holder: Optional[StoredName] = None
    holder_star_level: Optional[Annotated[int, Field(ge=1, le=4)]] = None
    min_copies: Annotated[int, Field(ge=0, le=24)] = 1
    max_copies: Optional[Annotated[int, Field(ge=0, le=24)]] = None

    @model_validator(mode="after")
    def validate_ranges(self) -> "ItemCondition":
        """Validate holder dependencies and copy bounds.

        Returns:
            The validated item condition.

        Raises:
            ValueError: If a holder star is provided without a holder or a
                minimum exceeds its maximum.
        """

        if self.holder_star_level is not None and self.holder is None:
            raise ValueError("holder_star_level requires holder")
        validate_range(self.min_copies, self.max_copies, "item copies")
        return self


class TraitCondition(StrictToolModel):
    """Require a named trait and optionally constrain its activation details.

    Cohort compilation applies these fields to anonymous board-trait facts,
    including the named active tier, numeric style, and contributing-unit count. A
    condition with only ``name`` populated means the trait must be active at
    any active tier, style, and contributing-unit count.
    """

    name: StoredName = Field(
        description=(
            "Exact stored trait name. By itself, requires the trait to be "
            "active at any tier, style, and contributing-unit count."
        )
    )
    active: bool = True
    tier: Optional[TraitTier] = None
    style: Optional[Annotated[int, Field(ge=0, le=20)]] = None
    total_tier: Optional[Annotated[int, Field(ge=0, le=20)]] = None
    min_contributing_units: Optional[
        Annotated[int, Field(ge=0, le=20)]
    ] = None
    max_contributing_units: Optional[
        Annotated[int, Field(ge=0, le=20)]
    ] = None

    @model_validator(mode="after")
    def validate_ranges(self) -> "TraitCondition":
        """Reject an inverted contributing-unit range.

        Returns:
            The validated trait condition.
        """

        validate_range(
            self.min_contributing_units,
            self.max_contributing_units,
            "trait contributing units",
        )
        return self


class CohortOrderRule(StrictToolModel):
    """Choose one result-ordering key for grouped cohort output.

    ``query_cohort`` applies up to three of these rules before stable dimension
    tie breakers.
    """

    metric: Literal[
        "distinct_boards",
        "distinct_lobbies",
        "avg_placement",
        "top4_rate",
        "win_rate",
        "pick_rate",
    ]
    direction: Literal["asc", "desc"] = "desc"


class FilterGroup(StrictToolModel):
    """Define structured entity and player-level predicates for one cohort.

    Every populated condition is conjunctive. Name-only entity conditions are
    presence requirements, while omitted optional attributes are unconstrained.
    """

    unit_conditions: Optional[
        Annotated[List[UnitCondition], Field(max_length=24)]
    ] = None
    item_conditions: Optional[
        Annotated[List[ItemCondition], Field(max_length=24)]
    ] = None
    trait_conditions: Optional[
        Annotated[List[TraitCondition], Field(max_length=24)]
    ] = None
    level: Optional[Annotated[int, Field(ge=1, le=20)]] = None
    min_level: Optional[Annotated[int, Field(ge=1, le=20)]] = None
    max_level: Optional[Annotated[int, Field(ge=1, le=20)]] = None

    @model_validator(mode="after")
    def validate_filter_group(self) -> "FilterGroup":
        """Normalize names and enforce nonempty, bounded cohort filters.

        Returns:
            The normalized filter group.

        Raises:
            ValueError: If the group is empty, has an inverted level range, or
                exceeds the predicate limit.
        """

        validate_range(self.min_level, self.max_level, "level")
        if not has_filter_group_predicates(self):
            raise ValueError("Filter groups must be nonempty.")
        total = count_filter_group_predicates(self)
        if total > MAX_FILTER_GROUP_PREDICATES:
            raise ValueError(
                "A filter group may compile at most "
                f"{MAX_FILTER_GROUP_PREDICATES} predicates."
            )
        return self


__all__ = [
    "ANALYSIS_RESULT_CONTRACT",
    "AnalysisCohortSummary",
    "AnalysisComparisonContext",
    "AnalysisComparisonResult",
    "AnalysisConfidenceInterval",
    "AnalysisEffect",
    "AnalysisErrorDetail",
    "AnalysisErrorResult",
    "AnalysisOverlap",
    "AnalysisPage",
    "AnalysisResolutionContext",
    "AnalysisResolutionEntry",
    "AnalysisResolutionMatch",
    "AnalysisResolutionResult",
    "AnalysisResult",
    "AnalysisSort",
    "AnalysisTableContext",
    "AnalysisTableResult",
    "AnalysisWarning",
    "CohortOrderRule",
    "FilterGroup",
    "ItemCondition",
    "MAX_FILTER_GROUP_PREDICATES",
    "StoredName",
    "StoredNames",
    "StrictToolModel",
    "TraitCondition",
    "UnitCondition",
]
