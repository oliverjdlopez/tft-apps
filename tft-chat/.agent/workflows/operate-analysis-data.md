---
id: operate-analysis-data
title: Operate analysis data
summary: Choose and validate rebuild, migration, copy, freeze, index, and stats operations.
paths:
  - "scripts/rebuild_tables/**"
  - "scripts/migrate_relational_v2.py"
  - "scripts/freeze_patch_db.py"
  - "scripts/copy_rds.py"
  - "scripts/download_rds.py"
  - "scripts/add_analysis_indexes.py"
  - "scripts/db_stats.py"
task_types: [rebuild-analysis, migrate-data, copy-database, freeze-patch, inspect-database]
keywords: [rebuild, migrate, preflight, freeze, publish, copy]
requires: [docs/data/persistence-and-analytics.md, docs/configuration.md]
last_verified: "2026-08-01"
---

# Operate analysis data

## Use this workflow when

Selecting or changing a database maintenance operation. Running these commands against real infrastructure requires an explicit target and, where destructive or costly, user authorization.

## Choose the operation

- Ledger-only lag, no processed raw mutation: `chat-tft-rebuild-tables` (default catch-up), or startup catch-up.
- Replace the configured patch/queue/set projection or repair a dirty scope: `chat-tft-rebuild-tables --full-rebuild`.
- Legacy-v1 covering indexes before cutover: `tft-add-analysis-indexes`.
- Relational-v2 cutover: `tft-migrate-relational-v2 --preflight-only`, then the migration in a maintenance window.
- Explicit source-to-destination PostgreSQL copy: `tft-copy-rds --source ... --destination ...`.
- Configured application RDS to local PostgreSQL: `chat-tft-download-rds --local-database ...`.
- Publish an exact patch to a new serving-ready RDS instance: `tft-freeze-patch-db PATCH`.
- Read-only counts/identity inspection: `tft-db-stats`.

## Before execution or code changes

1. Resolve and display credential-safe source/destination identity. Never infer a production target from an ambiguous environment.
2. Read the command parser and tests for supported dry-run/preflight/create/override flags.
3. Check scope identity and whether state is merely behind or marked dirty.
4. Ensure PostgreSQL client tools/AWS permissions and a rollback or retained-source plan exist.

## Required sequence

For migration, run preflight and stop on duplicates/orphans/ambiguous legacy objects. For freeze, validate the source scope, copy from a repeatable-read read-only snapshot, provision deterministically, rebuild the target, and require publication validation. Do not switch application settings automatically. A failed freeze target is intentionally retained for diagnosis.

For any operation, inspect returned counts, scope identity, processed-match parity, foreign keys, fact-build status, and internal aggregate sanity before declaring success.

## Validation for implementation changes

```bash
uv run pytest -q tests/test_rebuild_tables_cli.py tests/test_update_tables_cli.py tests/test_migrate_relational_v2.py
uv run pytest -q tests/test_freeze_patch_db.py tests/test_copy_rds.py tests/test_add_analysis_indexes.py tests/test_db_stats.py
uv run pytest -q tests/test_download_rds.py
```

## Completion checklist

- Exact targets and auth modes are known and redacted in logs.
- Correct catch-up versus full rebuild choice is documented.
- Preflight and post-operation validation passed.
- Application cutover, if desired, remains a separate explicit action.

## Common mistakes

Using catch-up for dirty processed data, skipping migration preflight, passing DSNs through logs, or assuming a successful freeze changed the running application's target.
