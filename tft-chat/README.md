# ChatTFT

Normal entry point: run `python3 scripts/setup.py` from the suite root, then
`npm start` or `npm run dev` from `../desktop/`. See [suite setup](../docs/desktop.md).
Standalone commands below remain available for testing and troubleshooting.


A Teamfight Tactics chat app backed by a scoped Postgres match store and native
OpenAI Agents SDK tools.

The runtime path is intentionally small:

```text
Riot match ingestion -> current-patch/current-queue tables -> chat
                                                     -> data_analyst
```

Chat answers non-statistical conversation directly and hands every data-backed
TFT question to `data_analyst`, which owns the investigation and answers with
the minimum sufficient evidence.

## Agent-facing tools

| Group | Tools | Purpose |
| --- | --- | --- |
| `ranking` | name resolution plus unit, item, and trait rankings | Typed lookups, rankings, and filters |
| `query_cohorts` | `query_cohort`, `compare_cohorts` | Grouped anonymous-board analysis and comparisons |
| `probability` | `rolldown_probabilities` | Exact normal-shop rolldown odds with shared-pool depletion |
| `evidence` | `present_evidence` | Reference-only selection of backend-owned displays |

The final responder selects evidence displays by reference and supplies concise
prose; unsupported results remain Markdown. The registry
exposes no raw-row browser, generic leaderboard, ingestion, or match-store
mutation tools.

## Data flow

1. `tft-ingest` stores each Riot payload as a normalized match → participant
   board → exact unit-copy/item-slot/trait graph.
2. After each raw commit, the same batch is appended transactionally to its
   patch/queue/set analysis scope. Metrics are published and facts validated
   once after the ingestion run's batches. A processed-match ledger makes
   retries idempotent; analytics failures trigger catch-up, with endless mode
   also running a periodic recovery sweep.
3. Search and cohort tools expose only bounded structured JSON results. Raw
   rows, query relations, scope ids, counters, player identifiers, and
   timestamps remain private.
4. `chat-tft-rebuild-tables` catches up the configured patch/queue/set scope,
   reusing existing facts and aggregate counters. Add `--full-rebuild` to clear
   and recalculate that scope's derived data. Structured tools read those
   projections internally.

`player_units.cost` is the normalized 1-based shop gold cost. Existing databases
with the old zero-based `rarity` column are migrated when the schema opens.

## Install and run

```bash
pip install -e .
cd app/frontend && npm ci && npm run build && cd ../..
chat-tft-start
```

The UI is served at <http://127.0.0.1:8300>. It can start without RDS for
UI-only features and displays a warning while database features are
unavailable. Configure a complete application RDS target with `RDS_HOST`,
`RDS_PORT`, `RDS_ADMIN`, and `RDS_DB` to enable them; omit `RDS_PASSWORD` for
IAM authentication.

### Response continuation prompt tuning

Set `OPENAI_API_KEY` in `.env`, start the UI, and open **Prompt tuning** in the
sidebar. Paste a stored Responses API `response_id`, enter the candidate next
user message, and run it. The page fetches the parent only for debugging, then
creates the branch with `previous_response_id`; the key stays server-side.
Optional model, replacement instructions, temperature, and output-token limit
fields support quick runtime comparisons. The result panel shows the exact API
request, parent response/input items when available, output/tool items, usage,
errors, and latency.

Common commands:

```bash
# Ingest recent ranked matches.
tft-ingest --platform na1 --max-new-matches 50

# Reuse existing calculations and process newly stored matches.
chat-tft-rebuild-tables

# Explicitly reset and fully rebuild the configured analysis scope.
chat-tft-rebuild-tables --full-rebuild

# Legacy-v1 only: install its covering indexes before relational cutover.
tft-add-analysis-indexes

# Maintenance-window preflight/cutover from the retained legacy schema.
tft-migrate-relational-v2 --preflight-only
tft-migrate-relational-v2

# Create chat_tft_patch_10_5 in RDS and freeze patch 10.5.
tft-freeze-patch-db 10.5 --master-user-password "$RDS_MASTER_USER_PASSWORD"

# Copy an explicitly selected RDS/PostgreSQL source to a destination.
tft-copy-rds --source "$SOURCE_DSN" --destination "$DESTINATION_DSN"

# Download the configured application RDS database into local PostgreSQL.
chat-tft-download-rds --local-database chat_tft_local

# Report row counts for the latest patch in the application database.
tft-db-stats

# Force-sync this host's public IP into the configured RDS security group.
tft-sync-rds-ip

# Run the deterministic/unit test suite.
uv run pytest -q

# Preview a reference-aware Python symbol move; add --apply after review.
uv run --extra refactor tft-refactor-move \
  app/backend/src/source.py symbol_name app/backend/src/common/destination.py

# Start the Langfuse evaluation workspace (requires Docker and Compose).
uv sync --locked --extra evals
uv run chat-tft-evals up

# Run the frozen analyst definition (requires model credentials and eval data).
uv run chat-tft-evals run --suite data_analyst
```

Set `rebuild_query_tables_on_startup` in `chat_tft.ini` to `sync` or `async` if
the UI should run ledger-based catch-up automatically; the default is off.

`tft-freeze-patch-db PATCH` publishes a serving-ready database for the exact
configured patch/queue/set scope. It derives the new RDS instance's engine,
storage, network, and security-group settings from `RDS_INSTANCE_ID`, copies a
consistent normalized raw-graph snapshot,
rebuilds the target query tables, and validates counts, foreign keys, scope
identity, and processing completeness before reporting success. The target
identifier replaces the dot in the patch with a hyphen, so patch `10.5`
becomes `chat_tft_patch_10_5`; the database name remains `chat_tft` by default.
Set `RDS_MASTER_USER_PASSWORD` or pass `--master-user-password`. Publication
does not switch the application: cut over explicitly by setting the printed
`RDS_INSTANCE_ID`, `RDS_HOST`, `RDS_PORT`, `RDS_ADMIN`, and `RDS_DB` values.

## Configuration

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Enables assistant runs |
| `RIOT_API_KEY` | Enables Riot API ingestion |
| `RDS_*` / `RDS_EVAL_*` / `RDS_TEST_*` | RDS coordinates and optional passwords; eval values override `RDS_*` |
| `RDS_SECURITY_GROUP_ID` and related `RDS_*` knobs | Optional local-IP ingress sync |
| `CHAT_TFT_S3_UPLOAD`, `CHAT_TFT_S3_BUCKET`, `CHAT_TFT_S3_PREFIX` | Optional raw-payload mirror |

See [docs/README.md](docs/README.md) for the architecture, storage, tool, and
backend references.

## Using tools in code

```python
from domain.tools import call_tool, get_tool, list_tool_groups

tool = get_tool("rank_units")
resolved = await call_tool("resolve_tft_names", {"names": ["Jinx"]})
groups = list_tool_groups()
```

## Project layout

```text
app/backend/api/          FastAPI routes and UI server
app/backend/src/db/       storage, insertion, and query-table builders
app/backend/src/common/   dependency-light shared helpers
app/backend/src/domain/   assistants, prompts, tools, and tasks
app/backend/src/services/ chat and HTTP orchestration
app/frontend/             Vite frontend source, lockfile, and build output
scripts/                  ingestion, rebuild, transcription, and app CLIs
evals/                    Python evaluation execution, assertions, and traces
evals/langfuse/           Local platform, UI experiment integration, and snapshots
tests/                    pytest suites
docs/                     architecture and reference docs
```

## License

MIT
