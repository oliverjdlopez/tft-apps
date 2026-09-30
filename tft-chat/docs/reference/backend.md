# Backend Reference

The backend lives under `app/backend`. Its main job is to provide native
OpenAI SDK tools over the local TFT match store and orchestrate the chat and
analysis assistants.

## Tool Registration

`domain.tools` is the canonical registry. Tool modules register async functions
with the official OpenAI Agents SDK `function_tool` decorator. The package
exposes direct `get_*` and `list_*` registry functions and invokes tools
in-process through `ToolContext`. Assistant construction resolves spec-declared
tool names and groups into SDK tool objects.

Tool modules are grouped by responsibility:

- `domain.tools.db_tools.ranking_tools` — typed name resolution plus entity,
  loadout, and relationship rankings
- `domain.tools.db_tools.cohort_tools` — grouped cohort queries and board-level
  cohort comparisons
- `domain.tools.db_tools.deltas` — cohort-relative unit, item, and trait delta
  breakouts

## Assistants

`domain.assistants` builds OpenAI Agents SDK agents from spec directories under
`domain/assistant_specs/`. Each spec pairs a `system.md` prompt with an
optional `agent.json` declaring its description, tool groups/names, and
handoffs. The `chat` assistant has no direct data tools and hands every
statistical question to `data_analyst`, which owns typed rankings, cohort
investigations, and bounded context tools. The analyst then hands verified
evidence to the tool-free `final_responder` for the terminal user-facing
response.

## Prompt context

`domain.providers.context` owns the repository Markdown models and
the injectable `ContextProvider`, while the raw documents live under
`domain/resources/context`. Selection uses a bounded local shortlist followed
by optional model reranking, then enforces excerpt-count and character budgets
before rendering the same reference block for chat and its contextualized
handoff agents. See the [context provider guide](../content_providers/context.md)
for metadata, ranking, selector input, fallback behavior, and evaluation.

The chat service selects bounded repository excerpts for chat and its
contextualized analyst handoff. The analyst's spec excludes the private schema
pack and relies on typed tools as the model-facing data boundary; no dedicated
context endpoint is required.

## Prompt skills

`domain.providers.skills` owns the `SkillDefinition` model and
injectable `SkillProvider`. The raw skill files live under
`domain/resources/skills`; the repository provider discovers them and deterministically
selects one focused playbook from the latest user task. The chat service builds
these selections into its backend-owned integration context and injects skill instructions
only into contextualized handoffs, not the top-level chat assistant or frontend
configuration.

## Shared clients

`core.chat_tft_riot` wraps the [pulsefire](https://pulsefire.iann838.com/) SDK's
`RiotAPIClient` for ingestion, preserving ChatTFT's method names, error
contract, and adaptive rate limiting. `core.cdragon` supplies catalogue data
for name normalization. Region/platform validation stays in `core.routing`.

## Data and models

`core.chat_tft_riot` and `core.cdragon` keep upstream API concerns out of tool
code. `db` owns match storage (Postgres on RDS), ingestion, and query helpers.
`aws` holds the boto3 factories for RDS IAM auth and S3 upload. `core.models`
contains only the Riot match and Community Dragon payload slices the runtime
consumes.

See [Assistants and Tasks](../architecture/assistants-and-tasks.md),
[Persistence and Analytics](../data/persistence-and-analytics.md), and
[Ingestion and Upstreams](../data/ingestion.md) for the detailed subsystem
boundaries.

## Adding a tool

Add an async function with typed parameters, a typed return value, and a
docstring to the appropriate `domain.tools` module, then include it in that
module's `ToolGroup`.
