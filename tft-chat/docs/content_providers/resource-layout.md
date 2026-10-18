# Resource layout and schema

The resource library separates identity, discovery metadata, and complete content.
Physical paths can change while authored IDs and links remain stable.
`domain.resources` manages this library without assistant presentation or access
policy. Its library lists catalogue metadata and loads complete contents. Assistant
configuration selects exposure from specs; assistant renderers format prompts,
and `domain.tools.context` formats read responses and records actual reads.
Runtime retains invocation state and coordinates setup.
Assistant renderers choose how to format those listings into instructions.

```text
app/backend/src/resources/
  references/set18/
    index.md
    units/index.md
    units/roster.md
    items/index.md
    augments/index.md
    traits/index.md
    systems/index.md
    wisps/index.md
    wisps/rules.md
    wisps/offers-goldxp.md
    wisps/offers-goldxp.json
  skills/tft-unit-itemization/
    SKILL.md
    references/allocation-patterns.md
  playbooks/<name>/
    PLAYBOOK.md
    references/example.md
```

## Reference metadata

```yaml
---
id: set18/units/roster
title: Champion roster
description: Complete champion population with costs, traits, roles, and forms.
kind: reference
parent: set18/units
sets: ['18']
patches: ['18.1']
related: [set18/systems/reference-conflicts]
provenance: Source coverage and revision notes belong here.
---
# Complete champion roster
```

`id` is a set, skill, or playbook namespace followed by lowercase slash-separated names.
`kind` is `index`, `reference`, `records`, `skill`, `skill-reference`, `playbook`, or
`playbook-reference`.
Every reference declares its set scope; children inherit their parent's scope.
Every non-root reference has a known parent. Reference roots are indexes. Skill
supporting resources inherit the owning package's permission; they cannot grant
new access through links. Stable IDs are the only resource identities; old provider aliases are not accepted.

`requires` names resources needed to interpret the facts correctly. `related`
names useful adjacent references; those links may be mutual. Required dependency
cycles are invalid. Reads return only links the caller may access. The model
must read required facts before making a claim that depends on them; the library
does not reintroduce automatic prompt injection.

## Indexes and complete reads

An index body gives a brief overview and scope. The read tool supplies children
from their parent metadata, so authors do not maintain a duplicate child inventory.
Initially, assistants see root references and permitted skill entry points only.
Index contents and children arrive together as tool output. Use meaningful
reference boundaries, preserving all caveats and conditions within each leaf.
Retain complete population documents for counts, odds, and exhaustive comparisons.

## Typed record collections

A `records` descriptor adds `data_file: offers-goldxp.json` and a `views` list
such as `[stage-2, stage-3, stage-all]`. Backing JSON must be in the same directory,
owned by exactly one descriptor, and use schema version 1. Each record has:

- a stable `id`, display `name`, and complete original `text`;
- `offer_windows`: inclusive `{start: [stage, round], end: [stage, round]}` objects;
- `all_stages`: explicitly true only when there are no restricted windows;
- `modes`, `conditions`, and `augment_exclusions`.

Source text preserves additional restrictions even when a normalized field is
empty. These are Wisp records; adding another record family requires its own
explicit typed schema rather than accepting arbitrary JSON. Validation checks
unique names/IDs, ordered windows, and exact agreement between declared views and
record eligibility. Runtime views use typed windows, never regexes over prose.
The complete category remains readable alongside all its views.

## Portable skills

Keep standard `name` and `description` YAML frontmatter in `SKILL.md`; its name
must match the direct-child package. Standard optional protocol fields are
accepted without becoming routing rules. IDs are `skill:<name>`.
Supporting Markdown uses the reference metadata schema with `kind:
skill-reference`, an ID such as `skill:tft-unit-itemization/allocation-patterns`,
and `parent: skill:tft-unit-itemization`. The entry point links to required
supporting procedures and the read tool exposes its permitted child directory.
Chat cannot discover or read skill entry points or their descendants.

## Specific playbooks

Playbooks live under `resources/playbooks/<name>/PLAYBOOK.md`. They use `name`
and `description` frontmatter with the same package naming and description
limits as skills. IDs use `playbook:<name>`; supporting Markdown uses
`kind: playbook-reference`, child IDs such as `playbook:<name>/example`, and an
explicit parent within the same package. Storage namespaces and resource kinds
must agree. Their `resources.playbooks` allowlist is independent of `resources.skills`; both apply
to children and exact reads. See [authoring and access](skills.md#adding-a-playbook).
The metadata cache tracks changes in all three resource roots.

## Offline checks

```bash
.venv/bin/python -m domain.resources
uv lock --check --offline
.venv/bin/python -m pytest -q tests/test_resource_library.py
```

The first command checks all metadata, links, bodies, and derived views. PyYAML
is an explicit dependency; resources use safe loading with duplicate-key rejection.
The shared flat parser remains unchanged for older configuration and fixtures.
