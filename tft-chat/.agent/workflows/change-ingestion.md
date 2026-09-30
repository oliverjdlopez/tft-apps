---
id: change-ingestion
title: Change ingestion
summary: Change upstream fetching, normalization, raw inserts, and analytics catch-up coherently.
paths:
  - "scripts/ingestion/**"
  - "app/backend/src/core/chat_tft_riot.py"
  - "app/backend/src/core/cdragon.py"
  - "app/backend/src/db/insert.py"
task_types: [change-ingestion, change-normalization, change-upstream-schema]
keywords: [ingest, Riot, cdragon, normalize, writer]
requires: [docs/data/ingestion.md]
last_verified: "2026-08-01"
---

# Change ingestion

## Use this workflow when

Changing platform production, Riot calls/schemas, Community Dragon normalization, writer batching, raw insertion, analytics cadence, or S3 mirroring.

## Before editing

Trace one match from producer to bounded queue, `IngestionWriter`, `insert_match_payload`, raw commit, and `process_match_batch`. Identify whether the change affects exact copy/slot cardinality or the configured scope.

## Implementation sequence

1. Update consumed upstream Pydantic slices and routing/client adapters.
2. Update normalization with set-aware lookup and unresolved-name logging.
3. Change raw insertion within the writer-owned session/savepoint boundary.
4. Preserve raw-first durability and later idempotent analytics processing.
5. Add corresponding CLI/INI override only if it is safe for both direct and API-triggered ingestion; infrastructure values remain forbidden in HTTP bodies.
6. Update fixture/unit coverage before a bounded live integration run.

## Required patterns

- Concurrent producers, one session-owning writer, bounded queues, orderly draining.
- At least one fetch worker; no session access from producer tasks.
- Duplicate units/items remain distinct by unit copy and item slot.
- App target only; no ingestion DSN.

## Validation

```bash
uv run pytest -q tests/test_ingestion_cli_config.py tests/test_db_insert.py tests/test_riot_client.py tests/test_riot_api_schemas.py tests/test_cdragon_schemas.py tests/test_tft_utils.py
uv run pytest -q tests/test_build_query_tables.py tests/test_relational_analytics.py
```

## Completion checklist

- Retries/replays are idempotent and one bad match does not discard a valid batch.
- Producer failure cannot deadlock writer shutdown.
- Raw success remains durable if analytics fails.
- Name and set semantics reach downstream aggregates correctly.

## Common mistakes

Sharing SQLAlchemy sessions across async tasks, removing queue backpressure, collapsing duplicate item instances, or testing only happy-path sequential ingestion.
