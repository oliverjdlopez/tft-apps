"""Bounded saved-result projections and comparable-population analysis."""

from .models import (
    CompositionListResponse,
    CompositionDetailResponse,
    BoardExampleView,
    CompositionWarning,
    ComparisonResponse,
    ComparisonMetrics,
)
from .persistence import saved_result, frozen_boards
from .fixtures import family_summary
from .utils import board_example, population_boards, population_context

EXPERIMENT_WARNINGS = (
    CompositionWarning(
        code="experimental",
        message="Private experiment. Definitions are unpublished; model probabilities are not calibrated confidence.",
    ),
)


def experiment_population(experiment_id, population_kind):
    """Resolve one completed, frozen population for display or comparison."""
    run = saved_result(experiment_id)
    population = next(
        (p for p in run.populations if p.population_kind == population_kind),
        None,
    )
    if population is None:
        raise ValueError("Requested population was not classified")
    return run, population


def composition_list(experiment_id, population_kind):
    """Project family counts from a selected sample or full population."""
    run, population = experiment_population(experiment_id, population_kind)
    profiles = {p.family_id: p for p in population.profiles}
    return CompositionListResponse(
        schema_version="composition.v1",
        context=population_context(run, population_kind),
        families=tuple(
            family_summary(f, profiles[f.family_id]) for f in run.families
        ),
        warnings=EXPERIMENT_WARNINGS,
    )


def composition_detail(experiment_id, population_kind, family_id):
    """Include representatives and bounded assigned examples with separate outcomes."""
    run, population = experiment_population(experiment_id, population_kind)
    family = next((f for f in run.families if f.family_id == family_id), None)
    if family is None:
        raise LookupError("Family not found")
    boards = frozen_boards(run.snapshot_id)
    assignments = {a.observation_id: a for a in population.assignments}
    representative_ids = set(family.representative_observation_ids)
    eligible = sorted(
        (
            observation_id
            for observation_id in representative_ids
            | {a.observation_id for a in population.assignments if a.family_id == family_id}
            if observation_id in boards
        ),
        key=lambda observation_id: (observation_id not in representative_ids, observation_id),
    )
    return CompositionDetailResponse(
        schema_version="composition.v1",
        context=population_context(run, population_kind),
        family=family,
        profile=next(p for p in population.profiles if p.family_id == family_id),
        examples=tuple(
            board_example(boards, observation_id, assignments.get(observation_id),
                          observation_id in representative_ids)
            for observation_id in eligible[:50]
        ),
        warnings=EXPERIMENT_WARNINGS,
    )


def inspect_board(experiment_id, population_kind, observation_id):
    """Show candidates and rejection evidence for assigned, ambiguous, or noise boards."""
    run, population = experiment_population(experiment_id, population_kind)
    assignment = next(
        (a for a in population.assignments if a.observation_id == observation_id), None
    )
    if assignment is None:
        raise LookupError("Observation not found in this population")
    return board_example(
        frozen_boards(run.snapshot_id), observation_id, assignment,
        any(observation_id in f.representative_observation_ids for f in run.families),
    )


def compare_experiments(left_id, right_id, population_kind):
    """Compare label-invariant assignments only when saved population contents match."""
    from scipy.optimize import linear_sum_assignment
    from sklearn.metrics import adjusted_rand_score
    import numpy as np

    left, lp = experiment_population(left_id, population_kind)
    right, rp = experiment_population(right_id, population_kind)
    lreq, rreq = left.request.model_dump(), right.request.model_dump()
    differences = {
        k: {"left": lreq[k], "right": rreq[k]} for k in lreq if lreq[k] != rreq[k]
    }
    lids, rids = (
        {a.observation_id for a in lp.assignments},
        {a.observation_id for a in rp.assignments},
    )
    identical = (
        lids == rids
        and left.context.patch == right.context.patch
        and left.context.set_number == right.context.set_number
        and left.context.queue_id == right.context.queue_id
        # Snapshot IDs are content hashes, so a shared ID already proves equal
        # boards; only distinct snapshots need their frozen boards compared.
        and (
            left.snapshot_id == right.snapshot_id
            or population_boards(left.snapshot_id, lids)
            == population_boards(right.snapshot_id, rids)
        )
    )
    overlap, ari = None, None
    if identical and lp.assignments:
        la = {a.observation_id: a for a in lp.assignments}
        ra = {a.observation_id: a for a in rp.assignments}
        ids = sorted(la)
        llabels = [la[k].family_id or f"status:{la[k].status}" for k in ids]
        rlabels = [ra[k].family_id or f"status:{ra[k].status}" for k in ids]
        # Match family labels optimally, but never match a rejected status to a
        # discovered family simply because the arbitrary labels line up.
        lf = sorted({a.family_id for a in la.values() if a.family_id})
        rf = sorted({a.family_id for a in ra.values() if a.family_id})
        matrix = np.array(
            [
                [
                    sum(la[k].family_id == a and ra[k].family_id == b for k in ids)
                    for b in rf
                ]
                for a in lf
            ]
        ).reshape((len(lf), len(rf)))
        rows, cols = linear_sum_assignment(-matrix)
        same_rejected = sum(
            la[k].status == ra[k].status and la[k].status != "assigned" for k in ids
        )
        overlap = (int(matrix[rows, cols].sum()) + same_rejected) / len(ids)
        ari = float(adjusted_rand_score(llabels, rlabels))
    return ComparisonResponse(
        left_id=left_id,
        right_id=right_id,
        identical_population=identical,
        left_metrics=ComparisonMetrics(
            family_count=len(left.families),
            eligible_boards=len(lp.assignments),
            coverage=lp.coverage,
            ambiguity=lp.ambiguity,
            elapsed_seconds=left.elapsed_seconds,
        ),
        right_metrics=ComparisonMetrics(
            family_count=len(right.families),
            eligible_boards=len(rp.assignments),
            coverage=rp.coverage,
            ambiguity=rp.ambiguity,
            elapsed_seconds=right.elapsed_seconds,
        ),
        configuration_differences=differences,
        assignment_overlap=overlap,
        adjusted_rand_index=ari,
        message="Family labels matched optimally; rejected statuses match only identical statuses."
        if identical
        else "Assignment overlap requires identical saved populations. Duplicate a run using its saved snapshot.",
    )
