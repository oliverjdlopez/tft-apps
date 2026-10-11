# UN4-4 dataset authoring report

Authored three active cases, preserving the stable IDs and original player questions at the start of each input. Each scenario makes the requested carry, tank, item-count, star and final-level constraints visible to the assistant. The inputs distinguish final level from stored unit-record count and occupied capacity, and require descriptive inspection of other item investment where available.

The deterministic checks use the supported trace wrapper `{name, kind: "trace", check: {type, value, ...}}`. They cover name resolution, package discovery, outcome comparison, and grouped board-shape diagnostics. Discovery accepts `rank_unit_loadouts`, `query_cohort` or `rank_units`; outcome comparisons accept `compare_cohorts` or `query_cohort`. Checks establish tool invocation only and do not assert successful execution, valid cohort construction or correct numerical results. No complete argument payloads, nested resolved-name checks or unsupported evaluator types were added.

The case rubrics keep their distinct analytical contracts:

- C01 requires Soraka2/Zyra2 and an exclusive Lillia2 or Malphite2 with a disclosed, reproducible defensive-item classification. It asks for actual packages, supported common-core and trait comparisons, and descriptive board-level investment checks.
- C02 compares exclusive Ashe2/Draven2 three-item builds on itemized Maokai2 boards. It separates dual carries, one-star carries and level ten, then checks support cores, Elder Dragon, unit-record count and other investment without claiming health, reward or capacity matching.
- C03 compares exclusive itemized Elder Dragon2/Ezreal2 packages on the Draven2/Maokai2 core, using a common observed item-count stratum for the core where supported. It requires top-four and win outcomes, upgrade and emblem diagnostics, and an explicit account of Elder Dragon's two-space occupancy versus stored unit count.

All cases use `grading_scope: "investigation_behavior_and_answer_coverage"` and `numeric_ground_truth_verified: false`. The native quality judge sees a bounded trace summary and presentation extract rather than full analytical tool outputs, so it cannot independently verify every quoted number or nested cohort argument. Factual fidelity remains the intended review contract; exact numerical verification needs a frozen compatible aggregate reference or a separate full-trace audit.

Remaining preparation gaps are external: a ready Set 18 standard-ranked scope, stable dataset revision, verified collection interval and population provenance, resolved candidate identities, and adequate samples. The available cohort tools cannot enforce a complete roster, whole-board item-family exclusions, exact occupied-capacity equality, Maokai accumulated health or Draven reward state. The grouped board-size and item-investment fields are descriptive and do not eliminate those confounders. No outcome winner or numerical answer was invented.

Validation performed with `PYTHONDONTWRITEBYTECODE=1` and `.venv/bin/python`: importer normalization, bundle validation, case semantic validation and positive/negative synthetic witnesses for each authored trace assertion. Snapshot export was intercepted in memory. No database query, web research, registration, model run or live evaluation was performed.

## Final coordinator verification

After lane authoring, the coordinator reviewed and normalized this file alongside the full collection. The final lane contains 3 cases and 12 trace checks. The [coordinator review](../../docs/coordinator-review.md) records content corrections; the [validation report](../../validation/dataset-validation.json) is authoritative for the final import and assertion results. The original authoring observations above describe the lane submission, before any coordinator refinements.
