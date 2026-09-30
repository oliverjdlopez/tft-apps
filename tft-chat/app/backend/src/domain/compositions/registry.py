"""HDBSCAN is the sole production composition discovery algorithm."""

ALGORITHM_IDS = ("hdbscan",)


def get_adapter(algorithm_id):
    """Load one named implementation without consulting another adapter's output."""
    if algorithm_id == "reference_fixture":
        from .reference import ReferenceAdapter

        return ReferenceAdapter()
    if algorithm_id not in ALGORITHM_IDS:
        raise ValueError("Unknown composition algorithm")
    from .algorithms.hdbscan import Adapter

    return Adapter()
