# Context Provider

Repository context supplies factual references, separately from assistant policy
and procedural skills. `domain.providers.context` owns context discovery and
provider operations, `domain.providers.models` defines the shared data and
protocol contracts, and `domain.providers.utils` contains parsing, candidate,
selection, and serialization helpers. Sources live under
`app/backend/src/resources/context`.

## Completeness-first retrieval

The selector sees a catalogue of **every source eligible for the configured
set**. There is no lexical shortlist or default candidate, character, or selected
source cap. Long documents cannot evict other sources before selection.

The catalogue includes source names, paths, descriptions, headings, and all entry
names. References without named entries retain their text as routing evidence;
standalone JSON without descriptive Markdown metadata retains its values too.
The selector chooses collections using semantic relevance, including informal
names and synonyms. For counts, odds, comparisons, and exhaustive lists, it is
instructed to select both the requested category and every collection needed for
the comparison population, plus eligibility rules.

After selection, the runtime injects **every selected collection in full**.
Ordinary JSON sources are complete top-level objects; ordinary Markdown sources
are complete bodies after frontmatter removal. Wisp categories use the complete
stage chunks described below. There is no per-entry ranking inside a selected
collection and no silent truncation. This deliberately spends more tokens
than individual-entry retrieval; completeness takes precedence over token cost.

`RepositoryContextProvider.select` and `aselect` use identical catalogue and
hydration rules. `select_context_snippets` is the offline lexical path: it ranks
whole collections using names, paths, descriptions, and contents, returning all
positive matches. If model selection fails, runtime selection uses that same
fallback. The fallback is less semantically capable and does not guarantee that
all relevant sources were selected. Model/API context-window limits still apply;
the provider does not conceal an oversized request by dropping facts.

Callers may explicitly provide `max_snippets` or `max_chars`. If selected sources
cannot fit, the provider raises `ValueError` with required collection/character
counts rather than returning a misleading partial pool. Character accounting
includes the rendered source labels and guidance. Nonpositive limits explicitly
disable selection. Default limits are `None`.

## Source formats and identity

Markdown uses flat frontmatter, for example:

```yaml
---
name: unit-reference
description: Champion roster, costs, traits, and roles. Use for roster and shop-pool questions.
kind: unit
sets: 18
---
```

`name` is a unique identity; `description` supplies semantic routing guidance;
`kind` defaults to `reference`. Optional `sets` limits eligibility.

JSON files must contain a top-level object. Their relative path is their source
identity. Set scope comes from the nearest `set<number>` directory, including
decimal sets. Empty objects contribute no selectable collection. Invalid JSON,
duplicate keys, and non-object roots are ignored with a warning.

A JSON source with a same-directory, same-stem Markdown companion inherits that
Markdown source's description and kind for routing. Both remain selectable:
matching filenames do not prove equivalent facts. The provider does not discard
one companion or merge away divergent content. Selected context can therefore
contain overlapping facts; token optimization is deferred.

The current corpus is under `context/set18/`. See
[Set 18 coverage and source notes](set18-context.md) for source limitations.
Completeness of a retrieved file does not establish completeness of the game
reference itself.

## Wisp stage collections

The seven Wisp category sources (`wisps-champion`, `wisps-combat`,
`wisps-goldxp`, `wisps-item`, `wisps-misc`, `wisps-risky`, and `wisps-shop`)
are partitioned into stage collections during candidate construction, for both
Markdown and JSON. The original files remain authoritative and are not rewritten.
General `wisps.md`/`wisps.json` rules remain whole and independently selectable.

Each `Stage N` chunk contains **every variant whose explicit offer window
intersects that stage**, retaining exact round windows, conditions, exclusions,
cooldowns, mode restrictions, fallback wording, and effects. A window such as
`3-5–4-1` contributes the unchanged entry to both Stage 3 and Stage 4; `6-1–10-1`
contributes to Stages 6 through 10. A stage chunk is not a claim that all its
entries are available throughout that stage or simultaneously eligible.

Entries marked `All bands (no round-band tag)` form an `All stages` chunk.
Stage-specific questions must also select these unrestricted chunks and general
rules, then apply variant requirements. In particular, a prismatic entry without
a round-band tag does not become an ordinary base offer.

Stage chunks carry stable keys (`stage-2`, `stage-3`, …, `stage-all`) and visible
headings in the catalogue, rendered context, and additional-context tool result.
The selector is instructed to choose only requested stages, all relevant
categories for a full probability denominator, applicable all-stage chunks, and
general rules. No-stage questions can select all stage chunks; count unions by
variant identity to avoid double-counting entries appearing in multiple stages.
Offline lexical fallback remains conservative and can return additional stages.

Markdown chunks retain the common introduction and complete entry blocks,
including continuation lines. If any entry has missing or unrecognized window
syntax, that source stays whole rather than silently losing the unknown entry.
Empty stage groups are not offered. Other context sources retain their existing
whole-collection behavior.

## Additional context and assistant integration

`request_additional_context` uses the same asynchronous provider. Its request
should describe all factual needs, including the comparison population for odds.
It returns full selected collection contents, source identities and stage headings, `collection_count`,
and `complete_selected_collections: true`. That flag means no selected collection
(including a stage chunk) was truncated; it does not assert that every relevant source or game fact was found.

The top-level assistant and its contextualized handoffs share initial selected
references. Tool calls can fetch additional collections. References are rendered
as facts, never instructions; private analyst schema and procedural skills remain
separate. Requests for another set cannot retrieve Set 18 sources.

## Verification

```bash
uv run pytest -q tests/test_context_service.py tests/test_chat_service.py tests/test_assistants.py tests/test_skill_provider.py
```

Regression tests cover full-catalogue visibility for informal Wisp, artifact,
and shop-pool questions; complete Wisp collections beyond the former 12-unit and
6,000-character caps; large-source crowding; divergent companion preservation;
set filtering; explicit budget errors; and synchronous/asynchronous parity.
Stage regressions verify corpus-wide Stage 2 membership, cross-stage windows,
all-band entries, complete reconstruction across chunks, retained conditions,
Markdown introductions, and lossless fallback for unknown eligibility syntax.

The context evaluation adapter uses the same catalogue and complete sources.
It no longer requires a 75% payload reduction or an empty catalogue for unrelated
queries: the selected result, rather than available source inventory, must be
empty for an unrelated question. Frozen historical evaluations expecting retired
part titles must be migrated separately rather than rewritten in place.
