"""Post-classification aggregation of prevalence, joint support, and outcomes."""

from .models import FamilyProfile, OutcomeSummary, PatternSupport
from .utils import matches_pattern


def summarize_outcomes(outcomes, member_ids, minimum=1):
    """Aggregate known outcomes once per board after membership is frozen."""
    placements = {
        o.observation_id: o.placement
        for o in outcomes
        if o.observation_id in member_ids and o.placement is not None
    }
    n = len(placements)
    state = (
        "empty"
        if not member_ids
        else "unavailable"
        if not n
        else "suppressed"
        if n < minimum
        else "available"
    )
    counts = tuple(sum(p == i for p in placements.values()) for i in range(1, 9))
    return OutcomeSummary(
        state=state,
        observed_boards=n,
        placement_counts=counts if state == "available" else None,
        avg_placement=sum(placements.values()) / n if state == "available" else None,
        top4_rate=sum(counts[:4]) / n if state == "available" else None,
        win_rate=counts[0] / n if state == "available" else None,
    )


def aggregate_profiles(boards, outcomes, families, assignments, minimum=1):
    """Count assigned boards once and retain all eligible boards in denominators."""
    if (
        len({b.observation_id for b in boards}) != len(boards)
        or len(assignments) != len(boards)
        or {a.observation_id for a in assignments} != {b.observation_id for b in boards}
    ):
        raise ValueError("population must have exactly one assignment per board")
    profiles = []
    for family in families:
        members = {
            a.observation_id
            for a in assignments
            if a.status == "assigned" and a.family_id == family.family_id
        }
        selected = [b for b in boards if b.observation_id in members]
        profiles.append(
            FamilyProfile(
                family_id=family.family_id,
                assigned_boards=len(members),
                eligible_population_boards=len(boards),
                play_share=len(members) / len(boards) if boards else None,
                joint_patterns=tuple(
                    PatternSupport(
                        pattern=p,
                        matching_boards=sum(matches_pattern(b, p) for b in selected),
                        eligible_boards=len(selected),
                    )
                    for p in family.defining_patterns
                ),
                outcomes=summarize_outcomes(outcomes, members, minimum),
            )
        )
    return tuple(profiles)
