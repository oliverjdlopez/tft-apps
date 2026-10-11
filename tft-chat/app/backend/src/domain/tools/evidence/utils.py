"""Adapt public analytical results and validate evidence display choices."""

import json
import logging
from uuid import uuid4

from common.serialization import to_jsonable
from domain.runtime.models import AssistantRunContext
from domain.tools.db_tools.models import AnalysisComparisonResult, AnalysisTableResult
from .models import (
    DistributionDataset,
    DisplaySpec,
    EvidenceBundle,
    EvidenceField,
    EvidenceRow,
    EvidenceStore,
    PlacementBin,
    RankingDataset,
    ResolvedPresentation,
)

logger = logging.getLogger(__name__)

# Deliberate public field lists prevent open analytical row mappings from becoming
# a route for private IDs or unknown values into the presentation contract.
RANKING_FIELDS = {
    "rank_units": "unit_name star_level cost games avg_placement top4_rate win_rate pick_rate universe_games delta relative_delta",
    "rank_items": "item_name unit_name holds boards avg_placement top4_rate win_rate pick_rate_per_board universe_games delta relative_delta",
    "rank_traits": "trait_name tier games avg_placement top4_rate win_rate pick_rate universe_games delta relative_delta",
    "rank_unit_loadouts": "unit_name star_level item_count item_1 item_2 item_3 boards avg_placement top4_rate win_rate unit_boards loadout_pick_rate delta relative_delta",
}
TEXT_FIELDS = {"tier", "unit_name", "item_name", "trait_name", "item_1", "item_2", "item_3"}
FRACTION_FIELDS = {
    "top4_rate",
    "win_rate",
    "pick_rate",
    "pick_rate_per_board",
    "loadout_pick_rate",
}
GROUP_FIELDS = {"unit_name", "trait_name", "star_level", "tier", "cost", "item_count"}
MAX_ROWS = 200


def resolve_evidence_store(context_or_store: object) -> EvidenceStore | None:
    """Resolve invocation evidence while preserving legacy bare-store callers.

    Args:
        context_or_store: Application run context, legacy store, or absent context.

    Returns:
        The caller-owned store, if this execution surface supports evidence.
    """
    if isinstance(context_or_store, AssistantRunContext):
        return context_or_store.evidence
    return context_or_store if isinstance(context_or_store, EvidenceStore) else None


def presentation_event(context_or_store: object, call_id: str | None) -> dict:
    """Extract a browser event from validated evidence without model rounding.

    Args:
        context_or_store: Application run context, legacy store, or absent context.
        call_id: SDK call identifier associated with a successful presentation.

    Returns:
        The existing presentation payload or its bounded unavailable error.
    """
    store = resolve_evidence_store(context_or_store)
    presentation = store.presentations.get(call_id) if store is not None else None
    if presentation is not None:
        try:
            # Only the acknowledgement crosses the model boundary. The browser
            # receives this store object directly to retain analytical precision.
            return {
                "type": "presentation",
                "presentation": presentation.model_dump(mode="json"),
            }
        except (ValueError, TypeError):
            pass
    return {"type": "presentation_error", "error": "Evidence view unavailable."}


def field_definition(key: str) -> EvidenceField:
    """Declare formatting and grouping from known analytical field semantics."""
    if key in TEXT_FIELDS:
        unit = "text"
    elif key in FRACTION_FIELDS:
        unit = "fraction"
    elif key == "avg_placement":
        unit = "placement"
    elif key in {"delta", "relative_delta"}:
        unit = "number"
    else:
        unit = "count"
    return EvidenceField(
        key=key,
        label=key.replace("_", " ").capitalize(),
        unit=unit,
        groupable=key in GROUP_FIELDS,
    )


def normalize_cell(field: EvidenceField, value: object) -> str | int | float | None:
    """Normalize database scalars without rounding or guessing percentage units."""
    if value is None:
        return None
    if field.unit == "text":
        if not isinstance(value, str):
            raise ValueError("Expected a public text value")
        return value
    if isinstance(value, bool):
        raise ValueError("Boolean is not an analytical number")
    number = float(value)
    if field.unit == "count":
        if number < 0 or not number.is_integer():
            raise ValueError("Invalid count")
        return int(number)
    if field.unit == "fraction" and not 0 <= number <= 1:
        raise ValueError("Rates must be fractions")
    if field.unit == "placement" and not 1 <= number <= 8:
        raise ValueError("Invalid average placement")
    return number


