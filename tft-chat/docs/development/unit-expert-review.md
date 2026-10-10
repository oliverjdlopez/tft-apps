# Unit expert annotated review

The source is the tracked
[annotated October 4 report](../../artifacts/2026-10-04-unit-expert-prompts-outputs-and-tool-arguments.md.pdf),
run `adea170a7b476b85`. Page numbers below refer to the PDF, including its
handwritten front matter. The report records 17 answers, 12 grading passes,
and 5 failures. Those historical results have not been rerun or regraded.

## Changes grounded in the review

| Review location | Resulting behavior |
| --- | --- |
| Page 1; 3–5; 81–82 | Lead with a useful conclusion for an intermediate player. Put comparison figures and board samples in a compact display; omit repeated statistics, prose-filled interpretation columns, and a compulsory closing paragraph. |
| Pages 11–12 and 69–70 | Test the requested exact build first. If it cannot be compared, give a concise limitation and stop that branch. A different item recipe or broader star pool does not answer the original question. |
| Pages 30–31 | Inspect complete loadouts and marker coverage before claiming an AP/AD comparison. An item-defined subset must remain a subset in the conclusion. |
| Pages 54–55 | Preserve the praised pattern: a direct, calibrated inference, a small relevant comparison, and only explanation that changes its reading. |
| Page 109 | Unit presence does not establish a main tank. Use observed investment as an explicit proxy and preserve the distinction from combat role. |
| Page 125 | Explain the material comparison in ordinary language; do not require methodological labels in the answer. |

Stable behavior lives in `unit_expert/system.md`. The prompt and manifest now
agree that this specialist answers directly with ranking, cohort, and evidence
tools. The fixed three-or-four-unit report and unavailable analyst handoff were
removed. Shared chat, analyst, final-responder, and selected skill guidance
adopts the corresponding response and investigation rules.

Evidence support is real tool behavior: grouped `query_cohort` results register
a bounded table, and `compare_cohorts` registers a summary table alongside
target/baseline distributions. `unit_expert` can call `present_evidence`
directly. Values remain backend-owned, suppressed values remain unavailable,
and the existing browser table components consume the same contract. See
[evidence displays](../tool_groups/evidence.md).

## Review cases and validation

`evals/datasets/unit_expert_review.json` is a portable schema-v3 manifest,
registered as `chattft/unit-expert-review`, containing six original player
questions. It retains the source case
lineage, immutable input snapshot, PDF pages, and qualitative review criteria.
It supplies no invented numerical gold and does not force tool counts or
unconditional supporting-board queries. A concise unresolved answer can pass
when the assistant actually attempted the relevant retrieval and the evidence
cannot support the requested comparison. Unsupported winners still fail.

Validate the contracts from `tft-chat/`:

```bash
uv run pytest -q tests/test_unit_expert_review.py tests/test_assistants.py tests/test_evidence.py tests/test_openai_tools.py tests/test_skill_provider.py
```

These are deterministic implementation checks. They do not demonstrate that
model answers improved. To register the review cases on a new local deployment,
use the existing command:

```bash
uv run --extra evals python -m evals create-dataset \
  --name unit_expert_review \
  --dataset-name chattft/unit-expert-review \
  --assistant unit_expert \
  --items evals/datasets/unit_expert_review.json \
  --max-turns 40
```

Registration does not update an existing hosted assistant prompt. Create and
select a Langfuse prompt version containing the revised repository
`unit_expert/system.md` before comparing results. Existing dataset definitions,
baseline labels, and immutable historical snapshots remain unchanged. Some
original checks, particularly the double-Blue-Buff case, require supporting
queries even when the exact build is unreportable; the review manifest tests
the annotated stopping policy without silently relaxing the historical run.

The current evaluation worker runs without an `EvidenceStore`, so it uses the
compact Markdown fallback. Chat uses native evidence cards. Adding a store to
the eval worker also requires carrying presentations into judging and exported
artifacts; supplying a store alone would hide supporting numbers from those
surfaces.

Native quality grading receives the final answer and a trace summary, but not
numeric tool returns. Its current presentation extraction also expects a `name`
field while normalized trace events use `tool`. A passing quality score alone
therefore does not establish numeric correctness or validate native evidence
cards. Inspect answers and captured tool arguments alongside grader comments.

The six-case review uses revised requirements and a selected subset of the
historical questions. Its pass fraction is not directly comparable to the
October 4 run's 12/17. One attempt per case also provides no stability estimate.

## Authorized live evaluation: October 8, 2026

The user authorized one paid run. Job `44f5a07d787f4e50bbc35a2a10cc4127`
finished execution and native grading, with six successful executions and
three quality passes at the 0.8 threshold. Its terminal job state is `failed`
because three answers failed quality grading, with no execution errors,
grading errors, or detected evaluator drift.

The run used one attempt per case, concurrency two, `gpt-6-luna` for the
assistant, and the existing `gpt-5` quality evaluator. Hosted unit-expert
prompt version 2 exactly matched the revised repository system prompt; version
1 retained its baseline label. The evaluation database was
`chat_tft_dev_set18_beta3`, whose active scope was Set 18, patch `18.beta`,
queue 1100. The run began at `2026-10-09T02:52:49Z` (October 8 locally).

| Case | Native quality score | Outcome |
| --- | ---: | --- |
| Yi versus Draven (`UN4-1-C02`) | 0.92 | Pass |
| AP versus AD Nidalee (`UN4-2-C01`) | 0.72 | Fail |
| Rapidfire Nidalee (`UN4-2-C03`) | 0.90 | Pass |
| Double Blue Buff Ahri (`UN4-2-C04`) | 0.72 | Fail |
| Morgana carry partners (`UN4-3-C01`) | 0.92 | Pass |
| Fiddlesticks and Defender (`UN4-3-C04`) | 0.62 | Fail |

The answer and argument review found shorter, clearer responses and a clean
stop for the unavailable Yi/Draven comparison. Remaining gaps include AP/AD
classification coverage, treating individually suppressed complete loadouts
as evidence about the entire double-Blue-Buff family, and using arbitrary
completed-item counts to represent defensive investment. Despite its passing
grade, Rapidfire Nidalee still substitutes all emblem holders for the
unavailable AP-specific comparison and overstates what a level-8-or-higher
filter establishes about surrounding-board strength. Numeric tool returns
were not independently verified by this review.

The native run is `2a6938dd5379c60f` in `chattft/unit-expert-review`. Frozen
snapshot `472c551b20e4795e03b9a9f11936da39b5e8358f608de4b30c3865860646aebe`
preserves its inputs, selected prompt, and grading definitions. Complete
answers and ordered tool arguments were automatically exported after grading
to ignored
`evals/langfuse/.runtime/artifacts/44f5a07d787f4e50bbc35a2a10cc4127.md`.

Full catalog validation currently fails on the unrelated retired
`_ContextCandidate` import in `evals/context_selection/utils.py`. Focused
review-manifest validation does not use that selector adapter.
