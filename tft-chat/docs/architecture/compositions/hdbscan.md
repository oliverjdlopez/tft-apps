# HDBSCAN composition discovery

The independent adapter in
[`algorithms/hdbscan`](../../../app/backend/src/domain/compositions/algorithms/hdbscan/__init__.py)
implements [adapter contract v1](adapter.md). New standalone fits use algorithm
version 3 and prefer NVIDIA cuML HDBSCAN on CUDA. CPU feature encoding produces
the existing weighted coordinates; cuML receives a float32 feature matrix with
Euclidean distance and brute-force neighbor construction (`knn_n_clusters=1`).
It performs density clustering on GPU without an application-created CPU square
distance matrix. The original `hdbscan` generic/precomputed fitter remains an
explicitly reported fallback when cuML or CUDA is unavailable.

Discovery uses unit multiplicities,
stars, itemized holders, holder-bound item instances, and observed trait states;
level and outcomes never enter the distance.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `min_cluster_size` | 5 | Smallest selectable density cluster; integer at least 2 |
| `min_samples` | 3 | Neighborhood density requirement; integer at least 1 |
| `cluster_selection_method` | `eom` | Excess of mass selection, or `leaf` |
| `cluster_selection_epsilon` | 0 | Merge selection threshold in structural distance units, finite and nonnegative |
| `allow_single_cluster` | false | Permit selection of the root density cluster |
| `rejection_distance` | 2.0 | Maximum accepted frozen reference distance |
| `ambiguity_margin` | 0.05 | Mark competing accepted families ambiguous when their distance gap is at most this value |

Every effective parameter, including classification thresholds, is serialized.
The run seed is recorded; cuML HDBSCAN does not accept a random seed. Observation
IDs determine canonical input order and frozen-family ordering. GPU neighbor/MST
tie handling and float32 arithmetic can differ from the CPU fitter, so identical
CPU/GPU memberships or bitwise repeatability are not promised. Assignments retain caller
input order. Duplicate discovery observation IDs are rejected.

Native cluster members produce stable family IDs and a real medoid's joint
structure as the display definition. GPU medoids are selected from actual native
members using float64 Euclidean distance blocks of at most 128 query rows against
one cluster's references; only per-row sums return to the host. This avoids
recreating a full CPU matrix just to select representatives. Repeated champions and repeated items stay
separate occurrences. All native non-noise members are retained as reference
boards, including unknown trait measurements. Empty-unit observations are
excluded from density fitting and reported unclassified. Samples smaller than
`max(min_cluster_size, min_samples + 1)` yield no families and unclassified
observations instead of silently weakening the requested density settings.

## Discovery and later classification

Discovery assignments preserve HDBSCAN's native density labels and noise.
Their scores are native membership strengths, explicitly labeled similarity
scores rather than calibrated family probabilities. Diagnostics include native
noise count/fraction and observation rows, per-family cluster persistence and
member counts, and the complete frozen classification policy. A missing family
result carries a diagnostic warning. An empty population has a null noise
fraction, rather than an invented zero denominator.

The frozen classifier uses the minimum shared structural distance to any native
reference in each family. It applies the saved rejection threshold and ambiguity
margin and retains competing candidate scores. It does **not** call HDBSCAN's
`approximate_predict`: the application retains its portable nearest-reference
matching policy for both GPU and CPU discovered models. Consequently a discovery noise board may later be assigned by the frozen
reference classifier, particularly with permissive rejection settings. This is
a deliberately separate policy; it never rewrites the recorded native result.
Boards with no observed units remain unclassified regardless of thresholds.

Portable state uses `hdbscan.references.v1` and
`nearest_native_reference.v1`, with JSON-only reference boards, family IDs,
cluster persistence, seed, and native noise IDs. Classification validates the
algorithm/version/feature envelope, every effective parameter, state revisions,
unique reference memberships, representatives belonging to their frozen family,
and exact agreement between family definitions and reference groups. It rejects
unknown fields, nonfinite values, empty reference groups, and incompatible state.
No fitted estimator, pickle, database access, other algorithm implementation, or
outcome data is needed to classify a serialized model.

## Validation and limits

Run ordinary fallback/contract coverage with:

```bash
uv run --extra compositions pytest -q tests/compositions
```

Run actual cuML fitting, bounded GPU medoids, and classifier CUDA checks with:

