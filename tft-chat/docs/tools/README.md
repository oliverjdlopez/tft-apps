# Tools

`domain.tools` is the source of truth for the native OpenAI Agents SDK tools.
Assistant specs select only the groups (or standalone tools) they need;
callers should discover tool metadata from the registry instead of
maintaining a second hard-coded list.

Most tools are declared as an `AssistantToolGroup` in their owning module. A
module that exposes exactly one bounded tool and gains no clarity from a
group may instead declare an `AssistantTool` (same `key`/`label`/`description`
contract, singular `tool` field). The registry folds each `AssistantTool`
into a single-tool `AssistantToolGroup` via `AssistantTool.as_group()` before
building `_TOOL_GROUPS`, so standalone tools go through identical discovery
and resolution as grouped ones — they appear in `list_tools()`,
`get_tool(name)`, `get_tool_group_key(name)`, and the group metadata listings
the same way. Register a standalone tool by adding it to `_STANDALONE_TOOLS`
in `domain/tools/__init__.py`, the same way group constants are added to
`_TOOL_GROUPS`.

The registered groups are:

- [Evidence displays](../tool_groups/evidence.md): reference-only initial display selection.
- [Ranking](../tool_groups/ranking.md): name resolution and bounded, Pythonic
  rankings across units, items, and traits.
- [Query Cohorts](../tool_groups/query_cohorts.md): bounded cohort groupings,
  and board-cohort comparisons over anonymous final-board facts.
- [Cohort Deltas](../tool_groups/deltas.md): frequency-first unit, item, and
  trait breakouts comparing entity outcomes within and outside a cohort.
- [Rolldown probability](../tool_groups/probability.md): Monte Carlo shop odds for named champions or generic cost tiers using the current roster and shared-pool depletion.

No generic leaderboard, raw-row browser, match-store mutation, or ingestion
tool is exposed. Ingestion and query-table rebuilds remain database/CLI
responsibilities.

The final responder owns the [Evidence displays](../tool_groups/evidence.md)
group. `present_evidence` chooses a bounded initial view by backend reference;
it cannot query the database or accept copied numerical datasets.

## Runtime boundary

`domain.tools.db_tools.utils.run_db_tool` is the single database execution
boundary. A model-facing tool passes its database operation directly to this
function; there is no intermediate ranking runner or database wrapper. The
boundary moves blocking SQLAlchemy work to a worker thread, records bounded
tool diagnostics, opens a fresh session, starts a read-only PostgreSQL
transaction with a bounded statement timeout, and always rolls back and closes
the session. Caller cancellation returns a bounded retryable error while the
shielded worker finishes independently and performs that cleanup. Database SDK
tools also enforce their own bounded timeout; the implementation constants
are authoritative for current values.

Reusable tool parameters use strict bounded schemas from
`domain.tools.db_tools.models`. Lightweight `Annotated`, `Literal`, and
collection aliases used by only one purpose module stay beside that module's
tool signatures. Investigation outputs use a typed family with `kind`,
`context`, and structured `warnings`: tables add `results` and `page`,
resolutions add bounded candidate `results`, comparisons add aligned summaries
and `effects`, and failures add a structured `error`. The internal contract
identifier is not serialized. Numeric values
returned across the model-facing boundary are rounded to at most two decimal
places; internal calculations and database precision are unchanged. Entity
arguments are resolved against the active scoped store rather than interpreted
from model memory.

Structured ranking is the interface for name lookup and discovery-oriented
rankings. Ranking tools accept only scalar exact-name conditions: holder/item
bindings and simple same-board unit/trait presence. They do not expose or
compile cohort filter groups. Cohort tools own richer anonymous board-grain
conditions and comparisons; delta tools own cohort-relative entity breakouts
without returning raw match/player identifiers. Aggregate relations remain
internal and cannot be queried by an assistant.

Every ranking row includes the ordinary frequency and outcome metrics plus
`delta` and `relative_delta`, calculated by the same disjoint board-presence
pipeline used by cohort delta breakouts. An unconditioned full-scope ranking has
no outside population, so its relative delta is `null`.

Each cohort delta tool derives its effective grouping dimensions once from its
public grouping option. The same dimension list controls both the SQL result
grain and the table-result context, preventing query behavior and returned
metadata from diverging.

Database-tool implementation helpers are consolidated in
`domain.tools.db_tools.utils`. Five- or six-line section banners identify the
purpose module each group supports, rather than splitting helpers into parallel
module-named utility files. Cycle-safe SQLAlchemy, database-model, and session
dependencies are module-level imports. Result/input-model and cohort-compiler
lookups remain deferred because those modules import `utils` themselves.

Tool schemas affect several consumers beyond the registry: assistant
`agent.json` access, `/api/config`, the browser Tools tab, prompt instructions,
and eval reachability checks.

The browser tool catalogue preserves the SDK's strict `input_schema` for exact
model-facing inspection and adds an `invocation_schema` for the interactive
form. The latter restores the backend's Python/Pydantic omission semantics, so
nullable and defaulted arguments are not presented as required merely because
OpenAI strict structured outputs list every property in `required`.

## Registry entry points

- `get_tool(name)` and `get_tool_group(key)` return registered objects; this
  resolves an `AssistantTool`'s single tool the same way as any group member.
- `list_tools()` and `list_tool_groups()` return the complete registries.
- `list_tool_metadata(names=None)` and `list_tool_group_metadata(names=None)` return API-safe descriptions and schemas.
- `call_tool(name, arguments=None)` invokes one tool in process.
- `list_tool_names()` and `list_tool_group_keys()` expose the current registry.

The current registry and assistant specifications are authoritative when a
hand-written catalog differs from runtime membership.

## Focused validation

```bash
uv run pytest -q tests/test_openai_tools.py tests/test_ranking_tools.py tests/test_cohort_tools.py tests/test_cohort_facts.py tests/test_rolldown_tool.py
uv run pytest -q tests/test_assistants.py tests/test_chat_service.py
```
