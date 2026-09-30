# Relational v2 maintenance migration

This cutover is deliberately offline. Do not run it while API or ingestion
writers are active.

## Before cutover

1. Stop the API, UI workers, and every ingestion process.
2. Take and retain an RDS snapshot.
3. Run the non-mutating preflight:

   ```bash
   tft-migrate-relational-v2 --preflight-only
   ```

Preflight reports source counts, repeated-match metadata conflicts, duplicate
board/unit-index keys, orphans, malformed packed trait segments, and both
legacy item representations. Any nondeterministic metadata, board, or
unit-index conflict aborts before DDL.

The migration recognizes both historical source layouts:

- packed v1: `all_matches`, `player_board`, `player_units`, and `player_items`;
- normalized v1: `matches`, `participants`, `participant_units`,
  `participant_unit_items`, and `participant_traits`.

Normalized-v1 databases can contain `unit_index` and `item_index` values that
were added to older rows with a default of zero. Preflight reports those
collisions, but they are not fatal: units are deterministically reindexed per
board, items are matched by participant plus character identity, and item slots
are deterministically reindexed. Relational v2 retains at most three completed
items per unit, matching current ingestion; the migration result reports any
excess source item rows it skipped.

## Cutover

```bash
tft-migrate-relational-v2 --batch-size 500
```

The command moves same-name v1 aggregates aside, creates normalized tables,
backfills bounded match batches, and resolves unit shop costs from exact-patch
Community Dragon metadata when available. This prevents legacy Riot `rarity`
values—including values outside the shop-cost range—from becoming persisted
costs. It then builds every represented patch/queue/set scope through the
runtime incremental processor, activates the configured scope, validates
foreign keys and orphans, and renames raw v1 sources with `_legacy`. It is
idempotent and uses those suffixed sources on a rerun. For normalized v1,
the source `matches` and derived `board_units` tables are moved aside before v2
schema creation because their names collide with relational-v2 tables.

The migration skips match IDs already present in relational v2. To correct
unit costs in a database that completed cutover before static-cost resolution
was added, use `scripts/repair_unit_costs.py` in dry-run mode and then rerun it
with `--apply`; that command repairs the raw rows and performs the required full
analytics rebuild.

The JSON result includes source/target counts, conflicts, skipped/malformed
rows, foreign-key validation, per-scope universe boards and aggregate counts,
processed-match lag, legacy/v2 aggregate counts, and elapsed time. Item outcome
metrics are expected to differ only where v1 weighted duplicate item instances
more than once per board.

## Enable traffic

1. Require zero normalized orphans, no unvalidated/missing foreign keys, and
   zero processed-match lag for the active scope.
2. Restart services with startup catch-up enabled once (`sync` is simplest).
3. Run catch-up again through a normal ingestion/startup cycle, then enable
   analysis traffic.
4. Retain all `_legacy` tables for one release. Remove them only in a separate,
   separately snapshotted cleanup migration after production metric validation.
