"""Shared whole-board distance with no outcomes or database dependencies."""

from .features import structural_features


def feature_distance(left, right, *, metric="euclidean") -> float:
    """Compare weighted feature coordinates, retaining Jaccard for saved v1 models."""
    import math

    keys = sorted(left.keys() | right.keys())
    if metric == "euclidean":
        return math.sqrt(sum((left.get(k, 0) - right.get(k, 0)) ** 2 for k in keys))
    if metric != "weighted_jaccard":
        raise ValueError("Unknown structural distance metric")
    denominator = sum(max(left.get(k, 0), right.get(k, 0)) for k in keys)
    return (
        1.0 - sum(min(left.get(k, 0), right.get(k, 0)) for k in keys) / denominator
        if denominator
        else 0.0
    )


def board_distance(left, right, *, metric="euclidean") -> float:
    """Compare complete observed structures while emphasizing itemized anchors."""
    return feature_distance(structural_features(left), structural_features(right), metric=metric)


def distance_matrix(boards):
    """Build the bounded discovery sample's symmetric precomputed distances."""
    import numpy as np
    from scipy.spatial.distance import pdist, squareform

    features = [structural_features(b) for b in boards]
    keys = sorted({key for f in features for key in f})
    if not keys:
        return np.zeros((len(boards), len(boards)))
    matrix = np.array([[f.get(k, 0.0) for k in keys] for f in features])
    # Keep the existing weighted coordinates; no normalization or learned
    # embedding changes the geometry seen by discovery and classification.
    return squareform(pdist(matrix, metric="euclidean"))
