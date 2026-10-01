# Configuration

`app/backend/src/core/config.py` is the canonical configuration loader. It
combines non-secret application behavior from `chat_tft.ini` with secrets and
infrastructure coordinates from `.env` or the process environment and returns
frozen typed dataclasses. `core/settings.py` remains a compatibility layer over
that configuration.

## Application settings

The tracked `chat_tft.ini.example` is the complete template for local
application behavior. Its sections cover model choices, chat and MCP settings,
UI binding, analysis scope, startup catch-up, tracing, ingestion behavior, and
RDS upgrade defaults. A local deployment normally copies it to the ignored
`chat_tft.ini` at the repository root.

For example, the active analysis patch can be pinned instead of inferred from
the latest represented patch:

```ini
[chat]
patch = 16.13
set_number = 16
```

CLI options owned by a command are one-run overrides rather than additional
environment contracts.

The optional `[ingest] patch_override` value manually sets the normalized
patch stored for every ingested Riot match, overriding the patch inferred from
the API's `game_version`. Leave it blank to retain Riot's value. The original
`game_version` is preserved, while the override selects the resolver patch and
the analytics patch scope, and is used when evaluating an ingestion `--patch`
filter. It applies to both CLI and API-triggered ingestion.

## Secrets and infrastructure

Media sharing defaults to `<suite>/media` independently of the working directory.
`TFT_MEDIA_DIR` can select another absolute directory for standalone processes;
an explicitly empty export disables sharing. The desktop always uses the
suite-owned directory instead of inherited source storage. This coordinate does
not initialize RDS or combine Python environments. See
[suite media sharing](../../docs/shared-media.md).

`.env.example` documents model API keys, the Riot key, typed database targets,
AWS-related RDS controls, eval operation/judge timeouts, and S3 toggles.
Non-secret persistent application behavior is kept in the INI file.

The database target prefixes are:

| Purpose | Prefix | Fallback |
| --- | --- | --- |
| Application | `RDS_` | None |
| Evaluation | `RDS_EVAL_` | Corresponding application field |
| Test | `RDS_TEST_` | None |

App targets require complete `HOST`, `ADMIN`, and `DB` fields; `PORT` defaults
to 5432. A password selects password authentication. Without one, every new
physical RDS connection receives an IAM token and uses TLS. Test database names
must end in `_test` and cannot share app or eval coordinates.

Full database DSNs are maintenance-command inputs only. Application runtime
does not read a `CHAT_TFT_DATABASE_URL`-style environment variable. Resolved
URLs, logs, and subprocess displays use credential-safe forms.

