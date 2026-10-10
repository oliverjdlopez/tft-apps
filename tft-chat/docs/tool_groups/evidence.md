# Evidence displays

The `evidence` tool group contains `present_evidence`, owned by
`final_responder` and the directly responding `unit_expert`. It accepts
`DisplaySpec`: `evidence_ref`, `dataset_ref`, one of
`static_table`, `interactive_table`, or `distribution`, a title, optional short
description, and table choices (`columns`, `primary_metric`, `sort_by`,
`direction`, `group_by`). Table columns are unique, visible fields, bounded to
eight. Distribution choices leave table options empty. Values are never inputs.

## Data ownership

`domain.tools.evidence.models` defines the shared `EvidenceBundle` envelope,
typed `RankingDataset` and `DistributionDataset`, editorial `DisplaySpec`,
resolved `ResolvedPresentation`, and invocation-local `EvidenceStore`.
The shared envelope describes source, population, minimum reportable sample,
warnings, and named datasets; it does not force distributions into table rows.

The registry captures supported successful analytical outputs before
`model_jsonable` rounds numbers. The four ranking tools and `query_cohort`
provide approved public fields and up to 200 rows. Cohort tables retain their
requested grouping dimensions, distinct-board and lobby samples, placement and
outcome rates, and pick rate. They use the same table contract, without merging
or averaging groups. Unknown dimensions, missing grouping fields, and rows
without a reportable board sample cannot register evidence. Truncation
preserves the original offset and sets
`has_more`; sorting cannot imply completeness. Labels, units, grouping
eligibility, and row keys come from the backend. Numeric database scalars are
normalized without guessing percentage-point units. Rates remain fractions,
null remains unavailable, and unknown row fields are excluded. Trait tiers
are text labels (medals such as `Silver`, or `All` for a rollup), so they remain
eligible for categorical grouping rather than numeric formatting.

`compare_cohorts` supplies a `summary` table with one row each for its target
and baseline: cohort label, boards, average placement, top-four rate and win
rate. These are the tool's reported metrics at their original precision;
unavailable values stay null, and suppressed cohorts expose no numerical
summary values. The table can be displayed even when no histogram was returned.
An explicitly empty cohort retains its reported zero board sample, null
outcomes, and an unavailable histogram. It does not prevent the other cohort's
evidence from being displayed. Nonempty cohorts below the reporting floor
remain unreportable.
Cohorts may overlap, so these rows must not be summed or treated as independent
parts of a whole.

The same comparison also supplies separate target and baseline distributions. A
reportable histogram explicitly contains placements 1–8 and counts summing to
the cohort sample. Missing bins are not filled with zeroes. Suppressed or absent
histograms remain unavailable datasets. No mean-to-distribution inference,
cohort merging, or inferred joint distribution is performed.

Unsupported, erroneous, or malformed analytical results remain usable as
ordinary tool output but do not register evidence. Successful capture adds an
`evidence` descriptor with references, field definitions, and compatible views
alongside the existing model-facing result. Chat passes one store through the
SDK run and handoffs inside `AssistantRunContext.evidence`. Existing callers may
still supply a bare store; an absent store retains prose-only behavior. The maximum-turn fallback receives the same store but
remains tool-free to terminate reliably.

## Presentation and interaction

`present_evidence` resolves references only within the current invocation,
checks the selected fields and view compatibility, stores a resolved object,
and returns a compact acknowledgement to the model. Invalid choices return a
correctable tool error; only one successful initial display is allowed per
answer. Comparison summary tables must include `cohort` and `boards`; grouped
cohort tables must include all requested grouping dimensions and
`distinct_boards`. Missing identity or sample columns produce a correctable
error so rates cannot appear without the row definitions they describe.
Stream events serialize the store's resolved object directly, retaining
backend precision. `domain.tools.evidence.presentation_event` owns extraction of
the validated object and the existing unavailable-error payload; the stream
adapter calls it when consuming the presentation tool's output. The browser
formats values for reading without changing them.

The static table has no sorting or grouping controls. The interactive table
places controls behind an explicit Explore table disclosure, keeping the
initial results easy to scan. It supports local search, sorting, approved
categorical sections, an exact displayed-row limit, and reset to the assistant's
initial choice. The row limit defaults to all loaded rows and is bounded by that
loaded slice; it does not retrieve more evidence. Sections do not sum board
counts or average rates because cohorts may overlap. Both views show
loaded-result coverage and retain source context. Placement distributions keep
count and placement labels at readable text sizes on narrow screens, with a
table alternative, including explicit zeroes and separate unavailable states.

Browser display state never changes the evidence or enters chat history. Views
survive tab navigation for the page lifetime. Conversation reset clears them;
a reload starts fresh. Prior references cannot be reused in later server runs.
Non-chat execution surfaces without an EvidenceStore use prose or Markdown.
There is no new HTTP endpoint, persistent evidence service, A2UI dependency,
or cell-triggered investigation flow.

## Validation

```bash
uv run pytest -q tests/test_evidence.py tests/test_assistants.py tests/test_chat_service.py
uv run --extra evals python -m evals validate
cd app/frontend
npm ci
npm test
npm run build
```
