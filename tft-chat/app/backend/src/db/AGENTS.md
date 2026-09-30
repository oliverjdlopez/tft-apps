# Database agent instructions

These rules apply under `app/backend/src/db/`.

- Read `docs/data/persistence-and-analytics.md` and `docs/data/analysis.md`. For schema work also read `.agent/workflows/change-database-schema.md`.
- Treat `RUNTIME_MODELS` as the runtime creation set; `Base.metadata` also contains retained legacy mappings. Query-table models are internal sources for bounded structured tools and are never model-queryable relations.
- `create_all` is not a migration. Existing-data cutovers require an explicit, validated maintenance path.
- Preserve the normalized raw graph, processed-match ledger, advisory-lock serialization, and atomic projection transactions.
- A mutation to already-processed raw ORM data must leave the affected scope dirty until a full rebuild; catch-up is not a repair for dirty projections.
- Keep tool transactions read-only and keep raw rows, identifiers, scope IDs, internal counters, and timestamps outside model-facing outputs.
- Run the narrow database tests listed in the persistence context. Database-backed tests must use isolated `RDS_TEST_*`, never app/eval targets.
