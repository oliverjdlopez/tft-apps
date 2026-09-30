---
id: analysis-data-contract
title: Analysis data contract
summary: Cross-cutting ownership and privacy contract from raw Riot payloads to bounded structured results.
paths:
  - "app/backend/src/db/**"
  - "app/backend/src/domain/tools/**"
  - "scripts/ingestion/**"
task_types:
  - change-data-flow
  - change-analysis-scope
  - change-data-exposure
keywords:
  - raw graph
  - aggregate
  - scope
  - ledger
  - privacy
  - minimum sample
depends_on: []
related:
  - docs/data/persistence-and-analytics.md
  - docs/data/ingestion.md
  - docs/tools/README.md
last_verified: "2026-08-03"
---

# Analysis data contract

## Load this context when

A change crosses ingestion, database projections, or model-facing queries, especially when it affects population scope, identifiers, sample thresholds, or exposed columns.

## Lifecycle and ownership

1. `scripts/ingestion` fetches Riot payloads and `db.insert.insert_match_payload` normalizes them into `raw_matches` → `player_boards` → `board_units` → `unit_items`, with `board_traits` attached to boards and patch/set `item_metadata` preserving canonical item identity and family.
2. One active `analysis_scopes` row fixes patch, queue, and TFT set. `analysis_processed_matches` makes incremental projection idempotent.
3. Private anonymous board-grain fact tables support bounded cohort queries. UUIDv5 lobby/board keys replace match and player identifiers.
4. Four scoped aggregate projections—unit, item, trait, and unit-loadout stats—feed bounded ranking tools but are not model-queryable relations.
5. Investigation tools return typed JSON summaries; they do not return raw rows, player identifiers, scope IDs, internal counters, or timestamps.

## Invariants

- Raw insertion may commit before analytics. A later projection failure leaves raw data durable for ledger catch-up.
- Incremental analytics for a scope is serialized by an in-process lock and PostgreSQL advisory transaction lock. Do not add a second unsynchronized projection writer.
- Mutating already-processed raw ORM objects marks affected scopes and fact builds `dirty`; a full rebuild is then required.
- An analysis fact build is usable only after source counts, anonymous lobby counts, foreign keys, schema version, and processed-match parity validate.
- Completed raw items, anonymous item facts, and item aggregates must retain canonical API identity and agree with the exact scope's persisted item metadata.
- Structured tools enforce minimum samples and suppress nonempty cohorts below 50 boards. Preserve both those checks and the database read-only transaction.
- `boards` is distinct `(match_id, puuid)`. Item `holds` is item-instance weighted, while item outcome rates are board-weighted. Final boards are observational, not causal evidence.
- Resolve user entity names through `resolve_tft_names`; stored display names and legacy API names can differ.

## Boundaries

- `QUERY_TABLE_MODELS` groups internal projections; tool schemas and result models are the model-facing contract.
- `domain.tools.db_tools.utils.run_db_tool` runs sync database work off the event loop, uses a fresh session, marks PostgreSQL transactions read-only, applies a bounded statement timeout, rolls back, and closes.
- Ingestion and maintenance CLIs may mutate data. Model-facing tools may not.

## Common failure modes

- Exposing aggregate relations, compatibility tables, or normalized raw tables through a model-facing tool.
- Counting item rows as independent games, or comparing unfiltered cohorts without reporting sample size.
- changing raw rows after projection without rebuilding dirty scopes.
- Treating `catch_up_query_tables` as a full repair; catch-up only processes ledger-missing matches, while dirty data needs rebuild.

## Evidence and uncertainty

The current contract is enforced by the `db/models/` package,
`db/build_query_tables.py`, `domain/tools/db_tools/ranking_tools.py`,
`domain/tools/db_tools/cohort_tools.py`, `domain/tools/db_tools/utils.py`, and
their tests. `docs/data/storage.md` says
analysis pool checkout is five seconds, but `db.session.POOL_TIMEOUT_SECONDS`
is currently 15; source and tests take precedence until the prose is reconciled.
