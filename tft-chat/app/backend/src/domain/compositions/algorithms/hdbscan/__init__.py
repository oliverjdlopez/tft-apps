"""Density-based composition discovery with portable frozen reference matching."""

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import logging

from ...models import BoardAssignment, BoardObservation, FitResult, FrozenModel
from ...utils import model_distance_metric, reference_assignments
from .models import Parameters, State
from .utils import (
    diagnostic_panels,
    discover,
    discover_standalone,
    backend_diagnostics,
    freeze_clusters,
    native_assignment,
    validate_model,
)

logger = logging.getLogger(__name__)


class Adapter:
    """Discover HDBSCAN density families independently of later reference matching."""

    algorithm_id = "hdbscan"
    algorithm_version = "3"
    gpu_discovery = True
    Parameters = Parameters

    def fit(
        self, boards: tuple[BoardObservation, ...], parameters: Parameters, seed: int,
        run_id: str | None = None,
    ) -> FitResult:
        """Freeze native families and density diagnostics from outcome-free boards.

        Args:
            boards: Discovery snapshot with unique experiment-local identities.
            parameters: Density and reference matching settings.
            seed: Recorded run seed; no random seed is accepted by cuML HDBSCAN.

        Returns:
            Frozen references, native discovery assignments, and diagnostics.
        """
        parameters = Parameters.model_validate(parameters)
        if len({board.observation_id for board in boards}) != len(boards):
            raise ValueError("HDBSCAN discovery requires unique observation IDs")
        # Canonical ordering stabilizes reference identities when the same snapshot arrives
        # in another order; assignment output still follows the caller's order.
        eligible = tuple(
            sorted(
                (board for board in boards if board.units),
                key=lambda board: board.observation_id,
            )
        )
        fit_started = perf_counter()
        discovery_started = perf_counter()
        discovery = discover_standalone(eligible, parameters) if self.gpu_discovery else None
        if discovery is None:
            distances, labels, strengths, persistence = discover(eligible, parameters)
        else:
            distances, labels, strengths, persistence = (
                discovery.distances, discovery.labels, discovery.strengths, discovery.persistence
            )
        discovery_seconds = perf_counter() - discovery_started
        freeze_started = perf_counter()
        families, clusters, label_families = freeze_clusters(
            eligible, distances, labels, persistence,
            vectors=discovery.vectors if discovery is not None else None,
        )
        freeze_seconds = perf_counter() - freeze_started
        native = {
            board.observation_id: (int(label), float(strength))
            for board, label, strength in zip(eligible, labels, strengths)
        }
        assignments = tuple(
            native_assignment(
                board, *native.get(board.observation_id, (-1, 0.0)), label_families
            )
            for board in boards
        )
        state = State(
            seed=seed,
            clusters=clusters,
            noise_observation_ids=tuple(
                sorted(
                    a.observation_id for a in assignments if a.status == "unclassified"
                )
            ),
        )
        model = FrozenModel(
            algorithm_id=self.algorithm_id,
            algorithm_version=self.algorithm_version,
            effective_parameters=parameters.model_dump(mode="json"),
            families=families,
            state=state.model_dump(mode="json"),
        )
        diagnostics = diagnostic_panels(
            boards,
            assignments,
            clusters,
            {key: value[1] for key, value in native.items()},
            parameters,
        )
        if discovery is not None:
            diagnostics = backend_diagnostics(diagnostics, discovery)
        if run_id is not None:
            try:
                _save_profile(
                    run_id, boards, eligible, parameters, seed, discovery, labels,
                    strengths, persistence, families, clusters,
                    perf_counter() - fit_started, discovery_seconds,
                    freeze_seconds,
                )
            except OSError:
                logger.exception("Could not write HDBSCAN run profile")
        return FitResult(
            model=model, discovery_assignments=assignments, diagnostics=diagnostics
        )

    def classify(
        self, boards: tuple[BoardObservation, ...], model: FrozenModel
    ) -> tuple[BoardAssignment, ...]:
        """Match independently against frozen native references, preserving ambiguity.

        Args:
            boards: New observations in the desired assignment order.
            model: Validated JSON-compatible HDBSCAN reference state.

        Returns:
            Exactly one assignment per input, without changing native definitions.
        """
        parameters, state = validate_model(model)
        references = {
            cluster.family_id: cluster.references for cluster in state.clusters
        }
        assignments = reference_assignments(
            boards,
            model.families,
            references,
            parameters.rejection_distance,
            parameters.ambiguity_margin,
            metric=model_distance_metric(model),
            accelerated=True,
        )
        return tuple(
            assignment if board.units else native_assignment(board, -1, 0.0, {})
            for board, assignment in zip(boards, assignments)
        )


