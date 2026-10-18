---
id: change-runtime-context-or-skill
title: Change runtime context or a skill
summary: Change progressively disclosed factual references or focused TFT playbooks without mixing their roles.
paths:
  - "app/backend/src/resources/references/**"
  - "app/backend/src/resources/skills/**"
  - "app/backend/src/resources/playbooks/**"
  - "app/backend/src/domain/resources/**"
task_types: [change-runtime-context, add-chat-skill, change-context-routing]
keywords: [context, skill, frontmatter, selection]
requires: [docs/content_providers/context.md, docs/content_providers/skills.md]
last_verified: "2026-08-03"
---

# Change runtime context or a skill

## Use this workflow when

Changing the factual TFT corpus, context-file parsing/ranking/budgets, or task playbooks selected for analyst handoffs.

## Before editing

Decide which layer owns the change: factual reference → `resources/references`; general guidance → `resources/skills`; specific task guide → `resources/playbooks`; durable assistant policy → `domain/assistant_specs`. Resource loading, validation, and models live in `domain/resources`; assistant configuration selects exposure in `domain/assistants/utils.py`; the resource library supplies listings and complete content, while `domain/tools/context.py` formats read responses. Runtime only coordinates setup and retains invocation state. Assistant renderers format directory metadata into prompts. Read the library and its tests before changing routing metadata.

## Implementation sequence

1. For context Markdown, use a unique stable `id`, explicit parent and set scope, title and one discriminating `description` that combines concrete contents, useful request shapes, and exclusions.
2. Use a separate file when sections need different routing descriptions; otherwise keep them together under meaningful headings. Split facts into independently useful paragraphs or list items.
3. For a skill, create one direct child directory with one protocol-compatible `SKILL.md`. Its name must match the directory, and its description must explain capability, activation cues, and boundaries without custom routing fields.
4. For a playbook, create `resources/playbooks/<name>/PLAYBOOK.md` with the same name/description rules. Use `playbook:<name>` IDs, `playbook-reference` children, and the independent `playbooks` assistant allowlist.
5. Preserve exact catalogue IDs, complete resource reads, set eligibility, and per-assistant read permissions. No provider or selector preselects prompt bodies.
6. Verify instructions contain only permitted metadata and read tool results contain full bodies. Chat cannot read skill or playbook bodies.

## Validation

```bash
.venv/bin/python -m domain.resources
uv run pytest -q tests/test_resource_library.py tests/test_chat_service.py tests/test_assistants.py
```

## Completion checklist

- No duplicate document or skill names.
- Successful reads, unknown IDs, unsupported sets, and denied reads are covered.
- Set filtering and complete collection reads still hold.
- Top-level chat, handoff, and direct-run injection boundaries remain intentional.

## Common mistakes

Writing monolithic context paragraphs, writing broad descriptions that cause accidental matches, adding generic process rules to factual context, or confusing product runtime content with `.agent/` coding-agent context.
