# TR-1 dataset authoring report

Authored three active cases, TR-1-C01 through TR-1-C03, preserving their original IDs and order. Each input begins with its original player question, then adds only the reconciled analytical scenario needed to make the evaluated work explicit. Each item carries the original research path and proposal lineage, an `answer_quality` threshold of 0.8, `grading_scope: investigation_behavior_and_answer_coverage`, and `numeric_ground_truth_verified: false`.

The checks use existing `tool_argument_resolved` and `tool_called` trace types. The name-resolution checks target Ahri, Soraka, or Cassiopeia in the top-level `unit` argument to `rank_unit_loadouts`; the investigation checks expect cohort queries and comparisons. C02 requires at least two `compare_cohorts` calls for its multiple contrasts. These checks only establish attempted calls, not successful queries, correct cohort definitions, cell coverage, or numerical accuracy. No nested path checks, full argument lists, or code syntax were placed in player input.

The requirements preserve each case's distinctions:

- C01 separates no active Invoker, active Invoker without Ahri holding its emblem, and the emblem held by Ahri. It requires a shared Ahri investment shell, a complement comparison to account for absent trait rows, and separate other-holder observations.
- C02 requires all four three/four-contributor by Kennen-present/absent groups, with within-stratum comparisons. It distinguishes contributor count from medal tier and does not infer roster choices from arithmetic.
- C03 explicitly makes current two/four/six-Defender performance in the selected scope answerable. The post-buff historical comparison remains conditional on separately supplied pre-period evidence and compatible provenance; arbitrary extra database metadata is not presented as a second executable data source.

Source inspection confirmed that `TraitCondition` defaults to active and supports contributing-unit bounds; `FilterGroup` predicates are conjunctive; `compare_cohorts` supports a shared shell and target complement; `query_cohort` groups by at most three available dimensions; and the evaluator's `execution_evidence` contains a bounded trace summary and presentation extract rather than complete analytical outputs. As a result, the native judge cannot independently verify every reported number against full tool output. Exact numeric gold scoring remains a gap pending a compatible frozen aggregate reference or a full-trace audit.

Remaining preparation gaps include a ready applicable Set 18 standard-ranked scope, data collection interval and population provenance, stable dataset revision, confirmed identity/rule compatibility, and sufficient samples for every requested cell. Public reporting floors may suppress groups. Current local context is not a verified 18.3B rules snapshot. Final-board associations cannot establish causality; C03 additionally needs separately supplied compatible pre-period evidence before it can support a before/after conclusion.

Validation performed with `PYTHONDONTWRITEBYTECODE=1` and `.venv/bin/python`: imported `scripts/validate_datasets.py` with `importlib` and called `validate_import` for this lane. Import normalization and semantic validation passed for all three items; all nine deterministic assertions passed synthetic positive/negative witness checks. No Langfuse dataset was registered, no application or research source was edited, and no database, web, or model call was made.

## Final coordinator verification

After lane authoring, the coordinator reviewed and normalized this file alongside the full collection. The final lane contains 3 cases and 9 trace checks. The [coordinator review](../../docs/coordinator-review.md) records content corrections; the [validation report](../../validation/dataset-validation.json) is authoritative for the final import and assertion results. The original authoring observations above describe the lane submission, before any coordinator refinements.