def _save_profile(run_id, boards, eligible, parameters, seed, discovery, labels,
                  strengths, persistence, families, clusters, fit_seconds,
                  discovery_seconds, freeze_seconds):
    """Write algorithm-specific fit statistics for a completed HDBSCAN run."""
    import numpy as np

    backend = discovery.backend if discovery is not None else "cpu"
    labels = np.asarray(labels, dtype=int)
    strengths = np.asarray(strengths, dtype=float)
    noise = int(np.count_nonzero(labels < 0))
    cluster_sizes = [int(np.count_nonzero(labels == label))
                     for label in sorted(set(labels.tolist()) - {-1})]
    matrix_bytes = len(eligible) ** 2 * 8 if backend == "cpu" else 0
    vectors = discovery.vectors if discovery is not None else None
    lines = [
        "HDBSCAN algorithm profile",
        f"Run UUID: {run_id}",
        f"Fit completed: {datetime.now(timezone.utc).isoformat()}",
        f"Implementation: {'cuML' if backend == 'cuda' else 'hdbscan CPU' if backend == 'cpu' else 'not required'}",
        f"Backend: {backend}",
        f"Seed: {seed}",
        f"Input boards: {len(boards)}",
        f"Boards with observed units: {len(eligible)}",
        f"Excluded empty boards: {len(boards) - len(eligible)}",
        f"Estimated CPU distance matrix bytes: {matrix_bytes}",
        f"Feature matrix shape: {tuple(vectors.shape) if vectors is not None else 'not retained'}",
        f"Feature matrix bytes: {int(vectors.nbytes) if vectors is not None else 'not retained'}",
        f"Fit wall seconds: {fit_seconds:.6f}",
        f"Density discovery seconds: {discovery_seconds:.6f}",
        f"Cluster freezing and medoid selection seconds: {freeze_seconds:.6f}",
        f"min_cluster_size: {parameters.min_cluster_size}",
        f"min_samples: {parameters.min_samples}",
        f"Cluster count: {len(cluster_sizes)}",
        f"Cluster sizes: {cluster_sizes}",
        f"Noise count: {noise}",
        f"Noise fraction: {noise / len(eligible):.6f}" if eligible else "Noise fraction: n/a",
        f"Membership strength mean: {float(strengths.mean()) if len(strengths) else 0:.6f}",
        f"Membership strength median: {float(np.median(strengths)) if len(strengths) else 0:.6f}",
        f"Membership strength min/max: {float(strengths.min()) if len(strengths) else 0:.6f} / {float(strengths.max()) if len(strengths) else 0:.6f}",
        f"Cluster persistence: {[float(value) for value in persistence]}",
        f"Frozen families: {len(families)}",
        f"Retained native references: {sum(len(cluster.references) for cluster in clusters)}",
    ]
    profile_dir = Path(__file__).resolve().parents[7] / "profiles" / "compositions" / "hdbscan"
    profile_dir.mkdir(parents=True, exist_ok=True)
    # Keep partial reports out of the completed-profile namespace if later
    # classification or persistence fails.
    (profile_dir / f"{run_id}.pending").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def append_execution_profile(run_id, report):
    """Append composition pipeline stages after a successful HDBSCAN execution."""
    directory = Path(__file__).resolve().parents[7] / "profiles" / "compositions" / "hdbscan"
    pending = directory / f"{run_id}.pending"
    try:
        with pending.open("a", encoding="utf-8") as profile:
            profile.write("\n" + report)
        pending.replace(directory / f"{run_id}.txt")
    except OSError:
        logger.exception("Could not finalize HDBSCAN run profile %s", run_id)
