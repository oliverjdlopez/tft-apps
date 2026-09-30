"""Outcome-separated pure execution pipeline, reusable in process tests."""

from domain.compositions.registry import get_adapter
from domain.compositions.adapter import serialize_model, deserialize_model
from domain.compositions.utils import validate_references
from .models import ExperimentResult
from .utils import population_result
from domain.compositions.profiling import CompositionProfiler


def execute_snapshot(snapshot, request, progress=lambda stage: None, run_id=None):
    """Fit on the bounded sample, then classify independently using frozen state.

    Args:
        snapshot: Immutable anonymous inputs and separately stored outcomes.
        request: Frozen validated run settings.
        progress: Worker-owned persistent stage callback.
    """
    adapter = get_adapter(request.algorithm_id)
    profiler = CompositionProfiler()
    if (
        request.algorithm_version is not None
        and request.algorithm_version != adapter.algorithm_version
    ):
        raise ValueError(
            "Queued algorithm version no longer matches this implementation"
        )
    sample_ids = set(snapshot.sample_ids)
    sample = tuple(b for b in snapshot.boards if b.observation_id in sample_ids)
    progress("fitting")
    with profiler.stage("fit"):
        fit = adapter.fit(
            sample, adapter.Parameters.model_validate(request.parameters), request.seed,
            **({"run_id": run_id} if request.algorithm_id == "hdbscan" else {}),
        )
    with profiler.stage("validate_discovery_references"):
        validate_references(sample, fit.model.families, fit.discovery_assignments)
    # Classification always crosses serialization, ensuring no in-memory estimator
    # or labels can secretly supply state unavailable to a reopened experiment.
    with profiler.stage("model_serialization_roundtrip"):
        model = deserialize_model(serialize_model(fit.model))
    progress("classifying_sample")
    with profiler.stage("classify_sample"):
        assignments = adapter.classify(sample, model)
        validate_references(sample, model.families, assignments)
    minimum = 1 if request.source_kind == "fixture" else 50
    with profiler.stage("aggregate_sample_profiles"):
        populations = [
            population_result(
                "discovery_sample", sample, snapshot.outcomes, model.families,
                assignments, minimum,
            )
        ]
    if request.full_population:
        if not snapshot.includes_full_population:
            raise ValueError("Saved snapshot lacks the requested population")
        progress("classifying_population")
        if len(sample) != len(snapshot.boards):
            full_assignments = []
            with profiler.stage("classify_full_population"):
                for offset in range(0, len(snapshot.boards), 256):
                    full_assignments.extend(
                        adapter.classify(snapshot.boards[offset : offset + 256], model)
                    )
                    progress("classifying_population")
            assignments = tuple(full_assignments)
        validate_references(snapshot.boards, model.families, assignments)
        with profiler.stage("aggregate_full_population_profiles"):
            populations.append(
                population_result(
                    "full_population", snapshot.boards, snapshot.outcomes,
                    model.families, assignments, minimum,
                )
            )
    progress("aggregating")
    result = ExperimentResult(
        model=model,
        diagnostics=fit.diagnostics,
        discovery_assignments=fit.discovery_assignments,
        populations=tuple(populations),
    )
    if request.algorithm_id == "hdbscan" and run_id is not None:
        from domain.compositions.algorithms.hdbscan import append_execution_profile

        append_execution_profile(run_id, profiler.report())
    return result
