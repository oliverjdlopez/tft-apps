# Agent documentation router

ChatTFT is a Python 3.13+ Teamfight Tactics analysis application: Riot and Community Dragon inputs become a normalized PostgreSQL match graph and scoped aggregate projections, which FastAPI, an unbundled React UI, and OpenAI Agents SDK assistants expose through bounded tools.

## Agentic Guidelines 

- When asked to dispatch subagents, use whatever the user requested in terms of model and reasoning effort. If not specified then 
  1. Use GPT luna 6 on high reasoning if in Codex harness
  2. Use Claude Sonnet 5.5 on medium reasoning if in Claude Code harness

## Code standards

- Use Google-style docstrings for every function and model; explain its purpose and where it is applied.
- Add targeted inline comments wherever a reviewer may struggle to follow non-obvious code. Examples include unusual initialization, loop priming, complex expressions, and multi-function pipelines; this list is not exhaustive.
- Good comments explain why the code exists or takes a particular approach, rather than merely restating it. Explaining what the code does is still useful when that context implicitly communicates the why.
- Optimize modules for intent-first reading. Readability outweighs keeping helper implementations nearby when their names already explain their behavior.
- Put data models in `models.py` unless they implement surprising, inseparable behavior.
- Keep lightweight type aliases composed only from typing constructs such as
  `Annotated`, `Literal`, and collection types in the module that uses them
  when they are used by only that one module. Reserve `models.py` for data
  models and aliases shared across module boundaries.
- Move self-explanatory implementation helpers to the single `utils.py` in their
  package, even when they are used by only one module. Never create parallel
  module-named utility files such as `query_utils.py`, `model_utils.py`, or
  `foo_utils.py` alongside it. When one `utils.py` supports several purpose
  modules, separate each module's helpers with a prominent five- or six-line
  comment banner that names the purpose module; use local imports when needed
  to keep the consolidated module free of circular imports.
- Functions left in a purpose module should be first-class operations of that module, not underscore-prefixed implementation details.

## Universal repository rules


- Preserve the raw-store → scoped-projection → bounded-tool boundary; model-facing code must not expose raw rows, player identifiers, scope IDs, or mutation paths.
- Runtime database access uses complete typed `RDS_*` targets. Full DSNs are maintenance-only; tests use an isolated database ending in `_test`.
- Do not edit `.venv/**`, `docs/reference/api/generated/**`, `data/**`, `scripts/transcription/output/**`, or eval result directories. They are dependencies or generated/runtime artifacts.
- Do not treat legacy ORM models as the write schema. `RUNTIME_MODELS` and the relational-v2 migration define current creation and cutover behavior.
- Preserve user changes and keep application behavior unchanged when editing repository documentation or agent routing.

## Load documentation

Before completing a task, first gather the related repository documentation.

1. Identify the affected paths and task type.
2. Read this file and every nested `AGENTS.md` governing those paths.
3. Use the routing tables below to select the closest subsystem documentation and workflow.
4. Initially load no more than three documentation pages unless the change clearly spans more subsystems.
5. Follow links to adjacent documentation only when the implementation crosses that boundary.
6. Inspect the current source and tests before relying on documentation; code, tests, build configuration, and CI are authoritative.
7. Avoid unrelated documentation. Report documentation mismatches rather than silently preserving stale claims.

## Subsystem routing

| Affected area | Load |
| --- | --- |
| `app/backend/api/**`, `app/backend/src/services/**`, `app/frontend/src/**`, `scripts/start.py` | [Web runtime and UI](docs/architecture/web-runtime.md) |
| `app/backend/src/domain/assistants/**`, `assistant_specs/**`, `domain/tasks/**` | [Assistants and tasks](docs/architecture/assistants-and-tasks.md) |
| `app/backend/src/domain/providers/**` | [Runtime context](docs/content_providers/context.md) and [skills](docs/content_providers/skills.md) |
| `app/backend/src/domain/tools/**` | [Model-facing tools](docs/tools/README.md) |
| `app/backend/src/db/**`, database rebuild/migration/publication scripts | [Persistence and analytics](docs/data/persistence-and-analytics.md) |
| `scripts/ingestion/**`, Riot/Community Dragon clients, `db/insert.py` | [Ingestion and upstreams](docs/data/ingestion.md) |
| `core/config.py`, `core/settings.py`, `app/backend/src/aws/**`, RDS scripts | [Configuration and infrastructure](docs/configuration.md) |
| `evals/**`, `tests/**`, `.github/workflows/ci.yml` | [Evaluations and tests](docs/development/testing-and-evals.md) |
| `scripts/transcription/**`, transcript task and prompts | [Transcription](docs/apps/transcription.md) |
| `app/backend/src/services/flowchart/**`, `app/frontend/src/flowchart/**`, `gameplans/**` | [Flowchart patch workspaces](docs/apps/flowchart.md) |
| Changes spanning raw data, projections, and tools | [Analysis data contract](docs/data/analysis.md) |

## Workflow routing

| Task | Follow |
| --- | --- |
| Add or change a model-facing tool | [Change a model-facing tool](.agent/workflows/change-model-facing-tool.md) |
| Change an assistant, prompt, handoff, or eval | [Change an assistant](.agent/workflows/change-assistant.md) |
| Change repository context or chat skills | [Change runtime context or skills](.agent/workflows/change-runtime-context-or-skill.md) |
| Change ORM schema or migrate existing data | [Change the database schema](.agent/workflows/change-database-schema.md) |
| Change Riot ingestion or normalization | [Change ingestion](.agent/workflows/change-ingestion.md) |
| Change routes, services, streaming, or browser UI | [Change API or UI](.agent/workflows/change-api-or-ui.md) |
| Add or change INI/environment/RDS settings | [Change configuration](.agent/workflows/change-configuration.md) |
| Rebuild, migrate, copy, or publish analysis data | [Operate analysis data](.agent/workflows/operate-analysis-data.md) |



## Basic validation

```bash
uv run pytest -q
```

CI runs the full pytest suite, frontend tests/build, and Langfuse snapshot validation/adapter tests, the offline fixture, and a local platform browser smoke job. There is no repository lint, format, or static-type command. Database-backed tests skip locally when `RDS_TEST_*` is absent or unreachable, while CI supplies PostgreSQL 16.

## Documentation completion requirement

Conclude every change by updating the relevant files under `docs/**` so they describe the resulting behavior and architecture. Documentation synchronization is part of the implementation, not a follow-up. Verify links, navigation, commands, and named source paths against the final code before reporting completion.
