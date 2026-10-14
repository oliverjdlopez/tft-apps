# Skill resources and progressive disclosure

Repository skills are complete task procedures read on demand through
`read_resource("skill:<name>")`. Assistants see only names and descriptions in
their permitted resource catalogue until they explicitly read a skill. Supporting procedures appear as child IDs
and are read separately with the same tool. No
provider or selector chooses workflows before execution. Factual game material
belongs in reference resources; durable assistant policy belongs in `system.md`.

Loading and protocol validation live in `domain.resources`. Skill packages
live under `app/backend/src/resources/skills/<name>/SKILL.md`.

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
portability, but catalogue routing uses only name and description.

## Access and reading

Assistants choose relevant workflows from their catalogue. Explicit
`skill:<name>` or `/skill <name>` user requests identify the workflow to read;
there is no automatic preselection or fixed three-skill cap. The read returns
the complete skill body in a tool result, preserving sequencing and constraints.

Chat cannot discover or read skill bodies. Other assistants qualify through
repository context or an explicit nonempty `skills` allowlist and must also
have the read tool. An omitted allowlist permits all discovered skills for an
eligible assistant; an empty list permits none. Transcript-only assistants have
no resource access. Both metadata and reads enforce each assistant's own frozen
permissions, including every handoff and captured graph. The final responder
can read only `tft-statistical-interpretation`; it owns the context read group
alongside its evidence presentation group.

The `tft-unit-itemization` workflow supports unit-specific frequency,
performance, holder, and loadout questions. Role concepts require support from
the user or game references; item statistics alone do not establish ability
scaling or item mechanics.

```bash
.venv/bin/python -m pytest -q tests/test_skill_provider.py tests/test_assistant_runtime.py tests/test_assistant_access.py
```

The unit-itemization entry point now links to its allocation-patterns supporting
reference; its original interpretation guidance is retained verbatim there.

Historical selector snapshots are preserved. Offline lexical helpers support
historical fixture comparisons, while live selector execution is retired.
