"""Immutable, outcome-separated composition contracts shared by all adapters."""

from typing import Annotated, Literal, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1)]
Count = Annotated[int, Field(ge=0, strict=True)]
Positive = Annotated[int, Field(ge=1, strict=True)]
Rate = Annotated[float, Field(ge=0, le=1, strict=True)]


class CompositionModel(BaseModel):
    """Reject accidental fields and mutable collections at composition boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class EntityRef(CompositionModel):
    """Identify an entity using the canonical identity available in scoped facts."""

    key: Identifier
    name: Identifier


class ItemOccurrence(CompositionModel):
    """Preserve one completed item slot, including duplicate item identities."""

    slot: Annotated[int, Field(ge=0, le=2, strict=True)]
    item: EntityRef


class UnitOccurrence(CompositionModel):
    """Keep an individual champion occurrence and its holder-bound investment."""

    occurrence_index: Count
    unit: EntityRef
    star_level: Positive
    items: Annotated[tuple[ItemOccurrence, ...], Field(max_length=3)]

    @model_validator(mode="after")
    def unique_slots(self):
        """Reject duplicate slots without rejecting repeated item identities."""
        if len({i.slot for i in self.items}) != len(self.items):
            raise ValueError("item slots must be unique")
        return self


class TraitObservation(CompositionModel):
    """Preserve unknown trait measurements independently from inactive values."""

    trait: EntityRef
    num_units: Count | None
    tier_current: Count | None
    style: Count | None


class BoardObservation(CompositionModel):
    """Supply only structural, experiment-local data to discovery adapters."""

    observation_id: Identifier
    level: Count | None
    units: tuple[UnitOccurrence, ...]
    traits: tuple[TraitObservation, ...]

    @model_validator(mode="after")
    def unique_occurrences(self):
        """Require occurrence indices to distinguish repeated champions."""
        if len({u.occurrence_index for u in self.units}) != len(self.units):
            raise ValueError("occurrence indices must be unique")
        return self


class BoardOutcome(CompositionModel):
    """Hold outcomes separately until classification has finished."""

    observation_id: Identifier
    placement: Annotated[int, Field(ge=1, le=8, strict=True)] | None


class UnitRequirement(CompositionModel):
    """Describe a conjunctive unit count and optional investment requirement."""

    unit: EntityRef
    min_copies: Positive
    itemized: Annotated[bool, Field(strict=True)] | None


class TraitRequirement(CompositionModel):
    """Describe an observed active breakpoint rather than inferred synergy."""

    trait: EntityRef
    min_tier_current: Positive


class StructuralPattern(CompositionModel):
    """Keep a jointly meaningful conjunction; alternatives use separate patterns."""

    pattern_id: Identifier
    label: Identifier
    units: tuple[UnitRequirement, ...]
    traits: tuple[TraitRequirement, ...]


class VariationDefinition(CompositionModel):
    """Describe an optional recurrent structure within one family."""

    variation_id: Identifier
    label: Identifier
    description: str
    patterns: tuple[StructuralPattern, ...]
    representative_observation_ids: tuple[Identifier, ...]


class FamilyDefinition(CompositionModel):
    """Describe a family without embedding its algorithm membership model."""

    family_id: Identifier
    label: Identifier
    description: str
    defining_patterns: tuple[StructuralPattern, ...]
    representative_observation_ids: tuple[Identifier, ...]
    variations: tuple[VariationDefinition, ...]


class MatchScore(CompositionModel):
    """Label score semantics without implying probability calibration."""

    name: Identifier
    value: Annotated[float, Field(strict=True)]
    kind: Literal["distance", "similarity", "model_probability"]
    higher_is_better: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def probability_range(self):
        """Constrain model probabilities while preserving arbitrary distance scales."""
        if self.kind == "model_probability" and not 0 <= self.value <= 1:
            raise ValueError("probability must be between zero and one")
        return self


class FamilyCandidate(CompositionModel):
    """Explain one candidate under a frozen classification policy."""

    family_id: Identifier
    score: MatchScore
    evidence: tuple[str, ...]


class BoardAssignment(CompositionModel):
    """Record classification, competing candidates, and rejection reasons."""

    observation_id: Identifier
    status: Literal["assigned", "ambiguous", "unclassified"]
    family_id: Identifier | None
    variation_id: Identifier | None
    candidates: tuple[FamilyCandidate, ...]
    explanation: str

    @model_validator(mode="after")
    def primary_family(self):
        """Prevent ambiguous or rejected boards from contributing to a family."""
        if self.status == "assigned" and self.family_id is None:
            raise ValueError("assigned board requires family")
        if self.status != "assigned" and (
            self.family_id is not None or self.variation_id is not None
        ):
            raise ValueError("only assigned boards have primary family or variation")
        return self


class PatternSupport(CompositionModel):
    """Record measured support of the entire conjunction."""

    pattern: StructuralPattern
    matching_boards: Count
    eligible_boards: Count

    @model_validator(mode="after")
    def denominator(self):
        """Reject support exceeding its population."""
        if self.matching_boards > self.eligible_boards:
            raise ValueError("matching boards exceed eligible boards")
        return self


class OutcomeSummary(CompositionModel):
    """Distinguish available, empty, suppressed, and unavailable outcomes."""

    state: Literal["available", "empty", "suppressed", "unavailable"]
    observed_boards: Count
    placement_counts: (
        Annotated[tuple[Count, ...], Field(min_length=8, max_length=8)] | None
    )
    avg_placement: Annotated[float, Field(ge=1, le=8, strict=True)] | None
    top4_rate: Rate | None
    win_rate: Rate | None

    @model_validator(mode="after")
    def distribution(self):
        """Ensure available metrics agree with the distribution and hide absent metrics."""
        metrics = (
            self.placement_counts,
            self.avg_placement,
            self.top4_rate,
            self.win_rate,
        )
        if self.state != "available":
            if any(v is not None for v in metrics):
                raise ValueError("unavailable metrics must be null")
            if self.state == "empty" and self.observed_boards:
                raise ValueError("empty outcomes have zero observations")
        else:
            if any(v is None for v in metrics) or not self.observed_boards:
                raise ValueError("available outcomes require nonempty distribution")
            counts = self.placement_counts
            n = self.observed_boards
            if sum(counts) != n:
                raise ValueError("outcome counts must sum to observed boards")
            expected = (
                sum((i + 1) * c for i, c in enumerate(counts)) / n,
                sum(counts[:4]) / n,
                counts[0] / n,
            )
            if any(abs(a - b) > 1e-9 for a, b in zip(metrics[1:], expected)):
                raise ValueError("outcome metrics disagree with counts")
        return self


class FamilyProfile(CompositionModel):
    """Summarize family membership with the entire eligible population denominator."""

    family_id: Identifier
    assigned_boards: Count
    eligible_population_boards: Count
    play_share: Rate | None
    joint_patterns: tuple[PatternSupport, ...]
    outcomes: OutcomeSummary

    @model_validator(mode="after")
    def denominator(self):
        """Keep rejected boards in prevalence denominators and zero populations null."""
        if self.assigned_boards > self.eligible_population_boards:
            raise ValueError("assigned boards exceed eligible population")
        n = self.eligible_population_boards
        if (not n and self.play_share is not None) or (
            n
            and (
                self.play_share is None
                or abs(self.play_share - self.assigned_boards / n) > 1e-9
            )
        ):
            raise ValueError("play share disagrees with population")
        return self


class DiagnosticPanel(CompositionModel):
    """Provide a named algorithm-specific JSON panel with explicit interpretation."""

    panel_id: Identifier
    title: Identifier
    kind: Literal["table", "series", "tree", "graph", "distribution", "text"]
    description: str
    data: dict[str, Any]


class Diagnostics(CompositionModel):
    """Keep diagnostic payloads out of stable family definitions."""

    schema_version: Literal["diagnostics.v1"] = "diagnostics.v1"
    panels: tuple[DiagnosticPanel, ...] = ()
    warnings: tuple[str, ...] = ()


class FrozenModel(CompositionModel):
    """Serialize algorithm state and the effective classification policy as JSON."""

    schema_version: Literal["adapter.v1"] = "adapter.v1"
    algorithm_id: Identifier
    algorithm_version: Identifier
    feature_revision: Literal["structure.v1"] = "structure.v1"
    effective_parameters: dict[str, Any]
    families: tuple[FamilyDefinition, ...]
    state: dict[str, Any]


class FitResult(CompositionModel):
    """Return frozen membership and native discovery labels separately."""

    model: FrozenModel
    discovery_assignments: tuple[BoardAssignment, ...]
    diagnostics: Diagnostics


class ReferenceParameters(CompositionModel):
    """Demonstrate validated and persisted effective matching thresholds."""

    rejection_distance: float = Field(default=2.0, ge=0)
    ambiguity_margin: float = Field(default=0.05, ge=0)
