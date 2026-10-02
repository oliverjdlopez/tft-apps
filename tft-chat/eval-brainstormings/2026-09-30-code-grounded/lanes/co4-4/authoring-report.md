# CO4-4 dataset authoring report

Authored four active evidence-relative cases in reconciled order: `CO4-4-C01` through `CO4-4-C04`. Inputs retain each reconciled player question verbatim at the beginning, followed by a concise investigation scenario. C03 and C04 use the coordinator's scoped-data adaptations; no website-panel values or historical answer ordering are used as expected output.

Each case has an `answer_quality` profile with threshold 0.8, source path and proposal lineage, and the required `grading_scope: investigation_behavior_and_answer_coverage` and `numeric_ground_truth_verified: false`. Requirements ask for sample denominators and returned outcomes while allowing either result direction or a genuinely unresolved comparison. Trace checks require the supported `query_cohort` and `compare_cohorts` operations, without brittle nested condition lists or assumptions about call ordering.

The inputs explicitly carry the analytical scenario facts needed by the assistant: C01's itemized Aphelios, Eclipse and Solar-upgrade comparison; C02's level-eight Azir/Rapidfire Emblem reconstruction shell and the unknown sixth shared unit; C03's shared eight and three named candidate additions; and C04's shared eight, level ten, Elder Dragon's two occupied slots, and Lux variant ambiguity. Requirements retain the limits on exact roster closure, capacity, item-category/global-investment filters, causal conclusions, sample suppression, and the distinction between observed end-board performance and success probability after choosing a composition. No resolved tool identifiers, database, or scope ID has been invented.

## Remaining preparation gaps

- The active Set 18 standard-ranked scope, data readiness, patch compatibility, and collection interval need operator preflight before a scored run.
- Numerical gold is not verified. The native quality judge sees bounded trace and presentation evidence, not full analytical outputs; exact numerical grounding still needs an immutable compatible aggregate reference or full-trace audit.
- Exact rosters, occupied capacity, broad item restrictions, global investment totals, and exhaustive candidate coverage cannot be guaranteed by these public cohort filters. The unknown sixth C02 unit and the C03/C04 candidate outcomes must come from execution evidence.

## Validation

Validated with the run's pure importer validator via `validate_import(path, suite_name)` using `PYTHONDONTWRITEBYTECODE=1`; this normalizes items and exercises deterministic checks against synthetic positive and negative traces while intercepting snapshot export. No database, live model, Langfuse registration, or external data was used.

## Final coordinator verification

After lane authoring, the coordinator reviewed and normalized this file alongside the full collection. The final lane contains 4 cases and 6 trace checks. The [coordinator review](../../docs/coordinator-review.md) records content corrections; the [validation report](../../validation/dataset-validation.json) is authoritative for the final import and assertion results. The original authoring observations above describe the lane submission, before any coordinator refinements.
