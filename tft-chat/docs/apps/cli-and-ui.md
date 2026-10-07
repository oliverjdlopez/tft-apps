# Applications

The detailed FastAPI lifecycle, streaming protocol, and frontend loading model
are documented in [Web Runtime and Browser UI](../architecture/web-runtime.md).

## Unified UI

The UI requires the locked frontend dependencies and a production build before
the FastAPI service starts serving browser assets:

```bash
cd app/frontend
npm ci
npm run build
cd ../..
```

```bash
chat_tft_start
```

The UI binds to `ui_host` and `ui_port` in the ignored `chat_tft.ini` (the
tracked `chat_tft.ini.example` is the complete template). Model, chat, scope,
tracing, and ingestion behaviour is INI-owned; `.env` contains secrets and
infrastructure only.

The application can start without a complete `RDS_*` target so UI-only
features remain available. A persistent browser warning identifies the
degraded state, and database-backed operations remain unavailable. Configure
the full target to enable them. Use `RDS_PASSWORD` for password auth or omit it
for IAM auth. Eval settings may override the normal target with `RDS_EVAL_*`;
missing eval values fall back to their corresponding `RDS_*` values. Test
targets use `RDS_TEST_*` settings.

For frontend development, use `npm run dev` from `app/frontend`. Vite proxies
`/api` and `/static` to the FastAPI service on port 8300.

## Ingestion CLI

```bash
tft-ingest --platform na1 --max-new-matches 50
```

CLI flags are one-run overrides of the typed `[ingest]` settings. Ingestion
always uses the configured app target; it has no `--dsn` option. Endless mode
uses `--endless` and `--cycle-delay` and can also be configured in the INI.

Maintenance tools accept explicit DSNs only where their operation requires a
controlled source or destination. The canonical RDS copy command is:

```bash
tft-copy-rds --source "$SOURCE_DSN" --destination "$DESTINATION_DSN"
```

To download the configured application RDS database into local PostgreSQL,
use its `RDS_*` coordinates and optionally choose the local database name:

```bash
chat-tft-download-rds --local-database chat_tft_local
```

The command creates the local database when absent and uses the current local
libpq user and Unix-domain socket. Creation connects to the local `postgres`
maintenance database through that same socket. Pass `--drop-existing-objects`
only when the matching objects in an existing local database should be
replaced.

`chat-tft-rebuild-tables`, `chat-tft-update-tables`, and
`chat-tft-add-analysis-indexes` use the app target by default and accept an
explicit maintenance override.

`uv run chat-tft-rebuild-tables` reuses existing calculations and processes only
ledger-missing matches. Use `uv run chat-tft-rebuild-tables --full-rebuild` to
clear and recalculate the configured scope's derived data, including repairs to
dirty scopes. Planner profiling flags (`--explain` and `--explain-analyze`)
require `--full-rebuild`. See [query table maintenance](../data/persistence-and-analytics.md#query-table-maintenance-cli)
for counts, transaction behavior, and target options.

## Documentation site

The documentation uses Sphinx with the Furo theme. `docs/conf.py` owns theme
options and loads `docs/_static/custom.css`, which provides the responsive
ChatTFT color system, landing-page cards, navigation states, and styled
reading components for both light and dark modes.

Build the static Sphinx site into `docs/_build/html` with:

```bash
uv run --extra docs chat-tft-docs --build
```

For live rebuilding on port 8001:

```bash
uv run --extra docs chat-tft-docs
```
