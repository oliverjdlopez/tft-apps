"""Shared structural and reference validation helpers for compositions."""

from collections import Counter
from .models import (
    BoardObservation,
    FamilyDefinition,
    BoardAssignment,
    StructuralPattern,
)


def validate_references(boards, families, assignments, outcomes=()):
    """Validate experiment-local references before persistence or display.

    Args:
        boards: Unique outcome-free observations.
        families: Frozen display definitions.
        assignments: Exactly one assignment per supplied board.
        outcomes: Optional separately held outcomes.
    """
    ids = {b.observation_id for b in boards}
    family_map = {f.family_id: f for f in families}
    if len(ids) != len(boards) or len(family_map) != len(families):
        raise ValueError("duplicate board or family identity")
    if len(assignments) != len(ids) or {a.observation_id for a in assignments} != ids:
        raise ValueError("assignments must cover each board exactly once")
    for family in families:
        if not set(family.representative_observation_ids) <= ids:
            raise ValueError("unknown representative")
        if len({v.variation_id for v in family.variations}) != len(family.variations):
            raise ValueError("duplicate variation")
        for variation in family.variations:
            if not set(variation.representative_observation_ids) <= ids:
                raise ValueError("unknown variation representative")
    for assignment in assignments:
        if any(c.family_id not in family_map for c in assignment.candidates):
            raise ValueError("unknown candidate family")
        if assignment.family_id is not None:
            family = family_map.get(assignment.family_id)
            if family is None:
                raise ValueError("unknown primary family")
            if assignment.variation_id is not None and assignment.variation_id not in {
                v.variation_id for v in family.variations
            }:
                raise ValueError("unknown family variation")
    if len({o.observation_id for o in outcomes}) != len(outcomes) or any(
        o.observation_id not in ids for o in outcomes
    ):
        raise ValueError("invalid outcome reference")


def matches_pattern(board: BoardObservation, pattern: StructuralPattern) -> bool:
    """Test whether one board contains every unit, item state, and trait tier of a pattern."""
    for requirement in pattern.units:
        copies = sum(
            u.unit.key == requirement.unit.key
            and (requirement.itemized is None or bool(u.items) == requirement.itemized)
            for u in board.units
        )
        if copies < requirement.min_copies:
            return False
    return all(
        any(
            t.trait.key == r.trait.key
            and t.tier_current is not None
            and t.tier_current >= r.min_tier_current
            for t in board.traits
        )
        for r in pattern.traits
    )


# =====================================================================
# Adapter display definitions and reference classification
# These helpers share structural semantics without sharing fitted models.
# Algorithms own cluster discovery and their serialized matching policy.
# =====================================================================


def family_from_boards(family_id, boards, representative=None):
    """Describe a family by its representative board rather than marginal frequencies.

    The returned pattern restates one real board (the representative): every unit with
    its copy count and whether it held completed items, plus active trait tiers. Other
    ``boards`` never contribute. The pattern is a description only; family membership
    is decided by distance to frozen references, and ``matches_pattern`` merely
    measures how many assigned boards resemble the representative.
    """
    from .models import (
        FamilyDefinition,
        StructuralPattern,
        UnitRequirement,
        TraitRequirement,
    )

    representative = representative or boards[0]
    counts = Counter((u.unit.key, bool(u.items)) for u in representative.units)
    refs = {u.unit.key: u.unit for u in representative.units}
    requirements = tuple(
        UnitRequirement(unit=refs[key], min_copies=count, itemized=itemized)
        for (key, itemized), count in sorted(counts.items())
    )
    traits = tuple(
        TraitRequirement(trait=t.trait, min_tier_current=t.tier_current)
        for t in representative.traits
        if t.tier_current is not None and t.tier_current > 0
    )
    anchors = [u.unit.name for u in representative.units if u.items]
    label = " / ".join(dict.fromkeys(anchors)) or "Unitemized structure"
    return FamilyDefinition(
        family_id=family_id,
        label=label,
        description="Observed structural family; the frozen adapter controls membership.",
        defining_patterns=(
            StructuralPattern(
                pattern_id=f"{family_id}-joint",
                label="Representative joint structure",
                units=requirements,
                traits=traits,
            ),
        ),
        representative_observation_ids=(representative.observation_id,),
        variations=(),
    )


