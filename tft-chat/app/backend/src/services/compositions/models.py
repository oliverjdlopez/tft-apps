"""Validated HTTP contracts for the private composition workspace."""

from typing import Literal, Annotated, Any
from pydantic import Field, model_validator
from domain.compositions.models import (
    CompositionModel,
    EntityRef,
    TraitObservation,
    BoardObservation,
    BoardOutcome,
    BoardAssignment,
    FamilyDefinition,
    StructuralPattern,
    FamilyProfile,
    Count,
    Identifier,
    Rate,
    FrozenModel,
    Diagnostics,
)


class CompositionContext(CompositionModel):
    """Identify the saved source and algorithm without exposing database identities."""

    source_kind: Literal["fixture", "experiment"]
    population_kind: Literal["discovery_sample", "full_population"]
    patch: Identifier
    set_number: Count
    queue_id: Count
    snapshot_revision: Identifier
    taxonomy_revision: Identifier
    feature_revision: Identifier
    algorithm_id: Identifier | None
    algorithm_version: Identifier | None
    experiment_id: Identifier | None


class BoardExampleView(CompositionModel):
    """Combine already-classified boards with separately computed display outcomes."""

    board: BoardObservation
    outcome: BoardOutcome | None
    assignment: BoardAssignment | None
    is_representative: Annotated[bool, Field(strict=True)]


class FamilyPatternPreview(CompositionModel):
    """Show at most six units and traits from the first representative structure."""

    pattern: StructuralPattern
    omitted_requirements: Count
    alternative_patterns: Count

    @model_validator(mode="after")
    def bounded_requirements(self) -> "FamilyPatternPreview":
        """Keep family navigation previews bounded across units and traits."""
        if len(self.pattern.units) + len(self.pattern.traits) > 6:
            raise ValueError("A family preview may contain at most six requirements")
        return self


class FamilySummaryView(CompositionModel):
    """Provide the bounded family-list projection."""

    family_id: Identifier
    label: Identifier
    description: str
    assigned_boards: Count
    eligible_population_boards: Count
    play_share: Rate | None
    variation_count: Count
    preview: FamilyPatternPreview | None

    @model_validator(mode="after")
    def denominator(self):
        """Preserve valid prevalence denominators in the compact list view."""
        n = self.eligible_population_boards
        if (
            self.assigned_boards > n
            or (not n and self.play_share is not None)
            or (
                n
                and (
                    self.play_share is None
                    or abs(self.play_share - self.assigned_boards / n) > 1e-9
                )
            )
        ):
            raise ValueError("Invalid family summary denominator")
        return self


class CompositionWarning(CompositionModel):
    """Expose a safe actionable warning to the workspace."""

    code: Identifier
    message: str


class CompositionListResponse(CompositionModel):
    """Version the family-list wire contract."""

    schema_version: Literal["composition.v1"]
    context: CompositionContext
    families: tuple[FamilySummaryView, ...]
    warnings: tuple[CompositionWarning, ...]


class CompositionDetailResponse(CompositionModel):
    """Version the complete family display wire contract."""

    schema_version: Literal["composition.v1"]
    context: CompositionContext
    family: FamilyDefinition
    profile: FamilyProfile | None
    examples: tuple[BoardExampleView, ...]
    warnings: tuple[CompositionWarning, ...]


class ExperimentRequest(CompositionModel):
    """Freeze reproducible source selection and algorithm settings before queueing."""

    algorithm_id: Identifier
    algorithm_version: Identifier | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    seed: int = Field(default=42, ge=0, le=2147483647, strict=True)
    sample_size: int = Field(default=2000, ge=1, strict=True)
    full_population: Annotated[bool, Field(strict=True)] = False
    source_kind: Literal["active", "fixture"] = "active"
    snapshot_id: Identifier | None = None


