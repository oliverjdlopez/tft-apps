"""Standalone cuML routing and portable HDBSCAN results."""

import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from domain.compositions.adapter import deserialize_model, serialize_model
from domain.compositions.algorithms.hdbscan import Adapter
from domain.compositions.algorithms.hdbscan import utils
from domain.compositions.fixtures import fixture_boards


def test_standalone_passes_vectors_and_parameters_to_cuml(monkeypatch):
    """Never build a CPU square matrix when standalone fitting selects cuML."""
    captured = {}

    class Estimator:
        """Capture the cuML contract without needing CUDA in the unit test suite."""

        def __init__(self, **settings):
            """Record all density controls and the selected neighbor algorithm."""
            captured["settings"] = settings

        def fit(self, vectors):
            """Return representative native outputs with two known fixture groups."""
            captured["vectors"] = vectors
            self.labels_ = np.repeat([0, 1], 12)
            self.probabilities_ = np.full(24, 0.75)
            self.cluster_persistence_ = np.array([0.8, 0.9])
            return self

    def forbid_matrix(*args):
        """Catch accidental CPU pairwise discovery work in the GPU path."""
        raise AssertionError("CPU discovery matrix must not be constructed")

    def first_member(vectors, indices):
        """Keep this routing test independent of GPU medoid arithmetic."""
        assert vectors.dtype == np.float64
        return indices[0]

    monkeypatch.setattr(utils, "gpu_estimator", lambda: (Estimator, None))
    monkeypatch.setattr(utils, "distance_matrix", forbid_matrix)
    monkeypatch.setattr(utils, "gpu_medoid", first_member)
    monkeypatch.setitem(sys.modules, "cupy", SimpleNamespace(asarray=np.asarray, float32=np.float32))
    parameters = Adapter.Parameters(min_cluster_size=4, min_samples=2, cluster_selection_epsilon=0.3)
    result = Adapter().fit(fixture_boards(), parameters, 42)
    assert captured["vectors"].shape[0] == 24
    assert captured["vectors"].dtype == np.float32
    assert captured["settings"]["metric"] == "euclidean"
    assert captured["settings"]["build_algo"] == "brute_force"
    assert captured["settings"]["build_kwds"] == {"knn_n_clusters": 1}
    for key in ("min_cluster_size", "min_samples", "cluster_selection_epsilon",
                "cluster_selection_method", "allow_single_cluster"):
        assert captured["settings"][key] == getattr(parameters, key)
    assert result.model.algorithm_version == "3"
    assert result.diagnostics.panels[-1].data["backend"] == "cuda"
    assert all(a.candidates[0].score.value == 0.75 for a in result.discovery_assignments)
    restored = deserialize_model(serialize_model(result.model))
    assert Adapter().classify(fixture_boards(), restored) == Adapter().classify(fixture_boards(), result.model)


def test_missing_cuml_fallback_is_visible(monkeypatch):
    """An unavailable optional runtime records CPU execution explicitly."""
    monkeypatch.setattr(utils, "gpu_estimator", lambda: (None, "Test runtime unavailable; CPU fallback."))
    boards = fixture_boards()
    result = Adapter().fit(boards, Adapter.Parameters(), 1)
    reference = Adapter().fit(boards, Adapter.Parameters(), 1)
    assert result.discovery_assignments == reference.discovery_assignments
    assert result.model.state == reference.model.state
    assert result.diagnostics.panels[-1].data["backend"] == "cpu"
    assert "CPU fallback" in result.diagnostics.warnings[-1]


def test_gpu_fitting_errors_do_not_silently_refit_on_cpu(monkeypatch):
    """CUDA fitting failures stay failures after the backend has been selected."""
    monkeypatch.setattr(utils, "gpu_estimator", lambda: (object, None))

    def fail(*args):
        """Simulate an out-of-memory failure during actual GPU fitting."""
        raise RuntimeError("GPU fit failed")

    monkeypatch.setattr(utils, "discover_cuda", fail)
    with pytest.raises(RuntimeError, match="GPU fit failed"):
        Adapter().fit(fixture_boards(), Adapter.Parameters(), 42)


def test_small_discovery_does_not_require_gpu(monkeypatch):
    """Empty or insufficient samples keep their existing no-family behavior."""
    def forbidden():
        """Fail if an unnecessary optional GPU runtime is initialized."""
        raise AssertionError("Insufficient samples do not need GPU initialization")

    monkeypatch.setattr(utils, "gpu_estimator", forbidden)
    adapter = Adapter()
    for boards in ((), fixture_boards()[:1]):
        result = adapter.fit(boards, adapter.Parameters(), 42)
        assert result.model.families == ()
        assert result.diagnostics.panels[-1].data["backend"] == "not_required"


@pytest.mark.skipif(os.environ.get("CHATTFT_HDBSCAN_CUDA_TEST") != "1", reason="Opt-in actual cuML fit")
def test_real_cuml_fit_and_gpu_medoids(monkeypatch):
    """Exercise actual GPU clustering and medoids without a CPU distance matrix."""
    from domain.compositions.distance import board_distance

    estimator, reason = utils.gpu_estimator()
    assert estimator is not None, reason

    def forbidden(*args):
        """Ensure hardware integration does not hide a CPU discovery matrix."""
        raise AssertionError("CPU square matrix must not be used")

    monkeypatch.setattr(utils, "distance_matrix", forbidden)
    boards = fixture_boards()
    result = Adapter().fit(boards, Adapter.Parameters(), 42)
    assert result.diagnostics.panels[-1].data["backend"] == "cuda"
    assert result.model.families
    assert len(result.discovery_assignments) == len(boards)
    _, state = utils.validate_model(result.model)
    for cluster, family in zip(state.clusters, result.model.families):
        representative = family.representative_observation_ids[0]
        totals = {board.observation_id: sum(board_distance(board, other) for other in cluster.references)
                  for board in cluster.references}
        assert totals[representative] == pytest.approx(min(totals.values()))
    restored = deserialize_model(serialize_model(result.model))
    assert Adapter().classify(boards, restored) == Adapter().classify(boards, result.model)
