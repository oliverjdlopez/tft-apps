# Skills, playbooks, and progressive disclosure

Repository skills provide reusable general guidance; playbooks provide specific
task guides. Both are complete resources read on demand through
`read_resource("skill:<name>")` or `read_resource("playbook:<name>")`. Assistants see only names and descriptions in
their permitted resource catalogue until they explicitly read the resource. Supporting procedures appear as child IDs
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
.venv/bin/python -m pytest -q tests/test_resource_library.py tests/test_assistant_runtime.py tests/test_assistant_access.py
```

The unit-itemization entry point now links to its allocation-patterns supporting
reference; its original interpretation guidance is retained verbatim there.

## Adding a playbook

Create `app/backend/src/resources/playbooks/<name>/PLAYBOOK.md` with the same
`name` and `description` frontmatter rules as a skill:

```markdown
---
name: specific-guide
description: A step-by-step guide for a specific TFT task. Describe when to use it and its boundaries.
---
# Specific guide

Write the complete procedure, including prerequisites, steps, and caveats.
```

The package directory must match `name`. Its ID is `playbook:specific-guide`.
Supporting Markdown declares `kind: playbook-reference`, a child ID such as
`playbook:specific-guide/example`, and `parent: playbook:specific-guide`.
Children inherit the owning playbook's permissions. Links to skills or references
never grant additional access.

Use skills for guidance reused across many tasks (for example statistical
interpretation), and playbooks for concrete task sequences. Existing skill IDs
remain valid; adding this category does not move authored content automatically.

An assistant's `agent.json` can independently declare:

```json
{"skills": ["general-guidance"], "playbooks": ["specific-guide"]}
```

Omitting `playbooks` permits all discovered playbooks for an eligible assistant;
`[]` denies them all. Eligibility requires repository context or an explicit
nonempty playbook allowlist, plus the `read_resource` tool. Chat cannot read
playbooks, matching its skill boundary; transcript-only assistants remain without
resources unless explicitly configured. Playbook bodies appear only in tool
results after a read, never automatically in instructions. Requests naming
`playbook:<name>` or `/playbook <name>` identify the guide the assistant should read.

Permissions are frozen per assistant and captured handoff graph. Historical
captures without a playbook field deny playbooks to preserve their original
capabilities. Newly captured graphs preserve the independent allowlist. The Specs
configuration summary displays both categories.

Skill and playbook discovery use the resource library exclusively. The provider classes,
lexical rankers, selector evaluators, and their compatibility models are removed.
