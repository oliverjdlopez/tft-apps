"""Adapter measurements with explicit fit hardware and CPU/CUDA distance kernels."""

import time
import numpy as np
from scipy.spatial.distance import pdist, squareform
from domain.compositions.adapter import deserialize_model, serialize_model
from domain.compositions.distance import board_distance
from domain.compositions.features import structural_features
from domain.compositions.registry import get_adapter
from domain.compositions.utils import validate_references


class CudaUnavailable(RuntimeError):
    """Mark a missing optional GPU runtime as skipped rather than a CPU result."""


def prepare_cuda():
    """Initialize the optional CUDA runtime once and return public device metadata."""
    try:
        import cupy as cp

        properties = cp.cuda.runtime.getDeviceProperties(cp.cuda.Device().id)
        cp.zeros(1).sum().get()
    except Exception as error:
        raise CudaUnavailable(
            "CUDA unavailable; install cupy-cuda12x with a compatible CUDA toolkit and accessible NVIDIA GPU"
        ) from error
    name = properties["name"]
    return {
        "name": name.decode() if isinstance(name, bytes) else name,
        "memory_bytes": int(properties["totalGlobalMem"]),
        "runtime_version": cp.cuda.runtime.runtimeGetVersion(),
    }


def encode_boards(boards):
    """Encode once into the same dense float64 feature matrix for both backends."""
    features = [structural_features(board) for board in boards]
    keys = sorted({key for row in features for key in row})
    return np.array(
        [[row.get(key, 0.0) for key in keys] for row in features], dtype=np.float64
    )


def cpu_distances(matrix):
    """Use the application's compiled symmetric SciPy distance implementation."""
    if not matrix.shape[1]:
        return np.zeros((len(matrix), len(matrix)))
    return squareform(pdist(matrix, metric="euclidean"))


def cuda_distances(matrix):
    """Compute Euclidean distances directly, including synchronized host transfers.

    Each CUDA thread owns one board pair. Feature-major storage coalesces reads
    across neighboring reference boards and avoids an N x N x features tensor.
    This is a benchmark kernel, not a replacement for production adapters.
    """
    import cupy as cp

    n, features = matrix.shape
    device = cp.asarray(np.ascontiguousarray(matrix.T))
    result = cp.empty(n * n, dtype=cp.float64)
    kernel = cp.RawKernel(
        r"""
    extern "C" __global__ void distances(const double* x, double* out, int n, int f) {
        long pair = (long)blockDim.x * blockIdx.x + threadIdx.x;
        if (pair >= (long)n * n) return;
        int left = pair / n, right = pair % n;
        double squared = 0.0;
        for (int k = 0; k < f; ++k) {
            double a = x[(long)k * n + left], b = x[(long)k * n + right];
            double delta = a - b;
            squared += delta * delta;
        }
        out[pair] = sqrt(squared);
    }
    """,
        "distances",
    )
    kernel(
        ((n * n + 255) // 256,),
        (256,),
        (device, result, np.int32(n), np.int32(features)),
    )
    # asnumpy blocks until the result is actually ready; timing cannot report
    # just the asynchronous launch. The reported duration includes both copies.
    return cp.asnumpy(result).reshape(n, n)


def check_distances(boards, matrix):
    """Compare deterministic sampled pairs against the original scalar metric."""
    if not np.isfinite(matrix).all():
        raise ValueError("Distance result contains nonfinite values")
    points = np.unique(np.linspace(0, len(boards) - 1, min(len(boards), 12), dtype=int))
    error = max(
        abs(float(matrix[i, j]) - board_distance(boards[i], boards[j]))
        for i in points
        for j in points
    )
    if error > 1e-12:
        raise ValueError(f"Distance parity failed: maximum sampled error {error}")
    return error


def measure_distance(boards, backend):
    """Time encoding and synchronized computation separately; verify outside timing."""
    started = time.perf_counter()
    encoded = encode_boards(boards)
    prepared = time.perf_counter()
    matrix = cuda_distances(encoded) if backend == "cuda" else cpu_distances(encoded)
    finished = time.perf_counter()
    return {
        "prepare_seconds": prepared - started,
        "compute_seconds": finished - prepared,
        "total_seconds": finished - started,
        "features": encoded.shape[1],
        "matrix_bytes": matrix.nbytes,
        "max_distance_error": check_distances(boards, matrix),
    }


def measure_adapter(boards, case):
    """Time existing fit, frozen-model serialization, and classification operations."""
    adapter = get_adapter(case.algorithm)
    parameters = adapter.Parameters.model_validate(case.parameters)
    started = time.perf_counter()
    fit = adapter.fit(boards, parameters, case.seed)
    fitted = time.perf_counter()
    model = deserialize_model(serialize_model(fit.model))
    frozen = time.perf_counter()
    from domain.compositions.acceleration import classification_backend

    with classification_backend(case.backend):
        assignments = adapter.classify(boards, model)
    finished = time.perf_counter()
    validate_references(boards, model.families, assignments)
    return {
        "fit_backend": next(
            (panel.data["backend"] for panel in fit.diagnostics.panels if panel.panel_id == "fit-backend"),
            "cpu",
        ),
        "fit_seconds": fitted - started,
        "freeze_seconds": frozen - fitted,
        "classify_seconds": finished - frozen,
        "total_seconds": finished - started,
        "families": len(model.families),
        "coverage": sum(a.status == "assigned" for a in assignments) / len(boards),
        "ambiguity": sum(a.status == "ambiguous" for a in assignments) / len(boards),
    }
