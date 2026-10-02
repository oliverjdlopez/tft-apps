# TR-2 dataset authoring report

Authored six ACTIVE cases, preserving stable IDs `TR-2-C01` through `TR-2-C06` and their reconciled order. Every input begins with the original player question, then states the constructed package anchors and relevant star/item constraints in ordinary language. The inputs distinguish constructed anchors from observed matches and ask for the available Set 18 standard-ranked final-board data.

## Input and evidence decisions

The authored inputs retain each comparison's named roster, swapped units, star levels, fixed carry/support item budgets, and relevant trait/emblem conditions. They keep the two-star and three-star support strata distinct (C02/C06), itemless swapped support conditions (C02–C06), matched named carry item identities (C01–C04/C06), and C05's exact Protector's Vow-only Kennen stratum. For C06, Sett holds one Fae Emblem and two tank items: the emblem occupies one item slot. C02–C05 require verification of Lux form before form-specific conclusions; generic Lux plus a board trait does not establish a variant. Trait breakpoints are assessed from recorded active traits/contributor counts, not by treating medal labels as numeric breakpoints.

Exact named cores can be checked by grouping a cohort that requires all N distinct unit identities by `board_size` and using a reportable row where `board_size == N`. When all N identities also have exact star constraints, that row establishes the complete stored roster and star vector for that slice. It does not prove occupied capacity or game legality. A global no-emblem/no-item restriction still needs all relevant item slots/identities accounted for; named predicates alone do not establish it. Broader contains-core cohorts are not exact roster comparisons.

Each item has a single `tool_called` trace check accepting supported cohort query/comparison routes as alternatives. The OR check does not lock a case to one implementation path or claim data success. Case requirements carry package-specific answer coverage and factual review expectations. Metadata sets `grading_scope` to `investigation_behavior_and_answer_coverage` and `numeric_ground_truth_verified` to `false`.

## Remaining preparation and grading gaps

All six source cases are provisional/incomplete and no outcomes were measured here. Before a scored run, an operator must verify a ready Set 18 standard-ranked scope, patch/subpatch and actual collection/population provenance, stable dataset revision, and sufficient sample support. No database or scope identifier is presumed by these import definitions.

Some requested global restrictions remain outside the available filters: absence of every emblem, exact item budgets unless identities/slots are fully accounted for, occupied board capacity, and unobserved gameplay history. Lux variant identity may not be preserved in historical facts. Trait contribution strata should be requested and interpreted as numeric contributing-unit counts; a trait medal is a categorical label. Even where exact stored roster and stars are established, final-board evidence cannot establish causal swap value, combat behavior, investment timing, or prior economic value.

The native quality judge receives bounded trace and presentation evidence rather than the full analytic tool outputs. It can assess answer coverage and visible investigation behavior, but cannot independently certify every reported number or nested cohort definition. Numerical gold scoring needs a compatible frozen aggregate reference or a full-trace audit.

## Validation performed

Called this run's `validate_datasets.py::validate_import` directly through `importlib` with `PYTHONDONTWRITEBYTECODE=1` and an isolated `/tmp` uv cache. Import normalization and semantic validation passed for all 6 items; each supported trace check passed positive and negative synthetic-witness validation. No Langfuse registration, snapshot write, live evaluation, database query, model call, or web research was performed. Only this report and `dataset.json` were authored.

## Final coordinator verification

After lane authoring, the coordinator reviewed and normalized this file alongside the full collection. The final lane contains 6 cases and 6 trace checks. The [coordinator review](../../docs/coordinator-review.md) records content corrections; the [validation report](../../validation/dataset-validation.json) is authoritative for the final import and assertion results. The original authoring observations above describe the lane submission, before any coordinator refinements.
