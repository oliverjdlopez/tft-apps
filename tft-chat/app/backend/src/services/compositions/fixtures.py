"""Fixture-backed composition display service."""

from domain.compositions.fixtures import (
    fixture_boards,
    fixture_outcomes,
    fixture_family,
)
from domain.compositions.models import BoardAssignment
from .utils import family_preview
from domain.compositions.profiles import aggregate_profiles
from domain.compositions.utils import validate_references
from .models import (
    CompositionContext,
    CompositionDetailResponse,
    CompositionListResponse,
    CompositionWarning,
    BoardExampleView,
    FamilySummaryView,
)


def fixture_detail():
    """Return validated fixture data with explicit representative-board semantics."""
    boards, outcomes, family = fixture_boards(), fixture_outcomes(), fixture_family()
    assignments = tuple(
        BoardAssignment(
            observation_id=b.observation_id,
            status="assigned" if i < 12 else "unclassified",
            family_id=family.family_id if i < 12 else None,
            variation_id=None,
            candidates=(),
            explanation="Illustrative fixture membership",
        )
        for i, b in enumerate(boards)
    )
    validate_references(boards, (family,), assignments, outcomes)
    return CompositionDetailResponse(
        schema_version="composition.v1",
        context=CompositionContext(
            source_kind="fixture",
            population_kind="discovery_sample",
            patch="fixture",
            set_number=17,
            queue_id=1100,
            snapshot_revision="fixture.v1",
            taxonomy_revision="fixture.v1",
            feature_revision="structure.v1",
            algorithm_id=None,
            algorithm_version=None,
            experiment_id=None,
        ),
        family=family,
        profile=aggregate_profiles(boards, outcomes, (family,), assignments)[0],
        examples=tuple(
            BoardExampleView(
                board=b,
                outcome=o,
                assignment=a,
                is_representative=b.observation_id
                in family.representative_observation_ids,
            )
            for b, o, a in zip(boards[:12], outcomes[:12], assignments[:12])
        ),
        warnings=(
            CompositionWarning(
                code="fixture",
                message="Illustrative fixtures, not published analytics.",
            ),
        ),
    )


def family_summary(family, profile):
    """Project common display fields from validated family definitions and metrics."""
    return FamilySummaryView(
        family_id=family.family_id,
        label=family.label,
        description=family.description,
        assigned_boards=profile.assigned_boards,
        eligible_population_boards=profile.eligible_population_boards,
        play_share=profile.play_share,
        variation_count=len(family.variations),
        preview=family_preview(family),
    )


def fixture_list():
    """Build the fixture list through the same response contract as saved runs."""
    detail = fixture_detail()
    return CompositionListResponse(
        schema_version="composition.v1",
        context=detail.context,
        families=(family_summary(detail.family, detail.profile),),
        warnings=detail.warnings,
    )