class SnapshotData(CompositionModel):
    """Persist input observations separately from outcomes and sampling identity."""

    context: CompositionContext
    boards: tuple[BoardObservation, ...]
    outcomes: tuple[BoardOutcome, ...]
    sample_ids: tuple[Identifier, ...]
    eligible_boards: Count
    includes_full_population: bool
    sampling_seed: int
    requested_sample_size: int

    @model_validator(mode="after")
    def references(self):
        """Reject incomplete, duplicated, or cross-snapshot anonymous references."""
        ids = {b.observation_id for b in self.boards}
        if (
            len(ids) != len(self.boards)
            or len(set(self.sample_ids)) != len(self.sample_ids)
            or not set(self.sample_ids) <= ids
        ):
            raise ValueError("Invalid snapshot observation references")
        if len(self.boards) > self.eligible_boards or (
            self.includes_full_population and len(self.boards) != self.eligible_boards
        ):
            raise ValueError("Snapshot population does not match its denominator")
        if len({o.observation_id for o in self.outcomes}) != len(self.outcomes) or any(
            o.observation_id not in ids for o in self.outcomes
        ):
            raise ValueError("Invalid snapshot outcome references")
        return self


class PopulationResult(CompositionModel):
    """Keep sample and full-population assignments and statistics separate."""

    population_kind: Literal["discovery_sample", "full_population"]
    assignments: tuple[BoardAssignment, ...]
    profiles: tuple[FamilyProfile, ...]
    coverage: Rate | None
    ambiguity: Rate | None


class ExperimentResult(CompositionModel):
    """Store frozen fitted state, native discovery labels, and classified populations."""

    model: FrozenModel
    diagnostics: Diagnostics
    discovery_assignments: tuple[BoardAssignment, ...]
    populations: tuple[PopulationResult, ...]


class SnapshotSummary(CompositionModel):
    """Retain the small snapshot fields needed by run views and reuse checks.

    Stored once per snapshot so history, polling, and reruns never load or
    validate the frozen board payload.
    """

    context: CompositionContext
    eligible_boards: Count
    sample_boards: Count
    includes_full_population: bool
    sampling_seed: int
    requested_sample_size: int


class AssignmentSummary(CompositionModel):
    """Identify one board's classification for run-level browsing.

    Candidate scores and evidence stay in the per-board inspection response.
    """

    observation_id: Identifier
    status: Literal["assigned", "ambiguous", "unclassified"]
    family_id: Identifier | None
    variation_id: Identifier | None


class ModelSummary(CompositionModel):
    """Expose a frozen model's families and settings without fitted algorithm state."""

    schema_version: Literal["adapter.v1"] = "adapter.v1"
    algorithm_id: Identifier
    algorithm_version: Identifier
    feature_revision: Literal["structure.v1"] = "structure.v1"
    effective_parameters: dict[str, Any]
    families: tuple[FamilyDefinition, ...]


class PopulationSummary(CompositionModel):
    """Project a classified population for the run view using compact assignments."""

    population_kind: Literal["discovery_sample", "full_population"]
    assignments: tuple[AssignmentSummary, ...]
    profiles: tuple[FamilyProfile, ...]
    coverage: Rate | None
    ambiguity: Rate | None


class ExperimentResultView(CompositionModel):
    """Bound a saved result to the fields the workspace renders for a whole run.

    Fitted state and native discovery labels exist only for reproducibility and
    can be tens of megabytes, so they never leave the service layer.
    """

    model: ModelSummary
    diagnostics: Diagnostics
    populations: tuple[PopulationSummary, ...]


class SavedResult(CompositionModel):
    """Hold one completed run's immutable display inputs for repeated projections.

    Applied by the display service, which caches these per experiment so family
    and board navigation does not revalidate the stored result on every click.
    """

    experiment_id: Identifier
    snapshot_id: Identifier
    request: ExperimentRequest
    context: CompositionContext
    elapsed_seconds: float = Field(ge=0)
    algorithm_id: Identifier
    algorithm_version: Identifier
    families: tuple[FamilyDefinition, ...]
    populations: tuple[PopulationResult, ...]


class ExperimentView(CompositionModel):
    """Expose persistent run state without source database or worker identifiers."""

    experiment_id: Identifier
    snapshot_id: Identifier
    created_at: str
    status: Literal[
        "queued", "running", "completed", "cancelled", "interrupted", "failed"
    ]
    stage: str
    elapsed_seconds: float = Field(ge=0)
    request: ExperimentRequest
    context: CompositionContext
    eligible_boards: Count
    sample_boards: Count
    error: str | None
    result: ExperimentResultView | None


