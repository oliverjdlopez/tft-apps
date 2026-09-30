"""Implementation helpers for density discovery and frozen reference validation."""

from ...distance import distance_matrix
from ...models import (
    BoardAssignment,
    DiagnosticPanel,
    Diagnostics,
    FamilyCandidate,
    MatchScore,
)
from ...utils import family_from_boards, encode_reference_boards, cuda_reference_distances
from .models import DiscoveryResult, FrozenCluster, Parameters, State


def discover(boards, parameters):
    """Run actual HDBSCAN on structural distances, preserving native noise.

    Args:
        boards: Canonically ordered observations with at least one observed unit.
        parameters: Validated density settings.

    Returns:
        Distance matrix, native labels, strengths, and cluster persistence values.
    """
    import hdbscan
    import numpy as np

    distances = distance_matrix(boards)
    # HDBSCAN cannot estimate density from an empty/singleton sample. Avoid
    # silently reducing the user's density requirement on other small samples.
    minimum = max(parameters.min_cluster_size, parameters.min_samples + 1)
    if len(boards) < minimum:
        return distances, np.full(len(boards), -1, dtype=int), np.zeros(len(boards)), ()
    fitted = hdbscan.HDBSCAN(
        metric="precomputed",
        algorithm="generic",
        min_cluster_size=parameters.min_cluster_size,
        min_samples=parameters.min_samples,
        cluster_selection_method=parameters.cluster_selection_method,
        cluster_selection_epsilon=parameters.cluster_selection_epsilon,
        allow_single_cluster=parameters.allow_single_cluster,
        approx_min_span_tree=False,
        core_dist_n_jobs=1,
    ).fit(distances)
    return distances, fitted.labels_, fitted.probabilities_, fitted.cluster_persistence_


def freeze_clusters(boards, distances, labels, persistence, *, vectors=None):
    """Assign stable family IDs and retain medoid representatives of native clusters."""
    groups = [
        tuple(i for i, candidate in enumerate(labels) if candidate == label)
        for label in sorted(set(int(label) for label in labels) - {-1})
    ]
    groups.sort(key=lambda indices: tuple(boards[i].observation_id for i in indices))
    families, clusters, label_families = [], [], {}
    for number, indices in enumerate(groups, 1):
        family_id = f"hdbscan-{number:03d}"
        label = int(labels[indices[0]])
        members = tuple(boards[i] for i in indices)
        medoid = gpu_medoid(vectors, indices) if vectors is not None else min(
            indices,
            key=lambda i: (
                sum(float(distances[i, j]) for j in indices),
                boards[i].observation_id,
            ),
        )
        families.append(
            family_from_boards(family_id, members, representative=boards[medoid])
        )
        clusters.append(
            FrozenCluster(
                family_id=family_id,
                persistence=float(persistence[label]),
                references=members,
            )
        )
        label_families[label] = family_id
    return tuple(families), tuple(clusters), label_families


def native_assignment(board, label, strength, label_families):
    """Expose native density membership without applying frozen matching thresholds."""
    if label < 0:
        reason = (
            "No observed units; excluded from density discovery"
            if not board.units
            else "Native HDBSCAN noise; no density cluster selected"
        )
        return BoardAssignment(
            observation_id=board.observation_id,
            status="unclassified",
            family_id=None,
            variation_id=None,
            candidates=(),
            explanation=reason,
        )
    family_id = label_families[label]
    # Membership strength is HDBSCAN's persistence-derived score, not a
    # calibrated posterior probability of the composition family.
    candidate = FamilyCandidate(
        family_id=family_id,
        score=MatchScore(
            name="native density membership strength",
            value=float(strength),
            kind="similarity",
            higher_is_better=True,
        ),
        evidence=(
            "Native HDBSCAN discovery label; distinct from frozen reference classification",
        ),
    )
    return BoardAssignment(
        observation_id=board.observation_id,
        status="assigned",
        family_id=family_id,
        variation_id=None,
        candidates=(candidate,),
        explanation="Native HDBSCAN density cluster membership",
    )


