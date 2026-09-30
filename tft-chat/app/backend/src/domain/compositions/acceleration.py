"""Bounded CPU/CUDA reference matching for frozen composition classifiers."""

from contextlib import contextmanager
from contextvars import ContextVar
import logging
from typing import Literal

import numpy as np

from .utils import (
    encode_reference_boards,
    cuda_reference_distances,
    cuda_group_minima,
    cpu_reference_distances,
    cuda_available,
)

Backend = Literal["auto", "cpu", "cuda"]
_backend: ContextVar[Backend] = ContextVar(
    "composition_classification_backend", default="auto"
)
logger = logging.getLogger(__name__)


@contextmanager
def classification_backend(backend: Backend):
    """Select execution hardware locally without changing frozen model semantics.

    Args:
        backend: Auto uses CUDA for larger batches when available; explicit CUDA
            refuses fallback so benchmark rows cannot be mislabeled.
    """
    if backend not in ("auto", "cpu", "cuda"):
        raise ValueError("Unknown classification backend")
    token = _backend.set(backend)
    try:
        yield
    finally:
        _backend.reset(token)


def grouped_reference_distances(boards, groups, *, batch_size=128, metric="euclidean"):
    """Yield minimum reference distance per group in board and group input order.

    Args:
        boards: New outcome-free observations; all features contribute to distance.
        groups: Nonempty frozen reference sequences, one per family or variation.
        batch_size: Maximum query rows materialized in a distance block.
        metric: Frozen Euclidean or legacy weighted Jaccard distance semantics.

    Yields:
        A vector of group minima per input board. CUDA keeps frozen features on
        device across query blocks and returns only reduced group scores.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not boards:
        return
    if any(not group for group in groups):
        raise ValueError("Reference groups must be nonempty")
    if not groups:
        for _ in boards:
            yield np.empty(0)
        return
    references = tuple(reference for group in groups for reference in group)
    queries, frozen = encode_reference_boards(boards, references)
    starts = np.cumsum([0, *(len(group) for group in groups[:-1])])
    requested = _backend.get()
    use_cuda = requested == "cuda" or (
        requested == "auto"
        and len(boards) * len(references) >= 65536
        and cuda_available()
    )
    device = None
    if use_cuda:
        try:
            import cupy as cp

            device = cp.asarray(np.ascontiguousarray(frozen.T))
        except Exception:
            if requested == "cuda":
                raise
            logger.warning(
                "CUDA reference preparation failed; using CPU", exc_info=True
            )
            use_cuda = False
    for offset in range(0, len(boards), batch_size):
        block = queries[offset : offset + batch_size]
        if use_cuda:
            try:
                distances = cuda_reference_distances(block, device, len(frozen), metric)
                # References are contiguous by group; reduction avoids copying
                # the full query/reference matrix back to the host.
                reduced = cuda_group_minima(distances, starts)
                yield from cp.asnumpy(reduced)
                continue
            except Exception:
                if requested == "cuda":
                    raise
                logger.warning(
                    "CUDA reference matching failed; using CPU", exc_info=True
                )
                use_cuda = False
                device = None
        distances = cpu_reference_distances(block, frozen, metric)
        yield from np.minimum.reduceat(distances, starts, axis=1)
