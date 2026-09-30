"""Population denominators, joint support, and cross-object reference failures."""

import pytest
from domain.compositions.fixtures import (
    fixture_boards,
    fixture_family,
    fixture_outcomes,
)
from domain.compositions.models import BoardAssignment, BoardOutcome
from domain.compositions.profiles import aggregate_profiles
from domain.compositions.utils import validate_references


def test_rejected_boards_remain_in_denominator_and_unknown_outcomes_stay_null():
    """Count every board once, with ambiguous/noise excluded only from membership."""
    boards, family = fixture_boards()[:3], fixture_family()
    assignments = tuple(
        BoardAssignment(
            observation_id=b.observation_id,
            status=status,
            family_id=family.family_id if status == "assigned" else None,
            variation_id=None,
            candidates=(),
            explanation="test",
        )
        for b, status in zip(boards, ("assigned", "ambiguous", "unclassified"))
    )
    unknown = tuple(
        BoardOutcome(observation_id=b.observation_id, placement=None) for b in boards
    )
    profile = aggregate_profiles(boards, unknown, (family,), assignments)[0]
    assert profile.assigned_boards == 1 and profile.eligible_population_boards == 3
    assert profile.play_share == 1 / 3
    assert profile.joint_patterns[0].matching_boards == 1
    assert profile.outcomes.state == "unavailable"
    assert (
        profile.outcomes.placement_counts is None
        and profile.outcomes.avg_placement is None
    )
    available = (BoardOutcome(observation_id=boards[0].observation_id, placement=1),)
    suppressed = aggregate_profiles(
        boards, available, (family,), assignments, minimum=50
    )[0].outcomes
    assert suppressed.state == "suppressed" and suppressed.win_rate is None


def test_service_rejects_cross_object_identity_corruption():
    """References must resolve within the experiment and the owning family."""
    boards, family = fixture_boards(), fixture_family()
    assignments = tuple(
        BoardAssignment(
            observation_id=b.observation_id,
            status="assigned",
            family_id=family.family_id,
            variation_id=None,
            candidates=(),
            explanation="test",
        )
        for b in boards
    )
    validate_references(boards, (family,), assignments)
    with pytest.raises(ValueError, match="unknown representative"):
        validate_references(
            boards,
            (
                family.model_copy(
                    update={"representative_observation_ids": ("missing",)}
                ),
            ),
            assignments,
        )
    with pytest.raises(ValueError, match="unknown primary family"):
        validate_references(
            boards,
            (family,),
            (
                assignments[0].model_copy(update={"family_id": "missing"}),
                *assignments[1:],
            ),
        )
    with pytest.raises(ValueError, match="unknown family variation"):
        validate_references(
            boards,
            (family,),
            (
                assignments[0].model_copy(update={"variation_id": "missing"}),
                *assignments[1:],
            ),
        )
