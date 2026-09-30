---
id: change-model-facing-tool
title: Change a model-facing tool
summary: Safely add or modify a bounded native Agents SDK tool.
paths:
  - "app/backend/src/domain/tools/**"
  - "app/backend/src/domain/assistant_specs/**"
task_types: [add-tool, change-tool-schema, modify-analysis-query]
keywords: [function_tool, tool schema, registry, structured result]
requires: [docs/tools/README.md]
last_verified: "2026-08-01"
---

# Change a model-facing tool

## Use this workflow when

Adding a tool, changing its arguments/output/query, moving group membership, or changing an assistant's access to it.

## Before editing

1. Read `domain.tools.__init__`, the target group module, and the related tests.
2. Confirm whether a typed structured ranking already expresses the request. Do not add overlapping free-form access.
3. If data exposure changes, read `docs/data/analysis.md` and inspect the input and result models plus minimum-sample enforcement.

## Implementation sequence

1. Implement an async typed function with a precise docstring and `@function_tool(strict_mode=True, ...)` in the owning module.
2. Bound strings, lists, numeric ranges, pagination, and returned rows using the repository's annotated Pydantic types.
3. Pass database work directly to `db_tools.utils.run_db_tool`; return dictionaries/lists/scalars, not ORM rows.
4. Add the SDK tool object to exactly one `AssistantToolGroup`; let the flat registry derive from groups. If the module exposes only this one bounded tool, declare an `AssistantTool` instead and register it in `_STANDALONE_TOOLS` (`domain/tools/__init__.py`) rather than inventing a single-member group.
5. Grant access in the relevant assistant `agent.json` only when intended. Update prompt tool-selection guidance when behavior—not just naming—changes.
6. Update docs and eval reachability expectations after registry behavior is correct.

## Required patterns

- Preserve the read-only transaction, timeout, minimum-sample filtering, name resolution, and typed result family.
- Preserve fetch-one-extra pagination when returning `page.has_more`.

## Validation

```bash
uv run pytest -q tests/test_openai_tools.py tests/test_ranking_tools.py tests/test_cohort_tools.py tests/test_cohort_facts.py tests/test_rolldown_tool.py
uv run pytest -q tests/test_assistants.py tests/test_chat_service.py
uv run python -m evals --validate
```

## Completion checklist

- Tool appears once in registry discovery and in only intended assistants' reachable graphs.
- JSON schema is strict and bounded; success, empty, invalid-input, timeout/error, and pagination behavior are covered.
- No raw or private identifiers became visible.
- Relevant prompt/docs/evals match actual names and semantics.

## Common mistakes

Maintaining a second hard-coded tool list, adding sync database calls inside async code, returning ad hoc result shapes, or assuming tool registration grants assistant access.
