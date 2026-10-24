# Skills, playbooks, and progressive disclosure

The authoring direction is for skills to provide reusable TFT-specific judgment
and for playbooks to guide broader analytical work. The shipped skills still
include general investigation and statistical interpretation guidance; the
reworked packages described below have not replaced them. Both categories are
complete resources read on demand through
`read_resource("skill:<name>")` or `read_resource("playbook:<name>")`. Assistants see only names and descriptions in
their permitted resource catalogue until they explicitly read the resource. Supporting procedures appear as child IDs
and are read separately with the same tool. No
provider or selector chooses workflows before execution. Factual game material
belongs in reference resources; durable assistant policy belongs in `system.md`.

Loading and protocol validation live in `domain.resources`. Skill packages
live under `app/backend/src/domain/resources/content/skills/<name>/SKILL.md`.

`domain.resources.models.Skill` and `Playbook` are explicit, immutable
`ResourceMetadata` subclasses. Entry-point loading stores these types in
`ResourceDescriptor.metadata`. Each enforces its own root ID namespace and kind,
and exposes the package `name` from its ID. Supporting documents retain ordinary
`ResourceMetadata`; complete bodies still load through `ResourceRead` on demand.

## Skill frontmatter

Three reworked packages are staged beside their originals under
`dev/resource_drafting/stashed/`:

- `tft-artifact-itemsv2/SKILL.md`: artifact compatibility and build-around requirements.
- `tft-reasoning-fundamentalsv2/SKILL.md`: board strength and combat bottlenecks.
- `tft-itemization-analysisv2/SKILL.md`: item allocation and build coherence.

Their frontmatter names match the requested directory names. Each is a complete,
self-contained skill with conditional examples and references to applicable
game resources. The originals remain intact. This location is outside runtime
discovery; writing these packages does not enable them for production assistants.
Validate the three packages in an isolated skill root, since the surrounding
stash also contains incomplete historical drafts. Format validation does not
establish model behavior; no live model evaluation accompanies these revisions.

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

The shipped chat spec sets `resources.skills` to `[]`. Other assistants qualify through
repository context or an explicit nonempty `resources.skills` allowlist and must also
have the read tool. An omitted allowlist permits all discovered skills for an
eligible assistant; an empty list permits none. Transcript-only assistants have
no model-facing resource access, although their context holds the shared library.
Renderers and reads use `AssistantSpec.allows_resource` to check the active spec
against that library, including every handoff and captured graph. No assistant
constructs a filtered library. Context stores shared materials and invocation-local
read records without assigning permissions.
The final responder
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

The shipped `final-response` playbook paraphrases the retained responder spec's
core guidance: answer the original question concisely from verified results,
state material uncertainty, and use supported evidence displays by reference.
Chat and the analyst read it before composing analytical final answers; its body
is retrieved on demand rather than inserted into their prompts. Its hyphenated
package name follows the existing playbook naming protocol.

Prototype playbooks in `dev/resource_drafting/playbooks/` explore broader modes
of analytical work: **Mapping the meta**, **Investigating interactions**, and
**Reconciling conflicting evidence**. They describe how to develop and test an
explanation rather than prescribing a fixed query sequence. These review drafts
are outside runtime discovery and do not alter assistant permissions or the
transcript pipeline. Their packages can be validated by passing that directory
as `playbook_root` to `domain.resources.library.validate_library`.

Create `app/backend/src/domain/resources/content/playbooks/<name>/PLAYBOOK.md` with the same
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

Use skills for TFT-specific judgment reused across tasks, and playbooks for
broader analytical approaches. Existing skill IDs
remain valid; adding this category does not move authored content automatically.

An assistant's `agent.json` can independently declare:

```json
{"resources": {"skills": ["general-guidance"], "playbooks": ["specific-guide"]}}
```

Omitting `resources.playbooks` permits all discovered playbooks for an eligible assistant;
`[]` denies them all. Eligibility requires repository context or an explicit
nonempty playbook allowlist, plus the `read_resource` tool. The shipped chat spec permits only `final-response` through
`resources.playbooks`, while its skill allowlist remains empty. The analyst's
omitted playbook allowlist permits the guide alongside other discovered
playbooks. Transcript-only assistants remain without resources unless explicitly
configured. Playbook bodies appear only in tool
results after a read, never automatically in instructions. Requests naming
`playbook:<name>` or `/playbook <name>` identify the guide the assistant should read.

Permissions are frozen per assistant and captured handoff graph. Historical
captures without a playbook field deny playbooks to preserve their original
capabilities. Newly captured graphs preserve the independent allowlist. The Specs
configuration summary displays both categories.

Skill and playbook discovery use the resource library exclusively. The provider classes,
lexical rankers, selector evaluators, and their compatibility models are removed.
