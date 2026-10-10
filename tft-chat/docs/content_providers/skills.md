# Skill Provider

The repository skill provider discovers portable Agent Skills, selects the
smallest useful set for a request, and injects each selected workflow in full.
`domain.providers.skills` owns provider operations and deterministic selection,
`domain.providers.models` defines the shared data and protocol contracts, and
`domain.providers.utils` contains loading, discovery, selector, and rendering
helpers. Skill packages live under
`app/backend/src/resources/skills/<name>/SKILL.md`.

Skills contain task procedures. Factual game reference material belongs in the
context corpus, while durable assistant behavior belongs in assistant
`system.md` files.

`AssistantAgent` owns the default skill provider; a non-`None`
`AssistantRunContext.skill_provider` overrides it for one invocation. The root's
`prepare_resources` method selects skills once, and every agent renders the
shared selection using its resolved provider and its specification's allowlist.
Context and skill overrides are independent. Handoffs and repeated model turns
do not reselect skills.

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

The `tft-unit-itemization` workflow distinguishes tank, fighter, and ranged
damage itemization archetypes so holder analysis can account for each role's
different balance of durability, offense, and resource generation.

Itemization and statistical investigation workflows start with the exact
question and use only exposed tools that can resolve it. Build-class comparisons
inspect observed loadouts, retaining hybrid or unclassified builds rather than
treating one signature item as the entire AP or AD population. Main-tank and
carry comparisons require a stated proxy based on recorded investment; mere
unit presence does not establish the role. These proxies describe allocation,
not positioning or measured combat contribution.

The statistical investigation, interpretation, and unit-itemization workflows
keep planning and diagnostic checks internal. Follow-up queries are conditional
on a material unresolved question, and an unavailable exact-build comparison
ends with a concise limitation rather than a substitute investigation. Responses
lead with the finding, use compact tables or available evidence displays for
supporting metrics and board samples, and state only limitations that affect the
conclusion. No workflow requires calls to every delta tool, a full set of outcome
metrics, repeated caveats, or an automatic follow-up offer.

Selected skills are injected only into contextualized handoffs. They are not
added to the top-level chat prompt or exposed through frontend configuration.
Names are unique, and repository discovery examines direct child directories
containing `SKILL.md`.

Each assistant can restrict the workflows it may read with a `skills` name
allowlist in its `agent.json`. Omission allows every discovered skill, while an
empty list allows none. The instruction builder filters preselected workflows
before rendering, preserving the boundary when callers share one selection
across a handoff graph.

Provider behavior is covered by the Python tests and the frozen offline
Langfuse snapshot. Edit evaluation cases in the Langfuse dataset and export
the updated definition before committing changes:

```bash
uv run pytest -q tests/test_skill_provider.py tests/test_chat_service.py
uv run --extra evals chat-tft-evals run --suite skill_selection --offline
```
