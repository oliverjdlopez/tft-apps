# Ingestion and Upstreams

The ingestion system turns Riot match payloads and Community Dragon catalogue
data into the normalized PostgreSQL graph consumed by scoped analytics.

## Upstream boundaries

- `core/chat_tft_riot.py` wraps Pulsefire while preserving the repository's
  Riot method names, adaptive rate limiting, and error contract.
- `core/models.py` validates only the upstream payload slices used by the
  application.
- `core/routing.py` validates platform and regional routing relationships.
- `core/cdragon.py` and `utils/tft.py` resolve API identifiers to display names
  for the selected TFT set.
- `db/insert.py:insert_match_payload` writes the normalized match graph.
- `app/backend/src/aws/s3.py` optionally mirrors fetched raw JSON to S3.

## Concurrency and ordering

`scripts/ingestion/main.py` coordinates concurrent platform producers and one
shared database writer. Riot requests can run concurrently, but SQLAlchemy
sessions are never shared between producers. The producers feed bounded queues;
the writer owns the session and preserves per-platform ordering even when
requests finish out of order.

Writer shutdown drains queued work after a producer failure so queue
backpressure cannot deadlock cleanup. `fetch_concurrency` is always at least
one.

## Transactions and analytics

`scripts/ingestion/ingest.py:IngestionWriter` owns savepoints, commit batching,
analytics intervals, rollback recovery, and shutdown draining. Nested
transactions isolate a malformed match from the rest of a batch.

Raw commits become durable before their corresponding analytics batch. Each
analytics batch appends facts, counters, and processed-ledger rows under the
scope lock. Global metric publication and complete fact validation happen once
after the run's batches. An analytics failure rolls back only that analytics
transaction and triggers ledger catch-up; endless mode also runs periodic
recovery sweeps.

Replays are idempotent through raw match identity and
`analysis_processed_matches`.

## Normalized identity and cardinality

Unit, item, and trait names are normalized before storage. Item resolution uses
the exact match patch and TFT set, retains both canonical API and display
identity, and atomically upserts the patch/set `item_metadata` classification
snapshot with the match. Community Dragon structure and tags take precedence,
then stable API markers; unresolved completed items remain queryable as
`unknown`. A conflicting display name or family for an existing metadata key
rejects the ingestion transaction. Components remain excluded from completed-
item analytics.

Unit shop costs use the exact-patch Community Dragon champion cost when that
catalogue entry is available. This is the game's one-based 1-5 cost and avoids
confusing Riot's zero-based match `rarity` field with the displayed cost. If a
static unit entry or cost is unavailable, ingestion falls back to the
normalized Riot value and logs any disagreement between the two sources.

Exact unit-copy and item-slot cardinality is retained, including duplicate
copies. Unresolved catalogue names are logged rather than silently merged,
because flattening or guessing identities changes downstream weights and
cohort meaning.

Adding an upstream payload field therefore crosses four layers: payload
validation, normalization, relational storage, and recorded/schema fixture
coverage.

## Configuration surfaces

The CLI uses the configured application database and has no ingestion `--dsn`
option. Command-line flags override the typed `[ingest]` INI values for one
run. The HTTP request model exposes the same safe operational options while
excluding database and credential overrides.

`[ingest] patch_override` optionally replaces the normalized patch derived
from each Riot match's `info.game_version` when ingestion stores the match.
Leave it blank to use Riot's patch. When set, the override also selects the
patch-specific Community Dragon resolver and becomes the patch used by scoped
analytics and any `--patch` ingestion filter; the original Riot `game_version`
remains stored unchanged. The setting applies to CLI and API-triggered
ingestion.

S3 mirroring is optional. Its credentials come from boto3's standard provider
chain.

## Validation surfaces

```bash
uv run pytest -q tests/test_ingestion_lower_tiers.py tests/test_ingestion_cli_config.py tests/test_db_insert.py
uv run pytest -q tests/test_riot_client.py tests/test_riot_api_schemas.py tests/test_cdragon_schemas.py tests/test_tft_utils.py
```

The deterministic suite uses recorded and schema fixtures rather than live
Riot or Community Dragon availability.

## Ranked player discovery

`--tiers` (or `[ingest] tiers`) accepts `iron`, `bronze`, `silver`, `gold`,
`platinum`, `emerald`, `diamond`, `master`, `grandmaster`, and `challenger`,
without case sensitivity. The default remains `challenger,grandmaster,master`.
For example:

```bash
uv run chat-tft-ingest --tiers diamond,emerald
```

`scripts/ingestion/utils.py:ladder_entry_pages` uses the dedicated ladder
endpoints for Master and above. For Diamond and below it requests Riot's
`/tft/league/v1/entries/{tier}/{division}` endpoint, walks divisions I–IV,
and advances pages from 1 until an empty response ends each division.
Discovery deduplicates player PUUIDs across pages and tiers. Existing overall
collection limits still apply; capped runs stop requesting pages once their
player target is reached, while endless runs walk every selected division.
There is no per-tier budget or balancing: earlier tiers and divisions can
fill the existing target before later ones are visited.

Tier selection controls which players supply match histories. It does not
label every participant in those matches with that tier, persist rank
observations, or add rank filtering to the patch/queue/set analytics scope.
