# Context and response smoke suite

`context_response_smoke` is a 30-case Set 18 suite targeting the real `chat`
assistant, including context selection, additional-context calls, and handoffs.
Its Langfuse dataset name is **context-response**. The existing dataset was
renamed in place; its case and experiment identities remain attached to the
same dataset ID.

Each case has exactly **one fact-oriented regex on final answer text**. The
patterns require the key names, counts, costs, stage windows, or rule clauses
needed for that question, so a topic-word response or question echo should
fail. They remain bounded smoke gates rather than full reference-answer
grading: context completeness is still inspected in the trace, and no quality
judge, rubric, tool-call assertion, or reference-answer check is configured.
Normal execution and contract-status scores still apply.

## Transfer and run

The portable source is [context_response_smoke.json](../../evals/datasets/context_response_smoke.json).
It uses schema-v3 string inputs and `metadata.deterministic_checks`. Stable case
IDs, coverage tags, and `quality_profile: null` survive transfer. The matching
[CSV](../../evals/datasets/context_response_smoke.csv) contains `input`,
`expected_output`, and JSON-encoded `metadata` columns for manual import.
Decode `expected_output` as JSON too: its explicit `""` cell represents an empty
reference string in the portable source. Langfuse stores that string as `null`;
the runner accepts this for cases with deterministic checks and no quality judge.
The checks still score
the response, and cases without scoring checks still require a reference.

The suite is registered in the snapshot catalog and normal workspace seeding.
Start/update the workspace through the normal command:

```bash
uv run --extra evals python -m evals up
```

Startup creates the dataset and its Custom Experiment button when missing.
Completed datasets remain UI-owned: restarting does not overwrite edits or restore
intentionally deleted cases. Prefer this native seeding path over CSV import;
manual import must preserve the complete metadata object, not just the question.

Select **context-response** in Langfuse and run a baseline experiment, then
edit prompt versions and compare runs using the existing Custom Experiment flow.
The CLI equivalent, after seeding, is:

```bash
uv run --extra evals python -m evals run --suite context_response_smoke
```

The portable source contains no hosted prompt versions. The original immutable
seed snapshot retains the historical `context-response-smoke` name; subsequent
hosted exports use `context-response`, freeze current prompt versions and
Langfuse's normalized case values, and advance the snapshot catalog. Do not use
the seed as a claimed historical prompt-replay baseline.

Use application `[chat] set_number = 18` with the matching corpus. The per-item
`set_number` tag documents intent; it does not override runtime configuration.
No database target is embedded. Runtime/database requirements remain those of the
normal assistant experiment worker. No 30-case model run or live import is implied
by the existence of these files.

To expand later, add or edit cases in Langfuse, retain their stable case IDs, and
export a new immutable snapshot. Keep the original snapshot untouched. The JSON
and CSV are bootstrap copies, not a two-way sync of later UI edits. Refine the
single fact regex when the corpus changes, or introduce richer grading
deliberately when a full reference answer is ready.

## Cases

The first six questions are the user's supplied examples, unchanged.

| # | Case | Coverage | Question |
| --- | --- | --- | --- |
| 1 | `riftbeast_roster` | roster | List all the riftbeast champs |
| 2 | `four_cost_adaptors` | roster | What are the 4 cost adaptors |
| 3 | `five_cost_count` | roster | How many 5 costs are in the game |
| 4 | `taric_ability` | champion | What does taric do |
| 5 | `potion_earliest_stages` | wisp stage | What is the earliest stage I can see mana potion wisp? Is it the same for health and blast? |
| 6 | `most_expensive_wisp` | wisp collection | What’s the most expensive wisp in the game |
| 7 | `econ_wisp_uniform_odds` | wisp probability | Assuming uniform distribution what are the odds of getting an Econ charm on stage2? Assume optimal conditions such as flipping heads, killing all enemy units, etc. assume a team size of 4 |
| 8 | `blossom_roster` | roster | Which champions have the Blossom trait? |
| 9 | `one_cost_roster` | roster | List the 1-cost champions in the current set. |
| 10 | `riftbeast_adaptor_overlap` | roster | Are any Riftbeast champions also Adaptors? Name them. |
| 11 | `elder_dragon_slots` | champion | How many team slots does Elder Dragon use, and how many Riftbeast counts does it contribute? |
| 12 | `adaptor_mechanic` | trait | How does Adaptor decide whether a champion uses its AD or AP form? |
| 13 | `taric_pairing` | trait | How do I pair an ally with Taric for Emerald Aspect? |
| 14 | `blossom_wisp_thresholds` | trait | What changes about Wisps at 3, 5, and 7 Blossom? |
| 15 | `stage2_goldxp_pool` | wisp stage | List every Gold/XP Wisp whose offer window includes Stage 2. Keep base and upgraded variants separate. |
| 16 | `stage3_goldxp_pool` | wisp stage | Which Gold/XP Wisps can be offered during Stage 3? |
| 17 | `stage2_item_pool` | wisp stage | Which item Wisps have an offer window that includes Stage 2? |
| 18 | `stage3_stage4_overlap` | wisp stage | Does an offer window of 3-5 through 4-1 include both Stage 3 and Stage 4? |
| 19 | `all_band_variants` | wisp eligibility | If a prismatic Wisp says All bands, does that mean I can buy it as a normal base Wisp in Stage 2? |
| 20 | `beggars_fallback` | wisp eligibility | Is Beggar’s Wisp a normal competing offer or a fallback? |
| 21 | `wisp_offer_cadence` | wisp rules | Does a Wisp appearing in the 2-1 to 2-7 window mean I get an offer every round? |
| 22 | `wisp_cooldown_units` | wisp rules | Are Wisp re-offer cooldowns measured in rounds or Wisp shops? |
| 23 | `wisp_purchase_phase` | wisp rules | Can I buy a Wisp during combat, or only during planning? |
| 24 | `late_combat_guarantee` | wisp rules | What is the Combat Wisp guarantee after Stage 5? |
| 25 | `coin_flip_cost` | wisp effect | How much does Coin Flip cost, and what decides whether it gives gold? |
| 26 | `bronze_spoon_variants` | wisp effect | Compare base and upgraded Bronze Spoon: what are their costs and earliest offer windows? |
| 27 | `artifactinate_conditions` | wisp eligibility | What conditions do I need to satisfy before Artifactinate can appear? |
| 28 | `hand_of_baron_condition` | wisp eligibility | Does Hand Of Baron require Riftbeast to be active? |
| 29 | `artifact_lookup` | item | What does Zhonya’s Paradox do, and is it an Artifact? |
| 30 | `forest_mage_shop` | wisp rules | What happens to the shop when Forest Mage creates a Wisp-filled shop? |

## Validation

```bash
uv run --extra evals pytest -q tests/test_context_response_suite.py evals/langfuse/tests/test_content.py
```

Tests validate all 30 cases, one regex each, the string-input contract, CSV and
snapshot parity, positive/empty-output scoring, dataset registration, and
idempotent native seeding that preserves UI edits. They do not invoke the model.
The older context-selector `exact_unit` gold mismatch still blocks global eval
validation; this new suite is validated independently.
