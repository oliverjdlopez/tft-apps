# Composition adapter contract v1

HDBSCAN is the sole production composition discovery implementation. This page documents its shared adapter envelope and saved-model compatibility.

The HDBSCAN `Adapter` exposes:

- `algorithm_id`: `hdbscan`.
- New standalone fits use algorithm version `"3"`.
- `Parameters`: immutable strict-extra Pydantic model in package `models.py`,
  inheriting `CompositionModel`; all parameters have validated defaults.
- `fit(boards: tuple[BoardObservation, ...], parameters: Parameters, seed: int)
  -> FitResult`.
- `classify(boards: tuple[BoardObservation, ...], model: FrozenModel)
  -> tuple[BoardAssignment, ...]` in input order, exactly one per input.

All envelopes live in `domain.compositions.models`. `FrozenModel` has
`schema_version="adapter.v1"`, algorithm id/version, `feature_revision="structure.v1"`,
`effective_parameters` (JSON dict including all default thresholds), `families`,
and algorithm-owned `state` (JSON dict). Store fitted references, feature
vocabularies, and parameters here. No pickle, filesystem, DB, HTTP, scheduler,
rendering, or cross-algorithm imports belong in discovery. The HDBSCAN package
validates its state through package-owned Pydantic models when classifying. Refuse incompatible
algorithm/version/feature revisions. Canonical JSON serialization is provided by
`adapter.serialize_model` / `deserialize_model`; JSON must contain finite values.

`FitResult` contains model, `discovery_assignments`, and `Diagnostics`.
Diagnostics use `schema_version="diagnostics.v1"`, `warnings: tuple[str,...]`,
and `panels: tuple[DiagnosticPanel,...]`. A panel has `panel_id`, `title`,
`kind` (table/distribution/text), `description`, and JSON `data`.
Use informative panel fields; the coordinator supplies specialized rendering.
Native discovery assignments can differ from frozen classification (especially
HDBSCAN noise). Explicitly describe the distinction in diagnostics.

Features exclude level and outcomes. `features.structural_features` encodes
roster multiplicity (weight 1), star state (.25), itemized holder count (2),
holder-bound item instances (.5), and observed trait tier state (.5).
Unknown tier is a distinct token, not tier zero.
`distance.board_distance` and `distance_matrix` use Euclidean (L2) distance on
these existing weighted coordinates: `sqrt(sum((a[k] - b[k]) ** 2))`.
There is no normalization, embedding, or additional square-root transformation of
feature weights. The holder coordinate remains 2, so a missing holder contributes
4 to the squared distance. Columns are the sorted union of observed feature keys;
absent coordinates are zero. The matrix is symmetric float64. Empty-to-empty
distance is zero; distances have no fixed upper bound.

Standalone HDBSCAN uses algorithm version 3 (cuML preferred, visible CPU fallback).
Saved version-1 models still classify using weighted multiset Jaccard,
selected from their frozen algorithm version. State shapes and feature revision
remain unchanged. Unsupported revisions remain errors.

New-run distance rejection defaults to 2.0. This is a provisional Euclidean
starting point, not a calibrated conversion of Jaccard settings. Distance thresholds
and ambiguity margins accept any finite nonnegative value.
Old results remain readable, and their frozen models remain classifiable. The
existing version guard rejects refitting queued or rerun version-1 requests with
the new fitter. Use a new experiment, or duplicate/edit with the current algorithm;
review copied distance thresholds because old numerical settings are not converted.

Shared helpers in `utils.py`: `family_from_boards(family_id, boards,
representative=None)` describes a family by its representative board (units with copy
counts and item state, plus active trait tiers), not marginal frequencies. The
pattern is descriptive: other members never contribute and membership never reads it. `reference_assignments(boards, families, references,
rejection_distance, ambiguity_margin)` uses nearest frozen reference per family,
rejects distances above threshold, and marks ties within the margin ambiguous.
Algorithms may implement their own matching policy. Serialize every effective
matching threshold. Repeated champion/item identities remain distinct occurrences.
`validate_references` validates experiment-local cross references; full-population
classification must not replace discovery representatives with new definitions.

Immutable fixtures: `domain.compositions.fixtures.fixture_boards()` (24 boards,
two itemized anchors, shared frontline, duplicate units/items, unknown traits),
`fixture_outcomes()` held separately. Contract runner: `tests/compositions/test_contract.py:exercise_adapter`.

HDBSCAN tests exercise harmless substitutions, changed itemized anchors, shared
frontlines, incomplete/empty input, ambiguity, seed determinism, serialization
round trips, and incompatible state rejection. Helpers belong in the package's
single `utils.py`. Include Google-style docstrings.

The service freezes snapshots and effective parameters before enqueueing. Reruns
create new results on identical inputs/settings. Full-population classification
uses frozen definitions and separately recorded statistics. Outcomes are joined
only after classification. Experimental results never promote a taxonomy.


HDBSCAN classification can execute frozen reference distances
through `acceleration.grouped_reference_distances`. The default hardware policy is
automatic with optional CuPy, bounded query batches, and a compiled CPU fallback.
The envelope remains adapter v1; frozen algorithm versions select the metric. CPU/CUDA selection is
an execution concern, not a learned parameter. Benchmark overrides use the scoped
`classification_backend` context manager and force errors for unavailable CUDA.
See the [benchmark guide](benchmarks.md).
