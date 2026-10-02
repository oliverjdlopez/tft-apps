# CO4-2 dataset authoring report

Authored six ACTIVE cases in the reconciled order, preserving IDs `CO4-2-C01` through `CO4-2-C06`. Each input begins with its original player question, followed by the reconciled scenario and concise natural-language population constraints. Expected requirements ask for evidence-relative findings, counts and denominators, overlap handling, and honest limits without supplying invented winners or numerical gold answers.

## Check decisions

Each case has one `tool_called` trace check whose `values` list accepts the appropriate registered cohort/query/comparison or delta tools as alternatives. These checks require an actual investigation step while allowing the assistant to choose among supported routes. They do not assert nested filter payloads, exact ordered lists, result correctness, or successful database access; case-specific population and answer coverage remain in `expected_output.requirements`. No resolved-name check was added because the case cohorts can be specified in player language and no single top-level resolved argument is necessary across valid routes.

The inputs state the observable operational populations directly: level-nine soup candidates (C01); Veigar three-star with recorded active Elderwood (C02); all six named AD pairs and itemization proxies (C03); disjoint Zyra/Soraka/both families with both frontline anchors absent for the main read (C04); Teemo top-four boards with itemized/low-item proxies and a separate all-placement sensitivity (C05); and three-star Murkwolf/Warwick, Riftbeast contribution strata, and their hybrid (C06). Each also requires verified Set 18 standard-ranked scope provenance and forbids treating final-board associations as timing or causal evidence.

## Preparation and grading gaps

The source cases remain provisional/incomplete, and no compatible populated scope or samples were measured. A scored run still needs an operator to verify the Set 18 standard-ranked ready scope, patch and population provenance, stable dataset revision, collection interval, and applicable sample support. Configured context alone does not certify an 18.3B or hotfix cutoff.

Public tools cannot produce exhaustive board-level composition partitions or arbitrary full-roster/flex-slot assignments. C01 is bounded candidate discovery rather than global five-cost enumeration. C02 and C04 expose contained packages, not exact rosters or player intent. C03 has no native six-pair union denominator and itemization is only a role proxy. C05 may not recover complete top-four groups when placement cells are suppressed. C06 cannot expose reroll process, Alpha Mark, sacrifice events, or combat behavior. These limits are stated in case requirements; missing or suppressed support must remain unknown rather than being called zero.

All items set `grading_scope` to `investigation_behavior_and_answer_coverage` and `numeric_ground_truth_verified` to `false`. The native quality judge receives bounded trace/presentation evidence rather than full analytic tool outputs, so it cannot independently certify every quoted number or nested cohort definition. Numerical gold grading still requires a frozen compatible aggregate reference or full-trace audit.

## Validation performed

Called this run's `validate_datasets.py::validate_import` directly through `importlib` with `PYTHONDONTWRITEBYTECODE=1` and an isolated `/tmp` uv cache. Import normalization and semantic validation passed for all 6 items; all 6 supported trace checks passed positive and negative synthetic-witness validation. No registration, snapshot export, live evaluation, model call, database query, or web research was performed. Only this report and the lane `dataset.json` were authored.

## Final coordinator verification

After lane authoring, the coordinator reviewed and normalized this file alongside the full collection. The final lane contains 6 cases and 6 trace checks. The [coordinator review](../../docs/coordinator-review.md) records content corrections; the [validation report](../../validation/dataset-validation.json) is authoritative for the final import and assertion results. The original authoring observations above describe the lane submission, before any coordinator refinements.
