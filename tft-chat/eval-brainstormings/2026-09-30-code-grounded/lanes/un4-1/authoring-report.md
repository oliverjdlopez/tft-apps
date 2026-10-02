# UN4-1 dataset authoring report

Authored four active dataset items: UN4-1-C01 through UN4-1-C04. Each input begins with its original player question and makes the mandatory investment, star, item, and board-context constraints visible to the evaluated assistant. Each item carries the source case path and proposal lineage, an `answer_quality` threshold of 0.8, and the required grading-scope metadata.

The deterministic checks use only existing trace types and the wrapper shape `{name, kind: "trace", check: {type, value, ...}}`. Name-resolution checks verify that the natural Veigar, Master Yi, or Ornn query flows to the relevant top-level unit argument; they do not assert an unverified stored identifier. Tool-call checks target cohort investigation, loadout ranking, and comparison, with a two-call minimum for the multi-cell Veigar frontline comparison. These checks establish attempted calls only: they do not certify call success, valid cohort definitions, or correct output. No nested resolved-name checks or brittle complete cohort arguments were added.

The case rubrics preserve their distinct analytical requirements:

- C01 asks for joint Veigar star/item investment cells, a named Veigar-board denominator, supported companion contexts, actual loadouts, and the limitation on inferring reroll payoff.
- C02 fixes the Yi2/Draven1 asymmetry and the holder-bound Flickerblade, radiant Quicksilver, and ordinary Edge of Night trio; it separates both-holder boards and support-conditioned comparisons.
- C03 distinguishes Veigar-held named ordinary trios, Dawncore, and overlapping active Flora Fatalis support. It requires a top-finish contribution denominator before claiming a group accounts for “most.”
- C04 defines focused and split Ornn/Alistar allocations numerically, keeps tank star strata and absent/richer groups visible, and limits claims about item-count matching.

The native quality judge receives bounded trace-summary and presentation evidence rather than full analytical tool outputs. Therefore each item sets `grading_scope` to `investigation_behavior_and_answer_coverage` and `numeric_ground_truth_verified` to `false`. Exact numerical verification remains a preparation gap requiring a compatible frozen aggregate reference or full-trace audit. No winner or outcome values were fabricated.

Remaining preflight gaps are external: verify a ready Set 18 standard-ranked scope, data collection interval and population provenance, stable dataset revision, candidate identities, and sample support. Local context does not certify 18.3B rules. Public cohort floors may suppress cells. The tools cannot match attempted rerolls or whole-board signatures, generically exclude all board special items, or match total investment and the rest of the board.

Validation performed with `PYTHONDONTWRITEBYTECODE=1` and the repository `.venv/bin/python`: `validate_bundle` and `validate_case_semantics` passed for all four authored items, including trace assertion validation and registered assistant references. No importer registration, production database query, model run, or live evaluation was performed.

## Final coordinator verification

After lane authoring, the coordinator reviewed and normalized this file alongside the full collection. The final lane contains 4 cases and 12 trace checks. The [coordinator review](../../docs/coordinator-review.md) records content corrections; the [validation report](../../validation/dataset-validation.json) is authoritative for the final import and assertion results. The original authoring observations above describe the lane submission, before any coordinator refinements.
