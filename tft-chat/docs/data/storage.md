# Data

For the complete runtime schema, scope lifecycle, locking, and migration
boundaries, see [Persistence and Analytics](persistence-and-analytics.md).
The upstream concurrency and normalization pipeline is described in
[Ingestion and Upstreams](ingestion.md).

## Storage

The application uses AWS RDS PostgreSQL exclusively. `open_db()` resolves the
application target from `RDS_HOST`, `RDS_PORT`, `RDS_ADMIN`, and `RDS_DB`.
Those fields are required together; there is no implicit DSN fallback.
`RDS_PASSWORD` selects password authentication. When it is absent,
each physical connection receives a fresh IAM token and requires TLS.

Evaluation settings override the application target through the equivalent
`RDS_EVAL_*` variables; each missing eval value falls back to its `RDS_*`
counterpart. Test processes use `RDS_TEST_*` and remain isolated. A test database
must end in `_test` and must not share the app or eval host/port/database tuple.
Fixture-only evals do not resolve a database. Full DSNs are accepted only by
explicit maintenance
commands such as migration, index installation, rebuild/update, freeze source
selection, and `tft-copy-rds`. `chat-tft-download-rds` is the narrower
developer workflow: it resolves the configured application `RDS_*` target,
uses password or IAM authentication over TLS, and restores it into a named
local PostgreSQL database without exposing the source credential in process
arguments.

The typed `DatabaseTarget` keeps a credential-safe URL, purpose, auth mode,
RDS coordinates, and optional instance identifier. Eval execution scopes an
eval target with a context variable, so worker threads see it without changing
the process environment.

Analysis connections use bounded connection and pool-checkout timeouts. The API
attempts to validate the app target and warm its pool during startup. Missing,
partial, or unreachable app RDS settings leave the UI running in a degraded
mode with a visible warning; database-backed operations remain unavailable
until configuration is fixed. Each model-facing analysis transaction is
read-only and has a bounded PostgreSQL statement timeout. The implementation
settings are authoritative for current timeout values.

## Ingestion

`tft-ingest` resolves the app target and accepts typed ingestion options only.
The API trigger uses the same app target and rejects unknown fields, DSNs,
hosts, credentials, and arbitrary environment dictionaries.

## Query tables

The raw hierarchy is `raw_matches` → `player_boards` → `board_units` →
`unit_items`, with `board_traits` attached to each board and patch/set-scoped
`item_metadata` providing canonical item identity and family. `analysis_scopes`
fixes patch/queue/set identity and `analysis_processed_matches` makes
incremental aggregation idempotent. `tft-rebuild-tables` is the explicit
full-scope rebuild; startup modes run catch-up only.
