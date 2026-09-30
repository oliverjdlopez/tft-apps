# Modules

- [Backend Reference](backend.md): native OpenAI SDK tools, clients, data layer,
  and models.
- [Runtime Flow](../architecture/flow.md): how chat, ingestion, stats, and explorer requests move
  through the codebase.
- [Web Runtime](../architecture/web-runtime.md): FastAPI lifecycle, service ownership, streaming, and the browser loader.
- [Assistants and Tasks](../architecture/assistants-and-tasks.md): specs, graph construction, instruction layers, and task pipelines.
- [Applications](../apps/cli-and-ui.md): local UI and CLI entry points.
- [Transcription](../apps/transcription.md): media transcription and transcript assistant processing.
- [Configuration](../configuration.md): INI and environment ownership plus typed database targets.
- [Storage](../data/storage.md): RDS Postgres storage, ingestion, and S3 upload behavior.
- [Analysis](../data/analysis.md): scope, filters, thresholds, and metrics for investigations.
- [Ingestion](../data/ingestion.md): upstream clients, concurrency, normalization, and transaction ordering.
- [Persistence](../data/persistence-and-analytics.md): schema creation, scope processing, locks, and maintenance boundaries.
- [Tools](../tools/README.md): registry entry points and exposed tool list.
- [Ranking Tool Group](../tool_groups/ranking.md): name resolution plus bounded,
  structured rankings across the aggregate projections.
- [Query Cohorts](../tool_groups/query_cohorts.md): grouped anonymous-board
  cohort queries and comparisons.
- [Cohort Deltas](../tool_groups/deltas.md): frequency-first anonymous-board
  cohort-relative entity breakouts.
- [Evidence displays](../tool_groups/evidence.md): backend-owned datasets and reference-only display choices.
- [API Reference](api/index.rst): autodoc pages generated from `app/backend` docstrings.
- [Tests and Evaluations](../development/testing-and-evals.md): CI, database fixture isolation, Langfuse datasets, snapshots, and model/prompt experiments.

## Backend packages

All backend packages live under `app/backend`.

- `api` owns the FastAPI app, routes, and UI server entry point.
- `domain` owns agent-facing behavior: tool functions and groups
  (`domain.tools`) and assistant definitions,
  assistant specs and registry (`domain.assistants`,
  `domain/assistant_specs/`), and application workflows (`domain.tasks`).
- `services` owns chat orchestration and adapts domain behavior for the HTTP layer: chat, display,
  assistant, task, and introspection services.
- `db` and `core` own the data pipeline, the upstream clients (Riot plus the
  Community Dragon catalogue client), and shared models/cache.
- `aws` owns RDS IAM/authentication helpers, security-group synchronization,
  and S3 integration.
- `common` owns repository-wide path, parsing, discovery, secret-redaction, and
  protocol helpers.
