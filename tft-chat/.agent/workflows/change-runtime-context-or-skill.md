---
id: change-runtime-context-or-skill
title: Change runtime context or a skill
summary: Change product-selected factual context or focused TFT playbooks without mixing their roles.
paths:
  - "app/backend/src/domain/resources/context/**"
  - "app/backend/src/domain/resources/skills/**"
  - "app/backend/src/domain/providers/**"
task_types: [change-runtime-context, add-chat-skill, change-context-routing]
keywords: [context, skill, frontmatter, selection]
requires: [docs/content_providers/context.md, docs/content_providers/skills.md]
last_verified: "2026-08-03"
---

# Change runtime context or a skill

## Use this workflow when

Changing the factual TFT corpus, context-file parsing/ranking/budgets, or task playbooks selected for analyst handoffs.

## Before editing

Decide which layer owns the change: factual reference → `domain/resources/context`; task procedure → `domain/resources/skills`; durable assistant policy → `domain/assistant_specs`. Provider logic and models live in `domain/providers`. Read the provider and its tests before changing routing metadata.

## Implementation sequence

1. For context Markdown, use a unique stable `name` and one discriminating `description` that combines concrete contents, useful request shapes, and exclusions.
2. Use a separate file when sections need different routing descriptions; otherwise keep them together under meaningful headings. Split facts into independently useful paragraphs or list items.
3. For a skill, create one direct child directory with one protocol-compatible `SKILL.md`. Its name must match the directory, and its description must explain capability, activation cues, and boundaries without custom routing fields.
4. If provider behavior changes, preserve deterministic local selection, budgets, explicit skill selection, and latest-user/follow-up handling.
5. Verify chat injects the material at the intended layer only.

## Validation

```bash
uv run pytest -q tests/test_context_service.py tests/test_skill_provider.py tests/test_chat_service.py tests/test_assistants.py
```

## Completion checklist

- No duplicate document or skill names.
- Positive and unrelated-selection cases are covered.
- Set filtering and budgets still hold.
- Top-level chat, handoff, and direct-run injection boundaries remain intentional.

## Common mistakes

Writing monolithic context paragraphs, writing broad descriptions that cause accidental matches, adding generic process rules to factual context, or confusing product runtime content with `.agent/` coding-agent context.