def reference_assignments(
    boards,
    families,
    references,
    rejection_distance,
    ambiguity_margin,
    *,
    accelerated=False,
    metric="euclidean",
):
    """Match frozen per-family reference boards with explicit rejection and ties.

    Args:
        boards: New outcome-free observations.
        families: Frozen definitions.
        references: Mapping from family id to nonempty reference board sequences.
        rejection_distance: Maximum accepted nearest-reference distance.
        ambiguity_margin: Minimum separation from the second viable family.
        accelerated: Use bounded CPU/CUDA matrix matching for supported adapters.
        metric: Euclidean for new models; weighted Jaccard for saved v1 models.
    """
    from .distance import board_distance
    from .acceleration import grouped_reference_distances

    retained = [f for f in families if references.get(f.family_id)]
    if accelerated:
        rows = grouped_reference_distances(
            boards, [references[f.family_id] for f in retained], metric=metric
        )
    else:
        rows = (
            [
                min(board_distance(board, ref, metric=metric) for ref in references[f.family_id])
                for f in retained
            ]
            for board in boards
        )
    return tuple(
        reference_assignment(
            board,
            sorted(
                (float(value), family.family_id) for value, family in zip(row, retained)
            ),
            rejection_distance,
            ambiguity_margin,
        )
        for board, row in zip(boards, rows)
    )


def reference_assignment(board, scores, rejection_distance, ambiguity_margin):
    """Apply the existing rejection, tie, and evidence rules to sorted scores."""
    from .models import BoardAssignment, FamilyCandidate, MatchScore

    candidates = tuple(
        FamilyCandidate(
            family_id=fid,
            score=MatchScore(
                name="reference distance",
                value=float(score),
                kind="distance",
                higher_is_better=False,
            ),
            evidence=(
                f"Frozen structural reference distance {score:.4f}; rejection threshold {rejection_distance:.4f}",
            ),
        )
        for score, fid in scores[:5]
    )
    status, family_id = "unclassified", None
    reason = "No reference within the frozen distance threshold"
    if scores and scores[0][0] <= rejection_distance:
        if (
            len(scores) > 1
            and scores[1][0] <= rejection_distance
            and scores[1][0] - scores[0][0] <= ambiguity_margin
        ):
            status, reason = (
                "ambiguous",
                "Competing families fall within the frozen ambiguity margin",
            )
        else:
            status, family_id, reason = (
                "assigned",
                scores[0][1],
                "Nearest frozen structural reference accepted",
            )
    return BoardAssignment(
        observation_id=board.observation_id,
        status=status,
        family_id=family_id,
        variation_id=None,
        candidates=candidates,
        explanation=reason,
    )


# =====================================================================
# CPU/CUDA reference classification
# Encode each board once; shared arithmetic preserves frozen score rules.
# CUDA is optional and never owns database or experiment worker state.
# =====================================================================


def encode_reference_boards(boards, references):
    """Encode query and frozen features together, retaining unseen-query penalties."""
    import numpy as np
    from .features import structural_features

    features = [structural_features(board) for board in (*boards, *references)]
    keys = sorted({key for row in features for key in row})
    matrix = np.array(
        [[row.get(key, 0.0) for key in keys] for row in features], dtype=np.float64
    )
    return matrix[: len(boards)], matrix[len(boards) :]


