# Assistants and Tasks

The assistant layer is defined by repository specifications and constructed as
fresh OpenAI Agents SDK graphs for each logical invocation. Assistant behavior,
tool access, handoffs, request-specific context, and synchronous task pipelines
remain separate concerns.

The public `domain.assistants` package exposes `Assistant` plus its registry,
invocation, and specification types. It does not maintain a parallel function
facade for specifications, tools, handoffs, discovery, or reloads. Named runtime
metadata comes from an `Assistant` instance (`spec`, `tool_names`,
`handoff_names`, `reachable_assistant_names`, and `reachable_tool_names`), while
`Assistant.names()` reads the lazily published live registry. SDK tool objects
remain internal to graph construction; consumers use stable tool names.
Invocation construction imports implementation dependencies directly, without
importing the package facade. `domain.assistants.utils.configure_tools(registry)`
wires isolated registries to the tool catalogue, and `AssistantRegistry` owns
handoff traversal and validation. `devtools.assistants` owns captured definitions,
prompt candidates, and instruction recording; it constructs an ordinary runtime
`Assistant` after adapting those development inputs. Token diagnostics and the
manual assistant command also live in that development package and are never
imported while building an application graph.

## Assistant specifications

Use the [assistant spec management commands](../development/assistant-specs.md)
to create, copy, or remove specs and synchronize their Langfuse prompts.
`AGENTS.md` and `README.md` are documentation, not executable assistants.

Each assistant lives under `app/backend/src/domain/assistant_specs/<name>/`:

- `system.md` contains plain Markdown instructions without frontmatter.
- `agent.json` optionally declares the name, descriptions, tool access, context
  policy, handoffs, model, reasoning, skill, and playbook overrides.
- `task.md` optionally wraps task-style input. Most assistants do not need one.

All current assistant definitions use this same layout. The `distill-transcript`
assistant keeps its source-input wrapper in `task.md` and its distillation policy
in `system.md`; names, descriptions, and access policy live in `agent.json`. The
application loader accepts only this directory format and fails the complete
registry load when a definition is malformed. The development loader retains
legacy frontmatter and field aliases for saved drafts, captures, and migration
commands without exposing those formats to live discovery.

`domain.assistants.active` discovers and publishes immutable specifications.
`Assistant.build_agent()` resolves the declared graph and constructs
fresh SDK `Agent` objects. Tool access is additive across the groups and names
declared in `agent.json`; registration alone does not grant an assistant access.
Python callers use `AssistantName` from `domain.assistants.constants` for
assistant API names; assistant specs retain their names as declarative strings.
Instruction callbacks require the typed context created by `Assistant.prepare()`;
direct SDK execution that bypasses preparation fails instead of silently omitting
request policy and resource permissions.

The streaming `/api/chat` boundary uses `chat` as its default root. API callers
can select another registered root with the `X-Chat-Assistant` header. The
header is validated before streaming, and the selected specification controls
request instructions, reachable tools, handoffs, and tracing metadata without
granting capabilities outside the registered graph.

Skill and playbook access use independent optional `skills` and `playbooks`
arrays in `agent.json`. Omission permits every discovered resource in that
category for an eligible assistant; an empty array denies the category. Each
category requires repository context or its own nonempty allowlist, and reads
require the read tool. Chat cannot read either category. Instructions expose
only permitted metadata; bodies arrive through exact `read_resource` calls.
Skills contain reusable general guidance, while playbooks contain specific task
guides. For example:

```json
{"skills": ["tft-statistical-interpretation"], "playbooks": ["specific-guide"]}
```

Captured graphs freeze both allowlists. Historical captures without
`playbook_names` deny playbook access, preserving their original capabilities.
See [skill and playbook authoring](../content_providers/skills.md).

Backend code imports this public surface through the installed `domain.assistants`
package. It must not mix that package with repository-qualified
`app.backend.src.domain.assistants` imports, because Python would initialize two
copies of the package and split registry state between them.

