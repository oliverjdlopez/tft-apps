"""Backend evidence and bounded editorial choices for chat displays."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from domain.tools.db_tools.models import AnalysisPage, AnalysisWarning


class EvidenceModel(BaseModel):
    """Reject unknown fields and non-finite numbers in display contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class EvidenceField(EvidenceModel):
    """Describe a backend-approved field and its display semantics."""

    key: str
    label: str
    unit: Literal["text", "count", "placement", "fraction", "number"]
    groupable: bool = False


class EvidenceRow(EvidenceModel):
    """Identify a public aggregate row without exposing database identifiers."""

    key: str
    values: dict[str, str | int | float | None]


class RankingDataset(EvidenceModel):
    """Keep bounded aggregate rows separate from presentation and local state."""

    kind: Literal["ranking"] = "ranking"
    ref: str = "rows"
    grain: str
    fields: tuple[EvidenceField, ...]
    rows: tuple[EvidenceRow, ...]
    page: AnalysisPage
    source_sort: tuple[str, ...] = ()


class PlacementBin(EvidenceModel):
    """Represent one reported placement category, including explicit zeroes."""

    placement: int = Field(ge=1, le=8)
    count: int = Field(ge=0)


class DistributionDataset(EvidenceModel):
    """Preserve one cohort's discrete placement distribution and availability."""

    kind: Literal["distribution"] = "distribution"
    ref: str
    label: str
    grain: str = "One placement category within this cohort"
    bins: tuple[PlacementBin, ...]
    boards: int | None = Field(default=None, ge=0)
    unavailable: bool = False


Dataset = Annotated[RankingDataset | DistributionDataset, Field(discriminator="kind")]


class EvidenceBundle(EvidenceModel):
    """Own retrieved evidence and interpretation context for one tool result."""

    version: Literal[1] = 1
    ref: str
    source: str
    population: str
    population_boards: int | None = None
    minimum_reportable_boards: int
    warnings: tuple[AnalysisWarning, ...] = ()
    datasets: tuple[Dataset, ...]


class DisplaySpec(EvidenceModel):
    """Let responding assistants choose a view by reference, never copied cells."""

    evidence_ref: str = Field(min_length=1, max_length=80)
    dataset_ref: str = Field(min_length=1, max_length=40)
    kind: Literal["static_table", "distribution", "interactive_table"]
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=240)
    columns: list[str] = Field(default_factory=list, max_length=8)
    primary_metric: str | None = None
    sort_by: str | None = None
    direction: Literal["asc", "desc"] = "asc"
    group_by: str | None = None


class ResolvedPresentation(EvidenceModel):
    """Carry backend evidence and validated editorial choices to the browser."""

    id: str
    bundle: EvidenceBundle
    display: DisplaySpec


class EvidenceStore(BaseModel):
    """Own isolated evidence and successful presentations for one SDK run."""

    bundles: dict[str, EvidenceBundle] = Field(default_factory=dict)
    presentations: dict[str, ResolvedPresentation] = Field(default_factory=dict)
