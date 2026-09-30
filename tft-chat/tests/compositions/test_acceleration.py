"""Exact matching parity, bounded execution, and optional CUDA fallback checks."""

import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from domain.compositions import acceleration
from domain.compositions.distance import board_distance
from domain.compositions.fixtures import fixture_boards
from domain.compositions.models import EntityRef
from domain.compositions.registry import get_adapter
from domain.compositions.utils import reference_assignments


def test_grouped_cpu_matches_scalar_and_preserves_empty_and_unseen_features():
    """Retain unknown-query penalties, group order, and scalar threshold arithmetic."""
    boards = fixture_boards()
    empty = boards[0].model_copy(
        update={"observation_id": "empty", "units": (), "traits": ()}
    )
    unseen = boards[0].model_copy(
        update={
            "observation_id": "unseen",
            "units": (
                boards[0]
                .units[0]
                .model_copy(update={"unit": EntityRef(key="novel", name="Novel")}),
            ),
        }
    )
    queries = (empty, unseen, *reversed(boards))
    groups = (boards[:12], boards[12:], (empty,))
    expected = [
        [min(board_distance(q, r) for r in group) for group in groups] for q in queries
    ]
    with acceleration.classification_backend("cpu"):
        actual = list(
            acceleration.grouped_reference_distances(queries, groups, batch_size=3)
        )
    np.testing.assert_array_equal(actual, expected)
    with acceleration.classification_backend("cpu"):
        assert list(acceleration.grouped_reference_distances((), groups)) == []
        assert len(list(acceleration.grouped_reference_distances(queries, ()))) == len(
            queries
        )


def test_hdbscan_fast_cpu_matches_legacy_assignment_objects_at_boundary():
    """Keep family IDs, ambiguity, evidence strings, and exact distances identical."""
    adapter = get_adapter("hdbscan")
    boards = fixture_boards()
    model = adapter.fit(boards, adapter.Parameters(), 42).model
    refs = {
        group["family_id"]: tuple(
            type(boards[0]).model_validate(b) for b in group["references"]
        )
        for group in model.state["clusters"]
    }
    for rejection, margin in ((0, 0), (0.45, 0.05), (1, 1)):
        legacy = reference_assignments(boards, model.families, refs, rejection, margin)
        with acceleration.classification_backend("cpu"):
            fast = reference_assignments(
                boards, model.families, refs, rejection, margin, accelerated=True
            )
        assert fast == legacy


def test_auto_fallback_and_explicit_cuda_failure(monkeypatch):
    """Only auto may recover from GPU errors; explicit benchmark CUDA must fail."""
    boards = fixture_boards() * 12
    groups = (boards[:150], boards[150:])
    fake = SimpleNamespace(asarray=np.asarray, minimum=np.minimum, asnumpy=np.asarray)
    monkeypatch.setitem(sys.modules, "cupy", fake)
    monkeypatch.setattr(acceleration, "cuda_available", lambda: True)
    calls = []

    def fail(*args):
        """Simulate a runtime GPU failure after device preparation."""
        calls.append(1)
        raise RuntimeError("device unavailable")

    monkeypatch.setattr(acceleration, "cuda_reference_distances", fail)
    with acceleration.classification_backend("cpu"):
        expected = list(acceleration.grouped_reference_distances(boards, groups))
    with acceleration.classification_backend("auto"):
        actual = list(acceleration.grouped_reference_distances(boards, groups))
    np.testing.assert_array_equal(actual, expected)
    assert len(calls) == 1
    with (
        acceleration.classification_backend("cuda"),
        pytest.raises(RuntimeError, match="device unavailable"),
    ):
        list(acceleration.grouped_reference_distances(boards, groups))


@pytest.mark.skipif(
    os.environ.get("CHATTFT_BENCHMARK_CUDA_TEST") != "1", reason="Actual CUDA required"
)
@pytest.mark.parametrize("name", ["hdbscan"])
@pytest.mark.parametrize("version", ["1", "2"])
def test_cuda_matches_cpu_frozen_classifiers(name, version):
    """Compare complete assignments including candidate evidence on real CUDA."""
    adapter = get_adapter(name)
    boards = fixture_boards()
    model = adapter.fit(boards, adapter.Parameters(), 42).model.model_copy(
        update={"algorithm_version": version}
    )
    metric = "weighted_jaccard" if version == "1" else "euclidean"
    empty = boards[0].model_copy(
        update={"observation_id": "empty", "units": (), "traits": ()}
    )
    queries = (*reversed(boards), empty)
    with acceleration.classification_backend("cpu"):
        expected = adapter.classify(queries, model)
    with acceleration.classification_backend("cuda"):
        assert adapter.classify(queries, model) == expected
        refs = (boards[:12], boards[12:])
        scores = list(
            acceleration.grouped_reference_distances(queries, refs, batch_size=3, metric=metric)
        )
    np.testing.assert_array_equal(
        scores,
        [[min(board_distance(q, r, metric=metric) for r in group) for group in refs] for q in queries],
    )