def cpu_reference_distances(queries, references, metric="euclidean"):
    """Compute Euclidean blocks or replay legacy weighted Jaccard references."""
    import numpy as np
    from scipy.spatial.distance import cdist

    if metric == "euclidean":
        return cdist(queries, references, metric="euclidean")
    if metric != "weighted_jaccard":
        raise ValueError("Unknown structural distance metric")
    l1 = cdist(queries, references, metric="cityblock")
    total = queries.sum(axis=1)[:, None] + references.sum(axis=1)
    denominator = total + l1
    # Feature weights are multiples of 1/4, so sums are exact. This ordering
    # preserves scalar 1 - min/max at threshold boundaries, including empties.
    return 1.0 - np.divide(
        total - l1, denominator, out=np.ones_like(l1), where=denominator != 0
    )


def cuda_available():
    """Probe optional CUDA without making imports fail on CPU-only installations."""
    try:
        import cupy as cp

        return cp.cuda.runtime.getDeviceCount() > 0
    except Exception:
        return False


def cuda_reference_distances(queries, frozen_device, reference_count, metric="euclidean"):
    """Compute bounded CUDA distances using new Euclidean or legacy Jaccard geometry."""
    import cupy as cp
    import numpy as np

    if metric not in ("euclidean", "weighted_jaccard"):
        raise ValueError("Unknown structural distance metric")
    count, features = queries.shape
    device_queries = cp.asarray(np.ascontiguousarray(queries.T))
    result = cp.empty((count, reference_count), dtype=cp.float64)
    kernel = cp.RawKernel(
        r"""
    extern "C" __global__ void references(const double* q, const double* r,
        double* out, int nq, int nr, int nf, int euclidean) {
        long long pair = (long long)blockDim.x * blockIdx.x + threadIdx.x;
        if (pair >= (long long)nq * nr) return;
        int a = pair / nr, b = pair % nr;
        double intersection = 0.0, total = 0.0, squared = 0.0;
        for (int k = 0; k < nf; ++k) {
            double x = q[(long long)k * nq + a], y = r[(long long)k * nr + b];
            double delta = x - y;
            squared += delta * delta;
            intersection += x < y ? x : y;
            total += x > y ? x : y;
        }
        out[pair] = euclidean ? sqrt(squared) : (total ? 1.0 - intersection / total : 0.0);
    }
    """,
        "references",
    )
    kernel(
        ((count * reference_count + 255) // 256,),
        (256,),
        (
            device_queries,
            frozen_device,
            result,
            np.int32(count),
            np.int32(reference_count),
            np.int32(features),
            np.int32(metric == "euclidean"),
        ),
    )
    return result


def cuda_group_minima(distances, starts):
    """Reduce contiguous family or variation references on device in one launch."""
    import cupy as cp
    import numpy as np

    rows, columns = distances.shape
    boundaries = cp.asarray(np.append(starts, columns).astype(np.int64))
    groups = len(starts)
    result = cp.empty((rows, groups), dtype=cp.float64)
    kernel = cp.RawKernel(
        r"""
    extern "C" __global__ void minima(const double* x, const long long* bounds,
        double* out, int rows, int cols, int groups) {
        long long index = (long long)blockDim.x * blockIdx.x + threadIdx.x;
        if (index >= (long long)rows * groups) return;
        int row = index / groups, group = index % groups;
        // Every reference group is nonempty; seed from a real distance.
        double best = x[(long long)row * cols + bounds[group]];
        for (long long col = bounds[group]; col < bounds[group + 1]; ++col) {
            double value = x[(long long)row * cols + col];
            best = value < best ? value : best;
        }
        out[index] = best;
    }
    """,
        "minima",
    )
    kernel(
        ((rows * groups + 255) // 256,),
        (256,),
        (
            distances,
            boundaries,
            result,
            np.int32(rows),
            np.int32(columns),
            np.int32(groups),
        ),
    )
    return result


def model_distance_metric(model):
    """Resolve frozen distance semantics so saved Jaccard models remain replayable.

    Args:
        model: A validated distance-based adapter envelope.

    Returns:
        The metric associated with its algorithm revision.
    """
    if model.algorithm_version == "1":
        return "weighted_jaccard"
    if model.algorithm_version in ("2", "3"):
        return "euclidean"
    raise ValueError("Unsupported distance model version")