def diagnostic_panels(boards, assignments, clusters, strengths, parameters):
    """Report persistence, native noise, and the frozen policy with finite JSON values."""
    noise = [a.observation_id for a in assignments if a.status == "unclassified"]
    rows = [
        {
            "family_id": cluster.family_id,
            "native_members": len(cluster.references),
            "persistence": cluster.persistence,
        }
        for cluster in clusters
    ]
    members = [
        {
            "observation_id": board.observation_id,
            "family_id": assignment.family_id,
            "native_label": "noise"
            if assignment.family_id is None
            else assignment.family_id,
            "membership_strength": float(strengths.get(board.observation_id, 0.0)),
        }
        for board, assignment in zip(boards, assignments)
    ]
    panels = (
        DiagnosticPanel(
            panel_id="persistence",
            title="HDBSCAN cluster persistence",
            kind="table",
            description="Native cluster stability across density levels; not an outcome score.",
            data={"rows": rows},
        ),
        DiagnosticPanel(
            panel_id="noise",
            title="Native discovery noise",
            kind="distribution",
            description="Unclassified native density labels are retained, including boards with no observed units.",
            data={
                "noise_count": len(noise),
                "population_count": len(boards),
                "noise_fraction": len(noise) / len(boards) if boards else None,
                "noise_observation_ids": noise,
                "rows": members,
            },
        ),
        DiagnosticPanel(
            panel_id="classification-policy",
            title="Frozen reference classification",
            kind="text",
            description="Later classification uses nearest native reference per family, not HDBSCAN approximate_predict. Native noise may subsequently match a family; discovery labels remain unchanged.",
            data={
                "matching_policy": "nearest_native_reference.v1",
                "rejection_distance": parameters.rejection_distance,
                "ambiguity_margin": parameters.ambiguity_margin,
                "references": "all native non-noise members",
            },
        ),
    )
    warnings = (
        ()
        if clusters
        else (
            "HDBSCAN found no density families; frozen classification will remain unclassified.",
        )
    )
    return Diagnostics(panels=panels, warnings=warnings)


def validate_model(model):
    """Reject incompatible envelopes, settings, or algorithm-owned references."""
    if (
        model.schema_version != "adapter.v1"
        or model.algorithm_id != "hdbscan"
        or model.algorithm_version not in ("1", "2", "3")
        or model.feature_revision != "structure.v1"
    ):
        raise ValueError("incompatible HDBSCAN model envelope")
    if set(model.effective_parameters) != set(Parameters.model_fields):
        raise ValueError("HDBSCAN model must serialize every effective parameter")
    parameters = Parameters.model_validate(model.effective_parameters)
    state = State.model_validate(model.state)
    family_map = {family.family_id: family for family in model.families}
    if len(family_map) != len(model.families) or set(family_map) != {
        c.family_id for c in state.clusters
    }:
        raise ValueError("HDBSCAN frozen families disagree with reference state")
    for cluster in state.clusters:
        if len(cluster.references) < parameters.min_cluster_size:
            raise ValueError(
                "HDBSCAN reference cluster is smaller than its frozen minimum"
            )
        family = family_map[cluster.family_id]
        references = {board.observation_id for board in cluster.references}
        if (
            not family.representative_observation_ids
            or not set(family.representative_observation_ids) <= references
        ):
            raise ValueError("HDBSCAN family representative is not a native member")
        if family.variations:
            raise ValueError("HDBSCAN v1 does not define variations")
    return parameters, state


# =====================================================================
# Standalone GPU density discovery
# CPU fallback uses the same fit contract and portable state.
# Only numeric features cross to CUDA; saved references remain portable.
# No GPU estimator or square distance matrix is serialized.
# =====================================================================


def discover_standalone(boards, parameters):
    """Prefer cuML for standalone fits, reporting unavailable-runtime CPU fallback.

    Args:
        boards: Canonically ordered nonempty board observations.
        parameters: Validated HDBSCAN settings shared with the CPU implementation.

    Returns:
        Native density outputs, actual backend, and medoid-selection inputs.
    """
    import numpy as np

    minimum = max(parameters.min_cluster_size, parameters.min_samples + 1)
    if len(boards) < minimum:
        return DiscoveryResult(
            labels=np.full(len(boards), -1, dtype=int),
            strengths=np.zeros(len(boards)), persistence=np.empty(0),
            backend="not_required",
        )
    estimator, reason = gpu_estimator()
    if estimator is None:
        distances, labels, strengths, persistence = discover(boards, parameters)
        return DiscoveryResult(
            labels=labels, strengths=strengths, persistence=np.asarray(persistence),
            distances=distances, backend="cpu", warning=reason,
        )
    # Runtime fitting errors deliberately propagate: an out-of-memory or cuML
    # failure must not silently launch an expensive CPU fit with different labels.
    return discover_cuda(boards, parameters, estimator)


