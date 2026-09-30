# Documentation

Docs are grouped by the part of the system they describe.

## Architecture

- [Runtime flow](architecture/flow.md): how chat, analysis, ingestion, and explorer requests move through the codebase.
- [Web runtime and browser UI](architecture/web-runtime.md): FastAPI lifecycle, Vite assets, streaming protocol, Markdown chat, and degraded startup.
- [Assistants and tasks](architecture/assistants-and-tasks.md): assistant specs, graph construction, runtime instruction layers, and registered workflows.

## Data

- [Storage](data/storage.md): RDS Postgres storage, ingestion, S3 upload, and query-table behavior.
- [Analysis](data/analysis.md): match-store scope, metrics, and statistical caveats.
- [Ingestion and upstreams](data/ingestion.md): Riot producers, the single database writer, normalization, and analytics finalization.
- [Persistence and analytics](data/persistence-and-analytics.md): runtime schema, scope lifecycle, locks, rebuilds, and maintenance boundaries.
- [Relational v2 migration](data/relational-v2-migration.md): maintenance-window preflight, cutover, validation, and rollback retention.
- [Database models](data/new-db-models.md): current normalized, anonymous-fact, aggregate, compatibility, and runtime model inventory.
- [Old versus new models](data/old-vs-new-db-models.md): migration-era design reference retained for historical context.

## Configuration and infrastructure

- [Configuration](configuration.md): INI behavior, environment-owned secrets, and typed database targets.
- [AWS integrations](aws-integrations.md): RDS authentication, ingress synchronization, patch publication, and S3.

## Tools

- [Tool registry](tools/README.md): registry entry points and the canonical tool groups.
- [Ranking tools](tool_groups/ranking.md): the Pythonic default for name
  resolution, rankings, ranges, loadouts, and aggregate relationships.
- [Query Cohorts](tool_groups/query_cohorts.md): bounded grouped cohort queries
  and board-cohort comparisons.
- [Cohort Deltas](tool_groups/deltas.md): frequency-first entity breakouts
  within and outside anonymous-board cohorts.

- [Evidence displays](tool_groups/evidence.md): backend-owned evidence, reference-only display selection, and local controls.

## Content providers

- [Context provider](content_providers/context.md): context metadata, chunking,
  local shortlisting, model reranking, prompt budgets, and evaluation.
- [Skill provider](content_providers/skills.md): protocol-compatible skill
  descriptions, selection, fallback ranking, and whole-workflow injection.

## Reference

- [Backend reference](reference/backend.md): native SDK tools, assistants, data layer, and models.
- [Modules](reference/modules.md): backend package ownership and doc map.

- [Shared UI conventions](development/shared-ui.md): canonical shadcn theme, local component ownership, and propagation between independent builds.

## Apps

- [CLI and UI](apps/cli-and-ui.md): local UI and CLI entry points.
- [Electron desktop](apps/desktop.md): native checkout launch, automatic backend startup, and frontend hot reload.
- [Flowchart](apps/flowchart.md): player-authored patch gameplan workspaces in the desktop Flowchart tab.
- [Transcription](apps/transcription.md): media download/transcription and the transcript assistant pipeline.

## Development

- [Tests and evaluations](development/testing-and-evals.md): the CI gate, PostgreSQL fixture isolation, Langfuse datasets, snapshots, and model/prompt experiments.
- [Local Langfuse deployment](development/langfuse-local.md): Docker startup, login, credentials, persistence, and backup.
- [Langfuse content](development/langfuse-content.md): editable datasets/prompts and versioned Git snapshots.
- [Assistant spec management](development/assistant-specs.md): terminal creation, dependency-checked removal, and Langfuse prompt synchronization.
- [Langfuse execution](development/langfuse-execution.md): agent execution, trace evidence, and grading.
