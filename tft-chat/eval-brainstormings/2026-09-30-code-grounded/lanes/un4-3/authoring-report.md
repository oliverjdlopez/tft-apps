# UN4-3 dataset authoring report

Authored six active cases with their original stable IDs and original questions first in each input. Each input then states the case's fixed comparison context in natural language. The dataset leaves database and scope selection unset for the required execution preflight.

Each case has two deterministic trace checks: at least one `compare_cohorts` call, and at least one candidate-build or cohort-composition inspection through `rank_unit_loadouts`, `query_cohort`, `get_cohort_unit_deltas`, or `rank_units`. The checks establish that the run attempted the relevant comparison and investigation; they do not certify query success, cohort validity, sample adequacy, or numerical correctness. Checks intentionally avoid exact stored-name arguments and full condition lists so valid analysis routes remain possible.

Input constraints and grading requirements preserve the lane-specific distinctions:

- C01 separates Ahri and Sivir partner investments, three-star and dual-partner variants, and reports AP/AD package and board-size/item-budget differences descriptively.
- C02 states that the without-Mama-Beak cohort is the eligible complement, not one forced replacement, and keeps star/item-count variants visible.
- C03 keeps naked versus itemized candidates distinct and requires observed shared named inventories before describing an allocation as shared.
- C04 calls defensive items a declared Fiddlesticks tank-investment proxy; same final level is not presented as a one-unit roster match.
- C05 represents Taric without Vanguard via the complement of active Vanguard in the shared Taric shell. It explicitly rejects `active: false` as a substitute for a missing trait row, preserves Amumu's active Juggernaut condition, and separates boards with both tanks.
- C06 defines Sett's main-tank role as a two-star defensive-item investment proxy and defines carry cores independently of Ravager Emblem.

All cases request observed samples and outcome tradeoffs and allow a supported direction, an unresolved comparison, or an explicitly sparse/suppressed result. They prohibit causal, role, inventory-equivalence, or absent-row claims the current evidence contract cannot support.

Preparation gaps remain external to these item definitions: confirm a ready Set 18 standard-ranked evaluation scope, population provenance and collection interval; verify reportable samples for the requested slices; and pin a stable dataset revision before scoring. Exact numerical gold is not verified. The native judge receives bounded trace and presentation evidence rather than full analytical outputs, so exact quoted numbers require a frozen aggregate reference or full-trace audit.

Validation performed: inspected the authoring and capability contracts, current tool registration/schema and implementations for `compare_cohorts`, `query_cohort`, and `rank_unit_loadouts`, the trace-check evaluator, and Langfuse dataset normalization/validation. With `PYTHONDONTWRITEBYTECODE=1` and `PYTHONPATH=app/backend/src:app/backend:.`, pure `validate_bundle` and `validate_case_semantics` both passed for all 6 normalized items. No import, registration, database query, web lookup, or live evaluation was performed.

## Final coordinator verification

After lane authoring, the coordinator reviewed and normalized this file alongside the full collection. The final lane contains 6 cases and 12 trace checks. The [coordinator review](../../docs/coordinator-review.md) records content corrections; the [validation report](../../validation/dataset-validation.json) is authoritative for the final import and assertion results. The original authoring observations above describe the lane submission, before any coordinator refinements.