class ExperimentHistory(CompositionModel):
    """Bound the run-history response while retaining all runs in storage."""

    experiments: tuple[ExperimentView, ...]


class AlgorithmView(CompositionModel):
    """Expose the supported algorithm's validated form and version."""

    algorithm_id: Identifier
    algorithm_version: Identifier
    parameter_schema: dict[str, Any]


class AlgorithmList(CompositionModel):
    """Describe the singleton algorithm catalog through a stable frontend boundary."""

    algorithms: tuple[AlgorithmView, ...]


class ComparisonMetrics(CompositionModel):
    """Expose directly comparable structural coverage and runtime measurements."""

    family_count: Count
    eligible_boards: Count
    coverage: Rate | None
    ambiguity: Rate | None
    elapsed_seconds: float = Field(ge=0)


class ComparisonResponse(CompositionModel):
    """Compare configuration and label-invariant overlap on identical populations."""

    left_id: Identifier
    right_id: Identifier
    identical_population: bool
    left_metrics: ComparisonMetrics
    right_metrics: ComparisonMetrics
    configuration_differences: dict[str, Any]
    assignment_overlap: Rate | None
    adjusted_rand_index: float | None
    message: str


class SourceSummary(CompositionModel):
    """Describe source readiness before capture without exposing scope identifiers."""

    source_kind: Literal["active", "fixture"]
    ready: bool
    patch: str | None
    set_number: Count | None
    queue_id: Count | None
    eligible_boards: Count | None
    fact_revision: str | None
    warning: str | None


class FrozenUnit(CompositionModel):
    """Keep equipment ownership while referring to shared champion and item identities."""

    occurrence_index: Count
    unit: Count
    star_level: Annotated[int, Field(ge=1, strict=True)]
    items: Annotated[
        tuple[tuple[Annotated[int, Field(ge=0, le=2, strict=True)], Count], ...],
        Field(max_length=3),
    ]

    @model_validator(mode="after")
    def unique_slots(self):
        """Reject duplicate holder slots just as expanded UnitOccurrence does."""
        if len({slot for slot, _ in self.items}) != len(self.items):
            raise ValueError("Frozen unit item slots must be unique")
        return self


class FrozenBoard(CompositionModel):
    """Reference lossless occurrence catalogs by index to keep the Git export small."""

    level: Count | None
    units: tuple[Count, ...]
    traits: tuple[Count, ...]


class FrozenSource(CompositionModel):
    """Store the complete anonymous population in a versioned development JSON file."""

    schema_version: Literal["compositions.source.v1"] = "compositions.source.v1"
    exported_at: Identifier
    patch: Identifier
    set_number: Count
    queue_id: Count
    eligible_boards: Count
    unit_entities: tuple[EntityRef, ...]
    item_entities: tuple[EntityRef, ...]
    units: tuple[FrozenUnit, ...]
    traits: tuple[TraitObservation, ...]
    boards: tuple[FrozenBoard, ...]
    placements: tuple[Annotated[int, Field(ge=1, le=8, strict=True)] | None, ...]

    @model_validator(mode="after")
    def complete_population(self):
        """Reject truncated exports and corrupt catalogs before experiments can start."""
        if len(self.boards) != self.eligible_boards or len(self.placements) != len(self.boards):
            raise ValueError("Frozen source population is incomplete")
        for unit in self.units:
            if unit.unit >= len(self.unit_entities) or any(
                item >= len(self.item_entities) for _, item in unit.items
            ):
                raise ValueError("Frozen unit entity reference is invalid")
        for board in self.boards:
            if any(index >= len(self.units) for index in board.units) or any(
                index >= len(self.traits) for index in board.traits
            ):
                raise ValueError("Frozen source catalog reference is invalid")
            occurrences = [self.units[index].occurrence_index for index in board.units]
            if len(set(occurrences)) != len(occurrences):
                raise ValueError("Frozen source occurrence indices must be unique")
        return self