The direct tool set and reachable tool set are intentionally different. A
top-level assistant may reach tools only through a handoff, so UI discovery
uses `Assistant.reachable_tool_names` rather than only `Assistant.tool_names`.
The `chat` assistant directly owns context retrieval, bounded rankings,
and rolldown probability estimation. Multi-step investigations can still follow
the `chat` to `data_analyst` to `final_responder` path: the analyst runs bounded
rankings and anonymous-board cohort investigations, with `query_cohorts` kept
separate from the `deltas` group for frequency-first entity breakouts, and the
responder is the terminal user-facing synthesizer. Delta guidance keeps the
cohort as the contextual shell, distinguishes within-cohort `delta` from
same-entity-outside-cohort `relative_delta`, and treats missing comparators as
unavailable evidence. The [decision workflow design](decision-workflows.md)
explains the prompt boundaries, alternatives, and same-copy item constraints.

`final_responder` owns the `evidence` and `context` tool groups, permits only the
`tft-statistical-interpretation` skill, and has no handoffs. Its
`present_evidence` tool selects one initial static table, interactive table, or
placement distribution by reference. Analytical tools retain their usual
results and additionally register evidence when an invocation supplies an
`EvidenceStore`. Chat owns the store inside `AssistantRunContext.evidence` and
shares that context across handoffs and its tool-free maximum-turn fallback.
Legacy callers may still pass an `EvidenceStore` directly. The responder receives field metadata and
references, never an instruction to reconstruct numerical presentation data.
Other execution surfaces without an evidence store retain prose/Markdown
behavior. See [Evidence displays](../tool_groups/evidence.md).

Tool results pass through the SDK handoff history without a custom input filter,
and the shared invocation context retains registered evidence independently of
model-generated handoff text. Trace recording is observational; it does not
transport tool results or evidence. Chat's prompt handles analytical routing;
the analyst owns cohort membership and histogram retrieval guidance, while the
final responder owns display selection and presentation fallback. Neither chat
nor the analyst needs instructions to preserve references manually. Historical
evaluation snapshots remain frozen; these corrections apply to repository
prompts used by normal application runs.

## Runtime instructions

Chat, direct assistant API, CLI, transcript distillation, and captured evaluations
use `domain.assistants.Assistant` to prepare each invocation. Preparation loads a
cached, validated resource metadata without selecting prompt material or calling
models. Bodies are loaded only by reads.
`domain.assistants.resources` owns resource presentation and assistant access
checks: it renders the initial directory, filters children and links, formats
read-tool responses, and records read provenance. `domain.resources` supplies
the validated library and complete content loading without depending on
assistant or invocation state.
Each target initially receives only root reference and permitted skill and playbook
descriptions. Index reads reveal children; exact reads enforce permissions at
every level. Bodies arrive through `read_resource`
tool results. See [reference resources](../content_providers/context.md) and
[skill resources](../content_providers/skills.md).

`AssistantRunContext` holds explicit settings, resource library and frozen
permissions, actual-read ID and hash provenance, evidence, activity, and optional timing.
Each invocation receives fresh state shared across its handoffs. The SDK context
is internal; instruction callbacks and tools expose only intended fields.

`Assistant.build_agent()` installs callbacks bound to each target specification.
Callbacks render durable policy and permitted metadata on every model step;
only the root receives the caller's system prefix. Chat cannot read skills.
Read results never become instruction layers. Later registry reloads cannot
change permissions or models in an existing graph. Reusing an `Assistant`
retains definitions while creating fresh run-local state for each execution.

```python
from domain.assistants import Assistant

# Ordinary synchronous consumers; use await assistant.run(...) in async code.
assistant = Assistant("chat")
result = assistant.run_sync("Which carries are strongest?")
print(result.final_output)
```

Advanced consumers own SDK execution and transport after preparation:

```python
from agents import Runner
from domain.assistants import Assistant

invocation = await Assistant("chat", model=model, surface="chat").prepare(
    messages, system=system, request_id=request_id,
)
result = Runner.run_streamed(
    invocation.agent, input=invocation.input,
    context=invocation.context, hooks=invocation.hooks,
)
```

`prepare` accepts user text or user/assistant conversation history. The SDK
receives the root's task
wrapper applied to the latest user message, preserving previous history and
caller-owned messages. `run_sync` rejects active event loops with guidance to
await `run`. Completed or failed ordinary runs finalize unfinished activity;
streaming consumers retain cancellation and cleanup ownership.