def gpu_estimator():
    """Find cuML and a usable CUDA device without requiring them on CPU-only hosts.

    Returns:
        cuML's estimator class, or an explicit reason for using the CPU fallback.
    """
    try:
        import cupy as cp
        from cuml.cluster import HDBSCAN

        if cp.cuda.runtime.getDeviceCount() < 1:
            return None, "CUDA HDBSCAN unavailable: no CUDA device; discovery used CPU."
        # Probe allocation as well as enumeration before selecting the backend.
        cp.empty(1).sum().get()
        return HDBSCAN, None
    except (ImportError, OSError, RuntimeError) as error:
        return None, (
            "CUDA HDBSCAN unavailable; discovery used CPU. Install the compositions-gpu "
            f"extra and verify the CUDA runtime ({type(error).__name__})."
        )


def discover_cuda(boards, parameters, estimator):
    """Fit cuML HDBSCAN directly on board vectors using brute-force neighbors.

    Args:
        boards: Sorted eligible observations, with enough rows for density fitting.
        parameters: Frozen density controls; no thresholds are silently adjusted.
        estimator: Imported cuML HDBSCAN class, supplied separately for testing.

    Returns:
        Host-native labels, probabilities, persistence, and float64 board vectors.
    """
    import cupy as cp
    import numpy as np

    vectors, _ = encode_reference_boards(boards, ())
    # cuML HDBSCAN operates in float32. Existing feature coordinates are multiples
    # of one quarter and are exactly representable; distance arithmetic may differ
    # from the legacy CPU float64 fitter, especially at tied-neighbor boundaries.
    device = cp.asarray(vectors, dtype=cp.float32, order="C")
    fitted = estimator(
        metric="euclidean", build_algo="brute_force",
        build_kwds={"knn_n_clusters": 1}, output_type="numpy",
        min_cluster_size=parameters.min_cluster_size,
        min_samples=parameters.min_samples,
        cluster_selection_method=parameters.cluster_selection_method,
        cluster_selection_epsilon=parameters.cluster_selection_epsilon,
        allow_single_cluster=parameters.allow_single_cluster,
        prediction_data=False, gen_min_span_tree=False,
    ).fit(device)
    return DiscoveryResult(
        labels=np.asarray(fitted.labels_, dtype=int),
        strengths=np.asarray(fitted.probabilities_, dtype=float),
        persistence=np.asarray(fitted.cluster_persistence_, dtype=float),
        backend="cuda", vectors=vectors,
    )


def gpu_medoid(vectors, indices):
    """Select an exact observed medoid using bounded GPU distance blocks.

    Args:
        vectors: CPU float64 feature coordinates already used for fitting.
        indices: Canonically ordered members of a single native cluster.

    Returns:
        Original row index with least total distance, breaking ties by input order.
    """
    import cupy as cp
    import numpy as np

    members = vectors[list(indices)]
    device = cp.asarray(np.ascontiguousarray(members.T))
    totals = np.empty(len(members), dtype=np.float64)
    for offset in range(0, len(members), 128):
        block = cuda_reference_distances(members[offset:offset + 128], device, len(members))
        totals[offset:offset + len(block)] = cp.asnumpy(block.sum(axis=1))
    return indices[int(np.argmin(totals))]


def backend_diagnostics(diagnostics, discovery):
    """Record actual standalone fitting hardware for run diagnostics."""
    panel = DiagnosticPanel(
        panel_id="fit-backend", title="Discovery execution", kind="text",
        description=(
            "Standalone discovery prefers cuML CUDA HDBSCAN on Euclidean vectors. "
            "GPU and CPU tie handling can differ; frozen classification remains portable."
        ),
        data={"backend": discovery.backend, "metric": "euclidean",
              "implementation": "cuml.HDBSCAN" if discovery.backend == "cuda"
              else "hdbscan.HDBSCAN" if discovery.backend == "cpu" else "insufficient_sample",
              "fit_precision": "float32" if discovery.backend == "cuda" else "float64",
              "neighbor_build": "brute_force" if discovery.backend == "cuda" else None},
    )
    warnings = diagnostics.warnings + ((discovery.warning,) if discovery.warning else ())
    return diagnostics.model_copy(update={"panels": (*diagnostics.panels, panel), "warnings": warnings})