def capture_evidence(store: EvidenceStore, name: str, output: object) -> dict | None:
    """Register supported results before model rounding, returning safe references.

    Unsupported or malformed evidence does not break the underlying analytical
    response. The assistant can still explain that result in prose.
    """
    if name not in RANKING_FIELDS and name != "compare_cohorts":
        return None
    try:
        data = json.loads(output) if isinstance(output, str) else to_jsonable(output)
        ref = "evidence-" + uuid4().hex
        if name in RANKING_FIELDS:
            result = AnalysisTableResult.model_validate(data)
            keys = [
                key
                for key in RANKING_FIELDS[name].split()
                if any(key in row for row in result.results)
            ]
            if not keys:
                keys = RANKING_FIELDS[name].split()[:1]
            fields = tuple(field_definition(key) for key in keys)
            rows = tuple(
                EvidenceRow(
                    key=f"row-{index}",
                    values={
                        field.key: normalize_cell(field, row.get(field.key))
                        for field in fields
                    },
                )
                for index, row in enumerate(result.results[:MAX_ROWS])
            )
            page = result.page.model_copy(
                update={
                    "count": len(rows),
                    "has_more": result.page.has_more or len(result.results) > MAX_ROWS,
                }
            )
            dataset = RankingDataset(
                grain="One aggregate per "
                + (", ".join(result.context.group_by) or name.removeprefix("rank_")),
                fields=fields,
                rows=rows,
                page=page,
                source_sort=tuple(
                    f"{sort.metric} {sort.direction}" for sort in result.context.sort
                ),
            )
            bundle = EvidenceBundle(
                ref=ref,
                source=name,
                population=result.context.population,
                population_boards=result.context.population_boards,
                minimum_reportable_boards=result.context.minimum_reportable_boards,
                warnings=tuple(result.warnings),
                datasets=(dataset,),
            )
        else:
            result = AnalysisComparisonResult.model_validate(data)
            datasets = []
            for key in ("target", "baseline"):
                cohort = getattr(result, key)
                available = not cohort.suppressed and cohort.histogram is not None
                bins = ()
                if available:
                    if set(cohort.histogram) != set(map(str, range(1, 9))):
                        raise ValueError(
                            "Distribution must explicitly report all placements"
                        )
                    bins = tuple(
                        PlacementBin(
                            placement=place, count=cohort.histogram[str(place)]
                        )
                        for place in range(1, 9)
                    )
                    if sum(bin.count for bin in bins) != cohort.boards:
                        raise ValueError("Histogram and sample size disagree")
                datasets.append(
                    DistributionDataset(
                        ref=key,
                        label=cohort.label,
                        bins=bins,
                        boards=cohort.boards if available else None,
                        unavailable=not available,
                    )
                )
            bundle = EvidenceBundle(
                ref=ref,
                source=name,
                population=result.context.shared_population
                or "Explicit target and baseline cohorts",
                minimum_reportable_boards=result.context.minimum_reportable_boards,
                warnings=tuple(result.warnings),
                datasets=tuple(datasets),
            )
        store.bundles[ref] = bundle
        return {
            "evidence_ref": ref,
            "datasets": [
                {
                    "dataset_ref": dataset.ref,
                    "kind": dataset.kind,
                    "fields": (
                        [field.model_dump() for field in dataset.fields]
                        if isinstance(dataset, RankingDataset)
                        else []
                    ),
                    "displays": (
                        ["static_table", "interactive_table"]
                        if isinstance(dataset, RankingDataset)
                        else ["distribution"]
                    ),
                }
                for dataset in bundle.datasets
            ],
        }
    except (ValueError, TypeError, OverflowError):
        logger.warning(
            "Evidence unavailable for tool %s; preserving analytical output", name
        )
        return None


def resolve_presentation(
    store: EvidenceStore, spec: DisplaySpec, call_id: str
) -> ResolvedPresentation:
    """Resolve only invocation-local evidence and compatible editorial choices."""
    bundle = store.bundles.get(spec.evidence_ref)
    if bundle is None:
        raise ValueError(
            "Unknown evidence reference; use a reference from this invocation"
        )
    dataset = next(
        (item for item in bundle.datasets if item.ref == spec.dataset_ref), None
    )
    if dataset is None:
        raise ValueError("Unknown dataset reference")
    if isinstance(dataset, RankingDataset):
        fields = {field.key: field for field in dataset.fields}
        if spec.kind == "distribution":
            raise ValueError("Ranking rows cannot supply a placement distribution")
        if (
            not spec.columns
            or len(set(spec.columns)) != len(spec.columns)
            or not set(spec.columns) <= fields.keys()
        ):
            raise ValueError("Select unique columns from the dataset fields")
        if spec.sort_by is not None and spec.sort_by not in spec.columns:
            raise ValueError("Sort must reference a visible column")
        if spec.primary_metric is not None and (
            spec.primary_metric not in spec.columns
            or fields[spec.primary_metric].unit == "text"
        ):
            raise ValueError("Primary metric must be a visible numeric field")
        if spec.group_by is not None and (
            spec.kind != "interactive_table"
            or spec.group_by not in spec.columns
            or not fields[spec.group_by].groupable
        ):
            raise ValueError("Grouping requires an approved visible categorical field")
    elif (
        spec.kind != "distribution"
        or spec.columns
        or spec.sort_by
        or spec.group_by
        or spec.primary_metric
    ):
        raise ValueError(
            "Distributions use their backend placement bins, without table options"
        )
    if store.presentations and call_id not in store.presentations:
        raise ValueError("One initial display is supported per answer")
    presentation = ResolvedPresentation(
        id="view-" + uuid4().hex, bundle=bundle, display=spec
    )
    store.presentations[call_id] = presentation
    return presentation