`devtools.assistants.assistant_from_capture` verifies a captured graph, applies
optional prompt candidates to immutable specifications, and constructs a normal
runtime `Assistant`. `record_invocation` transparently records actual model-facing
instructions and model settings in a development-owned record. The runtime
`AssistantInvocation` contains only execution state.

Live assistant evaluations and Playground requests require captured graphs and use
the development adapter followed by ordinary `Assistant.prepare()`. Fresh exports capture
repository definitions for every live assistant dataset format. Historical bundles
without captures remain readable; execution rejects them before dispatch and asks
for a fresh export. Historical selector benchmarks remain available offline; their live model
execution is retired. Static instruction assembly, the `create_assistant` factory, and the
`render_assistant_input` wrapper have been removed.

Dynamic callbacks use `render_instruction_layers` to combine the stable prompt
with the target's permitted discovery catalogue. Chat sees reference metadata;
eligible specialists see permitted reference, skill, and playbook metadata. Transcript
assistants see neither. Exact reads enforce the same permissions independently
of the instructions, and return bodies only as tool results.

Fresh handoff agents retain the request's model choice, preventing an
Anthropic-backed chat request from silently switching providers during a
handoff.

Prompt candidates are applied by `devtools.assistants` before runtime construction,
retaining callbacks and access policy. Raw instruction overrides are not part of
the runtime graph API. Construction-time token diagnostics
mark dynamic instruction counts and their combined static total as unresolved
(`null`), rather than counting a callback representation. Static counts remain
unchanged.

## Execution surfaces

Callers execute assistants through `Runner.run`, `Runner.run_sync`, or
`Runner.run_streamed`. `services/chat_service.py` obtains an `AssistantInvocation` through
`Assistant.prepare`, then owns tracing, streamed execution, and the maximum-turn
fallback using the prepared context and hooks. The `Assistant` class owns
definition snapshots, resource catalogues and read permissions, task input
wrapping, invocation state, and prompt policy; tools own evidence operations.
The streaming adapter preserves the browser protocol. Direct assistant API, CLI,
captured eval, and chat-handoff paths use the same preparation and target-specific
instruction construction.

## Registered tasks

`domain.tasks` contains synchronous application workflows. The existing
`transcription_pipeline` task invokes only `distill-transcript`, passing the
original transcript or other source text and returning compact Markdown reference
notes. It performs no JSON edit application or follow-up analysis.
`services/task_service.py` preserves the task catalog and success/error envelope
over HTTP. The [transcription guide](../apps/transcription.md) documents the
source contract, CLI, and retired assistant identities.

## Validation surfaces

Structural assistant and chat behavior is covered by:

```bash
uv run pytest -q tests/test_assistant_runtime.py tests/test_assistants.py tests/test_chat_service.py tests/test_task_service.py
uv run --extra evals pytest -q tests/test_workspace_trials.py evals/langfuse/tests/test_assistant_workspace.py
uv run --extra evals chat-tft-evals validate
```

Live evals additionally require model credentials and, for data-backed cases,
an evaluation database. Langfuse owns evaluation datasets, prompt candidates,
experiment comparisons, and annotations. Captured experiments and Specs trials
adapt frozen definitions through `devtools.assistants`, then use ordinary runtime
preparation while preserving dynamic context and skill restrictions.
Historical bundles without captured execution remain readable but cannot run;
export a fresh captured bundle to execute their dataset.
Candidates never change normal conversations. Suite discovery reads the exported
local catalog and works when Langfuse is stopped. See
[Tests and evaluations](../development/testing-and-evals.md).

## Captured definitions and Specs drafts

The [assistant workspace](../development/assistant-workspace.md) separates saved
drafts from active repository behavior. `AssistantRegistry` contains immutable
runtime definitions and graph operations. `devtools.assistants` pairs registries
with source inventories, validates full graphs, and freezes model defaults.
Captured worker execution threads this isolated registry through graph building,
task wrapping, resource discovery and reads, and instruction callbacks. Typed invocation
context, per-assistant access policy, activity, and evidence handling use the normal
application pipeline. Applying a validated draft publishes a replacement live
registry for newly created assistants; existing assistant instances retain their
captured registry snapshot.