Langfuse's Custom Experiment configuration controls case selection, model/prompt
variants, concurrency, repetitions, and offline/live selector mode. The Python
service processes one queued job at a time, with one to four concurrent attempts
(default four). This cap bounds application execution; Langfuse schedules quality
grading separately. Each variant/repetition produces a separate native experiment.
Required assertion failures and execution/judge errors fail the attempt.
`EVAL_OPERATION_TIMEOUT_SECONDS` defaults to `180` and bounds each isolated
application operation; a timeout terminates its local process group.
`EVAL_JUDGE_TIMEOUT_SECONDS` defaults to `45` for historical Python rubric replay.
`EVAL_JUDGE_MODEL` selects the initial native judge model; later changes belong
in the native evaluator editor. Evaluation definitions accept optional database
names on typed eval coordinates, not DSNs. Case `metadata.database` overrides
the suite's `database`; missing or null values fall back to the suite and then
the configured evaluation target. This allows assistant cases from multiple TFT
sets in one dataset; see [case database selection](development/langfuse-content.md#keep-cases-from-multiple-tft-sets).
`data_snapshot_label` records
provenance only and never selects the database.

`chat-tft-evals up` creates private platform credentials in
`evals/langfuse/.env` and starts the Docker Compose stack. Its generated
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_EXPERIMENT_TOKEN`
connect the native UI to the Python experiment service. Keep this file paired
with the persistent volumes. The runner reads existing model/RDS settings from
the repository `.env` on the host, so local PostgreSQL addresses work directly.
A Docker forwarder relays authenticated webhooks over a private Unix socket.
Use `chat-tft-evals restart-runner` to reload Python or configuration changes. See [local deployment](development/langfuse-local.md)
for login, backup, network, and container configuration.

Use `uv run --extra evals chat-tft-evals validate` and the commands in
[Tests and evaluations](development/testing-and-evals.md). Validation and
`run --suite dummy_assistant --offline` need no model credentials or running
platform. Online `run` freezes the current native dataset and baseline prompt labels, then
exports its effective configuration before execution. Explicit snapshot replay
uses the original frozen definitions. The explicit live
GitHub workflow reads model/RDS credentials from its `evals` environment;
ordinary CI uses offline fixtures and a local credential-free platform smoke.

## AWS behavior

`app/backend/src/aws/rds.py` owns boto3 clients, IAM tokens, connection data,
and optional developer IP ingress synchronization. When a security group is
configured, opening a physical connection can refresh the managed IPv4 rule;
`RDS_SYNC_LOCAL_IP=0` disables that behavior.

Patch freezing derives provisioning parameters from the source instance but
does not rewrite application configuration after publication. Database copies
use PostgreSQL client tools and redact credentials in displayed arguments.

The S3 raw-payload mirror is optional. Boto3 obtains AWS credentials through
its standard provider chain rather than application-specific settings.
The standalone `connectivity_check.py` command loads the canonical `.env`
configuration before running its S3 and PostgreSQL checks, so it can be run
directly from the repository without first exporting those variables in the
shell.

## Configuration validation

Configuration and infrastructure behavior is covered by:

```bash
uv run pytest -q tests/test_config.py tests/test_repository_consistency.py
uv run pytest -q tests/test_rds_ip_sync.py tests/test_sync_rds_ip_cli.py tests/test_rds_upgrade.py
uv run pytest -q tests/test_copy_rds.py tests/test_freeze_patch_db.py
```

## Optional Langfuse development tracing

`[chat] langfuse_tracing = false` is the default. Enable it explicitly and install
the `evals` optional dependencies to export conversation roots and nested Agents
operations. Configure `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, and
`LANGFUSE_SECRET_KEY` in the environment. Development observations use a separate
`development` environment and do not trigger paid evaluation rules. Missing
instrumentation or exporter failures do not fail chat.

Natural-contract evaluations use platform-managed quality evaluators. The
initial native OpenAI connection uses the existing credential and resolved
`EVAL_JUDGE_MODEL`/application model. Subsequent startup preserves UI edits.
Execution checkpoints enter `awaiting_scores`; the fixed grading deadline is
600 seconds with bounded polling and restart recovery. The old sequential Python
rubric path applies only to legacy definitions, not the new browser workflow.

`LANGFUSE_TEST_DEPLOYMENT=1` is a deployment-only CI switch: it seeds the internal
fixture and starts the local mock model endpoint for credential-free native
judge scheduling. Never use it to replace an existing production connection.

## Flowchart workspaces

`[chat] flowchart_source = database` is the default source for the
[Flowchart](apps/flowchart.md) tab: editable workspaces in the
`chat_tft_dev_workspaces` table on the application RDS target. Set it to `json`
to open the checked-in `gameplans/*.json` documents read-only instead. Any other
value fails configuration loading. `/api/config` publishes the value, and the
page's source switch and each route's `?source=` parameter override it per view
or request.

## Composition workbench

`[chat] composition_workbench = true` is the default, enabling the standalone
`/compositions` developer workspace, its Electron tab, private endpoints, and
experiment worker when the database is available. Set it to `false` and restart
the backend to disable the workbench. Offline mode remains disabled by default
(`composition_offline = false`). Install algorithm libraries
with `uv sync --extra compositions`. By default the feature uses the complete typed application
RDS target for private experiment tables and ready source facts. Set
`[chat] composition_offline = true` and restart to use the checked-in
`dev/compositions/eligible-boards.json` population and automatically initialized
local history at `.runtime/compositions/experiments.db` instead. This development
switch affects only Compositions; no RDS settings or other application database
operations are redirected. No DSN setting or credentials reach the renderer.
Fixture display itself needs no database.
See the [composition guide](architecture/compositions/index.md).