```bash
CHATTFT_HDBSCAN_CUDA_TEST=1 CHATTFT_BENCHMARK_CUDA_TEST=1 \
  uv run --extra compositions --extra compositions-gpu pytest -q tests/compositions
```

The same test path can be run through the repository's configured Python test
environment once its composition dependencies are installed. Tests cover the
shared adapter contract, duplicate champions/items, harmless substitutions,
changed itemized anchors with shared frontlines, incomplete/empty observations,
noise versus frozen assignment, ambiguity, rejection, deterministic ordering,
JSON round trips, and incompatible settings/state.

GPU discovery avoids the application's quadratic CPU distance matrix, but cuML
still has its own device workspace requirements; this is not a VRAM bound.
The CPU fallback still materializes a quadratic distance matrix. Frozen classification retains every native cluster member and scales
with the number of new boards times the number of stored references. Cluster
persistence is a density stability diagnostic, not a gameplay quality measure.
Reference matching does not estimate new-point density membership, and missing
observations remain missing evidence rather than inferred inactive traits.

## CPU and GPU classification

Frozen reference matching now encodes each board once and evaluates bounded
128-query distance batches. CUDA keeps frozen features on device and reduces
reference scores to family/variation minima before copying them back. The CPU
fallback uses compiled SciPy Euclidean distances for version-2/3 models and
retains the L1-based weighted Jaccard calculation for saved version-1 models.

Install GPU support in this checkout with:

```sh
uv sync --extra compositions --extra compositions-gpu
```

With a compatible NVIDIA GPU and CUDA 12 toolkit, classification automatically
uses CUDA for calls with at least 65,536 query/reference pairs. Smaller calls and
installations without CUDA use CPU. Automatic mode falls back to CPU if device
preparation or execution fails; the backend log records runtime failures.
`domain.compositions.acceleration.classification_backend("cpu" | "cuda" | "auto")`
provides a scoped override for benchmarks and tests. Explicit CUDA raises on errors
instead of silently relabeling CPU work. The hardware choice is not a statistical
parameter and does not alter frozen model schemas or algorithm versions.

Standalone fitting prefers cuML independently of the classification backend
context manager. Diagnostics → Discovery execution records `cuda`, `cpu`, or
`not_required` for an insufficient sample, together with implementation, precision,
and neighbor build mode. An unavailable optional runtime produces a visible CPU
fallback warning. Once cuML fitting starts, GPU fit errors propagate rather than
silently triggering a CPU refit.

Every completed standalone HDBSCAN run writes
`profiles/compositions/hdbscan/<experiment-uuid>.txt` at the repository root.
The report includes backend, input and eligible counts, density parameters,
cluster sizes, noise fraction, membership-strength summaries, persistence values,
retained reference counts, fit duration, and estimated CPU distance-matrix size.
It also records wall and process-CPU time for fitting, validation, serialization,
classification, and aggregation stages, along with process peak RSS, host RAM, and
CUDA device memory snapshots when CuPy can query a device. RSS is a process-wide
high-water mark, while CUDA memory values are point-in-time snapshots. A run only
receives the `.txt` filename after its pipeline completes; interrupted or failed
runs can leave a `.pending` diagnostic.
Classification preserves the original distance, rejection thresholds, exact tie
rules, candidate evidence, family IDs, and HDBSCAN family IDs. New-query
features absent from fitted references still contribute to rejection distances.
All-empty structures retain zero distance, and adapters retain their empty-unit
rejection policy. Memory scales with the encoded feature matrices and one bounded
query/reference block, not a query-by-reference-by-feature tensor.

New standalone fits use algorithm version 3 and unnormalized Euclidean
coordinates. Saved version-2 models retain Euclidean matching and version-1
models retain Jaccard matching. Saved results remain readable; refitting older
version-pinned requests requires selecting the current implementation. See the [shared distance and
version contract](adapter.md) for threshold units, defaults, and rerun behavior.

The GPU extra pins cuML 26.8 and compatible CuPy 14 for CUDA 12; cuML installation
is enabled on Linux x86-64/aarch64. Use a compatible NVIDIA driver/runtime. This adapter imports cuML directly without the global `cuml.accel` monkeypatcher. Consult [cuML HDBSCAN](https://docs.rapids.ai/api/cuml/legacy/api/generated/cuml.cluster.hdbscan.hdbscan/)
for native algorithm differences and [cuML distribution requirements](https://pypi.org/project/cuml-cu12/26.8.0/)
for platform dependencies.
