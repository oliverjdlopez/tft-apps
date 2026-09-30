# Composition benchmarks

The standalone `scripts/composition_benchmarks/` tool has three parts: a TOML run
definition, a sequential runner, and a portable HTML report. It does not start
Desktop, access the database, enqueue experiments, or change production algorithms.

## Define runs

Start with `scripts/composition_benchmarks/example.toml`. Each sweep crosses the
sample sizes, seeds, and every value in its parameter grid. Adapter defaults and
versions are expanded and recorded before execution; invalid settings fail early.
`--list` prints the expanded plan without running it:

```sh
uv run --extra compositions python -m scripts.composition_benchmarks \
  scripts/composition_benchmarks/example.toml --list
```

A small definition looks like this:

```toml
name = "HDBSCAN size and density sweep"
sample_sizes = [100, 500, 1000, 2000]
seeds = [42]
repeats = 3
warmups = 1

[[sweeps]]
kind = "distance"
backends = ["cpu", "cuda"]

[[sweeps]]
algorithm = "hdbscan"
[sweeps.parameters]
min_cluster_size = [5, 15]
min_samples = [3, 5]
```

`backends = ["cpu", "cuda"]` is supported for HDBSCAN adapter
sweeps. These backend axes select frozen classification. Standalone HDBSCAN fitting
independently prefers cuML when available. Measurements record `fit_backend`
separately in the report and CSV.

HDBSCAN is the only supported adapter sweep. Parameter arrays form a Cartesian product.
The benchmark runner retains a 2,000-board maximum per sample and a
2,000-measurement guardrail per plan. These benchmark-only limits are separate
from the desktop workbench, which allows population-sized samples and asks for
confirmation above 20,000 sampled boards.

By default, inputs are deterministic synthetic eight-unit boards with varied items
and shared anchors. These measure throughput, **not real-match clustering quality**.
To use real inputs, set `input_path` to a JSON array of `BoardObservation` objects,
or an existing snapshot JSON object containing a `boards` array. Paths resolve
relative to the TOML file. Outcomes are ignored. The runner never duplicates real
boards to satisfy a requested size: insufficient inputs fail. Samples are nested
for a seed and identical across backends. Saved input content is hashed.

## Do the runs

```sh
uv run --extra compositions python -m scripts.composition_benchmarks \
  scripts/composition_benchmarks/smoke.toml --output profiles/composition-benchmarks/smoke
```

For actual CUDA measurements, an NVIDIA GPU and compatible CUDA 12 toolkit must be
available. Add the optional CuPy package for this invocation:

```sh
uv run --extra compositions --extra compositions-gpu \
  python -m scripts.composition_benchmarks \
  scripts/composition_benchmarks/example.toml --output profiles/composition-benchmarks/scaling
```

See [CuPy installation](https://docs.cupy.dev/en/stable/install.html) for driver and
toolkit setup. A missing GPU/runtime produces explicit **skipped** rows; it never
silently runs a GPU-labeled case on CPU. Existing reports are protected from CLI
overwrite: use a new output directory. Ctrl+C retains completed measurements.

Runs execute sequentially, avoiding interference between measured cases. Close
other heavy jobs when measuring. The report records hardware, dependency versions,
Git revision/dirty state, effective settings, and repeated measurements. Warmup and
CUDA initialization costs are recorded separately, excluded from timed medians.
With `warmups = 0`, first-call compilation/setup can enter the measurements.

## Display and interpret

Open the resulting `index.html` in a browser. It contains workload and timing filters,
a scaling chart, sortable comparisons with median/min/max durations, effective
parameters, failure details, and a CSV download. `results.json` contains the complete
machine-readable measurements. Both files update after every repetition; refresh
an open report to see newly saved results. No server or remote chart library is used.

- **Distance workload:** equivalent Euclidean matrices on compiled
  SciPy CPU code and a CuPy CUDA kernel. Reports feature encoding separately from
  computation. CUDA computation includes input/output transfers and waits for the
  result to reach the host. It avoids an N-by-N-by-feature temporary tensor. Float64
  arithmetic matches the CPU metric within `1e-12`; deterministic sampled pairs are
  checked against the scalar implementation outside timing. The CPU uses symmetry;
  the simple GPU kernel currently calculates the full square matrix.
- **Adapter workload:** fit (standalone HDBSCAN prefers cuML), frozen-model serialization,
  and classification stages, plus family count, coverage, and ambiguity. It excludes
  DB capture, outcome aggregation, persistence, and rendering. These are not full
  desktop experiment timings. HDBSCAN can use CPU or CUDA classification.
  Explicit CUDA never silently falls back.

Distance speedup does not establish end-to-end algorithm speedup. Use adapter
sweeps to compare total fit, serialization, and classification times.
At small sample sizes, transfer and launch overhead can outweigh GPU parallelism.

## Validation

```sh
uv run --extra compositions pytest -q tests/compositions/test_benchmarks.py
CHATTFT_BENCHMARK_CUDA_TEST=1 uv run --extra compositions \
  --extra compositions-gpu pytest -q tests/compositions/test_benchmarks.py
```

The opt-in CUDA test compares the complete CPU/GPU fixture matrices, including
empty boards, duplicate units/items, and unknown traits. Other tests cover Cartesian
expansion, sample identity, invalid settings, missing GPU, failures, warmups, saved
artifacts, and safe report embedding.

## Initial local measurement

The measurements below predate Euclidean distance and describe the earlier
weighted-Jaccard implementation. They are not current Euclidean performance results.

The September 22, 2026 validation used an existing anonymous 2,000-board snapshot,
100/500/1,000/2,000-board subsets, HDBSCAN `min_cluster_size` values 5 and 15,
and two repetitions (no warmups). All 32 measurements completed on an i5-14600K
and RTX 4070. At 2,000 boards, median distance encoding plus computation was
3.17 seconds on CPU and 0.69 seconds on CUDA, including transfers. GPU sampled
scalar-distance checks had zero observed error. This is an initial local comparison,
not an isolated hardware performance guarantee; consult the per-run ranges.
HDBSCAN fit took roughly 3.4 seconds while classification took roughly 99 seconds,
identifying classification as the target of the subsequent GPU integration. These
initial measurements predate the accelerated classifiers.

In the benchmark worktree, the saved report is `profiles/composition-benchmarks/saved-sample/index.html`
and its replay definition is `profiles/composition-benchmarks/inputs/saved-sample.toml`. These local
artifacts and anonymous inputs are Git-ignored. Use a fresh output directory to rerun:

```sh
uv run --extra compositions --extra compositions-gpu \
  python -m scripts.composition_benchmarks \
  profiles/composition-benchmarks/inputs/saved-sample.toml --output profiles/composition-benchmarks/rerun
```
