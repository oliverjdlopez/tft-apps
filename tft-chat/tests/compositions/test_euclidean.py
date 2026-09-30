"""Distance migration coverage for geometry, bounded matching, and saved models."""

import math

import numpy as np
import pytest

from domain.compositions.acceleration import classification_backend, grouped_reference_distances
from domain.compositions.adapter import deserialize_model, serialize_model
from domain.compositions.distance import board_distance, distance_matrix, feature_distance
from domain.compositions.features import structural_features
from domain.compositions.fixtures import fixture_boards
from domain.compositions.models import BoardObservation, EntityRef
from domain.compositions.registry import get_adapter


def test_euclidean_coordinates_are_unbounded_and_not_normalized():
    """Use the existing coordinate weights inside L2 without Jaccard normalization."""
    assert feature_distance({"a": 3}, {"b": 4}) == 5
    assert feature_distance({"a": 6}, {"b": 8}) == 10
    assert feature_distance({}, {}) == 0
    assert feature_distance({"holder": 2}, {}) == 2
    assert feature_distance({"star": 0.25}, {}) == 0.25
    with pytest.raises(ValueError):
        feature_distance({}, {}, metric="unknown")


def test_discovery_and_batched_matching_use_same_euclidean_geometry():
    """Check real board features, unseen keys, empty boards, and distances above one."""
    boards = fixture_boards()
    empty = BoardObservation(observation_id="empty", level=None, units=(), traits=())
    sample = (boards[0], boards[1], boards[13], empty)
    features = [structural_features(board) for board in sample]
    keys = sorted({key for row in features for key in row})
    vectors = np.array([[row.get(key, 0) for key in keys] for row in features])
    expected = np.linalg.norm(vectors[:, None, :] - vectors[None, :, :], axis=2)
    assert expected.max() > 1
    np.testing.assert_allclose(distance_matrix(sample), expected, rtol=0, atol=1e-12)
    with classification_backend("cpu"):
        actual = list(grouped_reference_distances(sample, [(b,) for b in sample], batch_size=1))
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12)
    assert distance_matrix(()).shape == (0, 0)
    assert distance_matrix((empty,)).tolist() == [[0.0]]


@pytest.mark.parametrize("name", ["hdbscan"])
def test_saved_v1_models_keep_jaccard_matching(name):
    """An old model's reference geometry stays Jaccard across JSON restoration."""
    adapter = get_adapter(name)
    boards = fixture_boards()
    parameters = adapter.Parameters()
    fitted = adapter.fit(boards, parameters, 42).model
    assert fitted.algorithm_version == ("3" if name == "hdbscan" else "2")
    # A renamed unitemized flex creates a known nonzero distance that is accepted
    # under the old threshold but rejected under the same numerical L2 threshold.
    query = boards[1].model_copy(update={
        "observation_id": "novel-flex",
        "units": (*boards[1].units[:2], boards[1].units[2].model_copy(
            update={"unit": EntityRef(key="Novel", name="Novel")})),
    })
    settings = {**fitted.effective_parameters, "rejection_distance": 0.6}
    new = fitted.model_copy(update={"effective_parameters": settings})
    old = deserialize_model(serialize_model(new.model_copy(update={"algorithm_version": "1"})))
    with classification_backend("cpu"):
        legacy = adapter.classify((query,), old)[0]
        current = adapter.classify((query,), new)[0]
    assert legacy.status == "assigned"
    assert current.status == "unclassified"
    expected = min(board_distance(query, board, metric="weighted_jaccard") for board in boards)
    assert legacy.candidates[0].score.value == pytest.approx(expected)
    assert current.candidates[0].score.value > 1


@pytest.mark.parametrize("name", ["hdbscan"])
def test_euclidean_distance_thresholds_accept_values_above_one(name):
    """Distance controls permit nonnegative L2 units without relaxing score bounds."""
    parameters = get_adapter(name).Parameters(rejection_distance=5)
    assert parameters.rejection_distance == 5
    with pytest.raises(ValueError):
        get_adapter(name).Parameters(rejection_distance=math.inf)
