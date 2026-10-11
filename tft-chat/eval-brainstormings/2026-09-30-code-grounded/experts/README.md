# Expert dataset allocation

The 69 live cases were distributed using the subject lanes in the original
[manifest](../manifest.json). These definitions preserve the live source inputs,
answer requirements, statuses, lane metadata and original case IDs.

| Dataset | Original lanes | Cases | Default assistant | Definition |
| --- | --- | ---: | --- | --- |
| item-expert | IT-1 through IT-4 | 17 | item_expert | [JSON](item-expert/dataset.json) |
| unit-expert | UN4-1 through UN4-4 | 17 | unit_expert | [JSON](unit-expert/dataset.json) |
| comp-expert | CO4-1 through CO4-4 | 18 | comp_expert | [JSON](comp-expert/dataset.json) |
| trait-expert | TR-1 through TR-4 | 17 | chat | [JSON](trait-expert/dataset.json) |

There is no registered `trait_expert` assistant. The trait dataset uses `chat`
until a dedicated assistant exists; the per-run assistant override remains
available. No assistant specifications or model-facing tools were changed.
Each suite retains the original 40-turn budget. `meta-expert` stays empty.

All 154 checks remain. Twenty-eight checks offered several alternative tools,
including delta tools unavailable to the selected specialist. Those alternatives
were narrowed to the specialist's supported query/ranking tools. No check or
answer requirement was removed. The [allocation record](allocation.json) lists
every affected check and its original and supported alternatives.

New native items record `source_dataset`, `source_dataset_id`, `source_item_id`
and `source_suite_case_id`; existing `source_case_id` and proposal lineage remain
unchanged. All destination copies were verified before the combined live dataset
was deleted and its active catalog registration removed. Immutable historical
snapshots, original brainstorming files and a private workspace backup remain.

The [distribution receipt](../validation/expert-distribution.json) records native
dataset identities, per-lane counts, final snapshots and verification. Later
edits belong in Langfuse. These files are a reviewable distribution snapshot;
re-registering an existing suite does not replace its hosted cases.
