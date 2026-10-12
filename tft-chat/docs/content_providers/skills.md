# Skill Provider

The repository skill provider discovers portable Agent Skills, selects only the
focused workflows that materially help answer a request, and injects each
selected workflow in full. Investigation guidance is for questions that need
query planning; a straightforward lookup should not acquire extra workflow
steps. Follow-up queries are conditional on resolving a material uncertainty or
changing the conclusion.
`domain.providers.skills` owns provider operations and deterministic selection,
`domain.providers.models` defines the shared data and protocol contracts, and
`domain.providers.utils` contains loading, discovery, selector, and rendering
helpers. Skill packages live under
`app/backend/src/resources/skills/<name>/SKILL.md`.

Skills contain task procedures. Factual game reference material belongs in the
context corpus, while durable assistant behavior belongs in assistant
`system.md` files.

## Skill frontmatter

Selection uses only the protocol fields `name` and `description`:

```yaml
---
name: tft-grounded-recommendation
description: Turn TFT statistical evidence into a practical recommendation with an explicit population, metrics, baseline, caveat, action, and confidence. Use when the user asks what to play, build, prioritize, avoid, or change. Do not use for purely descriptive lookups.
---
```

The directory and `name` must match. Names use lowercase letters, numbers, and
hyphens and are limited to 64 characters. Descriptions are required and limited
to 1,024 characters.

Put all discovery information in `description`:

- what the workflow does;
- the concrete tasks and vocabulary it covers;
- when it should be activated; and
- important boundaries or cases where it should not be used.

Do not add custom top-level routing fields such as `keywords`, `covers`,
`scope`, or `use_when`. Optional standard Agent Skills fields may remain for
portability, but this provider does not use them for selection.

## Selection

Explicit `skill:<name>` and `/skill <name>` requests select the named skill
directly. Otherwise, the provider sends candidate IDs, names, and descriptions
to the `skill_selector` assistant. The selector can choose at most three
skills. When model selection is unavailable, a deterministic local ranker uses
exact name phrases and token overlap with the name and description.

A skill is selected and rendered as one complete workflow. Its headings or
steps are never shortlisted independently because partial procedural injection
could omit required constraints or sequencing.

The `tft-unit-itemization` workflow supports unit-specific frequency,
performance, holder, and loadout questions. Role concepts can organize a
requested comparison when the user or supplied game reference establishes the
role; item statistics alone do not establish a unit's job, ability scaling, or
an item's mechanics.

Selected skills are injected only where the target assistant's instruction
policy allows them. They are not added to the named `chat` assistant's prompt
or exposed through frontend configuration. Names are unique, and repository
discovery examines direct child directories containing `SKILL.md`.

During graph preparation, a non-chat assistant is skill-eligible when repository
context is enabled or its spec has a nonempty skill allowlist. An omitted
allowlist remains unrestricted for eligible assistants; an explicit empty
allowlist denies skills. Context-disabled transcript assistants with no
allowlist are skipped. The selector's candidate pool respects eligible
assistants' allowlists; if any eligible assistant is unrestricted, the full
discovered pool remains available. Each assistant's own policy then filters the
selected skills before rendering.

Each assistant can restrict the workflows it may read with a `skills` name
allowlist in its `agent.json`. Omission allows every discovered skill, while an
empty list allows none. The instruction builder filters preselected workflows
before rendering, preserving the boundary when callers share one selection
across an invocation graph. The final responder permits only statistical
interpretation; the analyst can receive the investigation and itemization
workflows that support its query tools.

Provider behavior is covered by the Python tests and the frozen offline
Langfuse snapshot. Edit evaluation cases in the Langfuse dataset and export
the updated definition before committing changes:

```bash
uv run pytest -q tests/test_skill_provider.py tests/test_chat_service.py
uv run --extra evals chat-tft-evals run --suite skill_selection --offline
```
