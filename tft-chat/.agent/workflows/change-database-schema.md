---
id: change-database-schema
title: Change the database schema
summary: Coordinate ORM changes, runtime creation, explicit migration, projections, and validation.
paths:
  - "app/backend/src/db/**"
  - "scripts/migrate_relational_v2.py"
  - "scripts/update_tables/**"
task_types: [change-schema, add-migration, rename-column]
keywords: [model, column, table, migration, schema]
requires: [docs/data/persistence-and-analytics.md]
last_verified: "2026-08-01"
---

# Change the database schema

## Use this workflow when

Adding/renaming/removing a persisted field/table/index/constraint or changing normalized, fact, aggregate, or compatibility schemas.

## Before editing

1. Classify the target as raw graph, scope/ledger, private fact, internal aggregate, compatibility projection, or retained legacy mapping.
2. Inspect `RUNTIME_MODELS`, `QUERY_TABLE_MODELS`, model catalog, creation path, existing migration code, and affected tests.
3. Determine whether existing deployed data needs an explicit maintenance migration. `create_all` is not a migration.

## Implementation sequence

1. Change the owning ORM model and indexes/constraints.
2. Update `RUNTIME_MODELS` or `QUERY_TABLE_MODELS` only when the table belongs there.
3. Update insertion, projection, bounded-query code, and result documentation for any semantic change.
4. Add an idempotent or explicitly preflighted migration path. Startup may perform only narrowly safe compatibility normalization; table cutovers belong in maintenance scripts.
5. Update validation/count checks, model catalog, tracked docs, and tests.
6. Test against isolated `RDS_TEST_*`; never experiment on app/eval targets.

## Required patterns

- Preserve cascade and composite identity semantics of the normalized graph.
- Preserve atomic projection + ledger transactions and dirty-scope marking.
- Maintain 1-based `cost`; reject partial `rarity`/`cost` states.
- For tool-visible changes, preserve privacy and minimum-sample constraints.

## Validation

```bash
uv run pytest -q tests/test_db_session.py tests/test_db_insert.py tests/test_build_query_tables.py tests/test_relational_analytics.py
uv run pytest -q tests/test_migrate_relational_v2.py tests/test_update_tables_cli.py tests/test_rebuild_tables_cli.py tests/test_model_catalog.py
uv run pytest -q tests/test_ranking_tools.py tests/test_cohort_tools.py tests/test_cohort_facts.py
```

## Completion checklist

- Empty/current/legacy/partial schema states have defined behavior.
- Runtime creation does not accidentally create retained legacy tables.
- Migration has preflight, validation, and failure behavior.
- Rebuild/catch-up semantics after the change are explicit.

## Common mistakes

Editing old migration-era docs as if they migrate data, assuming ORM metadata equals runtime schema, or adding a column only to the ORM while projections and safe schemas stay stale.
