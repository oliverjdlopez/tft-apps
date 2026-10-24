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
`domain/assistants/specs/`. Each spec pairs a `system.md` prompt with an
optional `agent.json` declaring its description, tool groups/names, and
handoffs. The `chat` assistant directly owns ranking, rolldown, context, and
evidence tools. Conditional cohort investigations can hand off to `data_analyst`,
which answers directly with its own evidence tools. Both read
`playbook:final-response` for final synthesis. The retained `final_responder`
spec is available for direct invocation and has no incoming shipped handoffs.

## Prompt context

`domain.resources` validates authored metadata, hierarchical index relationships,
and structured record views. Preparation loads a cached metadata index;
`read_resource` loads complete content by stable ID and records hashes for actual
reads. Reference sources live under `app/backend/src/domain/resources/content/references`;
portable skill packages remain under `resources/skills`.
`AssistantSpec.allows_resource` checks access for both prompt directories and
tool reads. Runtime places the repository-wide library in every context;
assistants neither load it nor construct filtered library copies.
The library supplies metadata listings and complete contents; assistant renderers
format instruction directories, and `domain.tools.context` formats read responses
and records actual reads. Runtime coordinates setup and retains invocation state.
The resource library handles storage and loading without assistant dependencies.
See [resource layout](../content_providers/resource-layout.md).

## Prompt skills

Portable `SKILL.md` packages and their supporting references use the same
validated resource library. Instructions expose permitted entry-point metadata;
`read_resource` returns the complete workflow or supporting document. Permission
checks apply to every read, including descendants. Chat cannot read skill bodies.

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
