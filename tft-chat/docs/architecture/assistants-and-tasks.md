# Assistants and Tasks

`Assistant` subclasses the OpenAI Agents SDK `Agent`. It bundles a ChatTFT
specification with prompt rendering, model settings, tools, and handoffs.
`domain.runtime.execution` gathers invocation context and owns Runner calls,
activity finalization, and streamed execution cleanup.

## Agent construction

`Assistant.from_name(name, registry=..., model=..., output_type=...)` constructs
a fresh graph from one validated registry snapshot. An explicit model override
applies to every handoff; output type applies only to the root. The explicit
`ASSISTANT_CLASSES` mapping selects `ChatAssistant` for `chat`, including when
chat is a handoff. Other names use `Assistant`. `Assistant.from_spec(spec, ...)`
constructs an explicit node with tools and matching handoffs supplied by its caller.

The assistant is directly usable by the SDK. Its `tools`, `handoffs`, `model`,
`model_settings`, and `instructions` are SDK fields; `spec` retains the immutable
ChatTFT definition. There is no `.agent` wrapper or assistant execution method.
Construction does not load the resource library or create request state.

`render_instructions(wrapper, agent)` is the subclass customization point. The
constructor binds it to the SDK's `instructions` field. Renderers consume the
provided `AssistantRunContext` and never gather context themselves. The default
renderer displays **Available resources**; chat displays **Available TFT
references**. Both expose permitted metadata, not resource bodies.

The subclass preserves SDK dataclass initialization and validation. `clone()`
retains spec metadata and SDK shallow-copy semantics, rebinding the default
renderer to the copy unless instructions are explicitly overridden. A renamed
fallback still renders with its specification's identity and root-only prefix.

The source responsibilities are:

- `assistant.py`: the SDK subclass, spec/name construction, and default rendering.
- `chat.py`: chat-specific rendering; the package installs its explicit mapping.
- `models.py` and `utils.py`: immutable specifications, file loading, and tool resolution.
- `registry.py`: validated definitions, direct/reachable tool metadata, and handoff graphs.
- `domain.resources.library`: catalogue construction, metadata listings, and complete reads.
- `domain.assistants.utils.select_resource_catalogues`: spec-based resource exposure.
  Assistants format their selected catalogue metadata into prompts.
- `domain.tools.context`: read-tool responses and actual-read recording.
- `domain.runtime`: context gathering, input assembly, execution, and activity lifecycle.

Registries expose frozen specs and read-only lookup tables. Discovery reads these
without constructing agents. Registry construction rejects unknown tools,
missing handoffs, and cycles. Each graph receives independent SDK tool lists.
Repository loading stays lazy so startup can recover the Specs workspace journal
before reading definitions. The tool catalogue loads when the registry resolves
declared tools.

The runtime registry reference is published by
`devtools.assistants.workspace.workspace.DefinitionsPublisher` after validation.
Publication affects new graphs; existing agents retain their specs and configuration.
Development adapters own captures, candidates, recording, diagnostics, and frozen
model choices. The live assistant package never imports development code.

## Assistant specifications

Use the [assistant spec management commands](../development/assistant-specs.md)
to create, copy, or remove specs and synchronize their Langfuse prompts.
`AGENTS.md` and `README.md` are documentation, not executable assistants.

Each assistant lives under `app/backend/src/domain/assistant_specs/<name>/`:

- `system.md` contains plain Markdown instructions without frontmatter.
- `agent.json` optionally declares the name, descriptions, tool access, handoffs,
  model, and reasoning. Its `resources` object groups context, skill, and playbook policy.
- `task.md` optionally wraps task-style input. Most assistants do not need one.

All current assistant definitions use this same layout. The `distill-transcript`
assistant keeps its source-input wrapper in `task.md` and its distillation policy
in `system.md`; names, descriptions, and access policy live in `agent.json`. The
application loader accepts this directory format and passes values to the model.
`AssistantSpec.validate_invariants()` enforces nonempty assistant names, text
fields, boolean permissions, name sequences, and model/reasoning enums.
It freezes name lists as tuples and removes duplicates in declaration order;
omitted and empty permission lists remain distinct. Empty descriptions and prompt
text are valid, including explicitly cleared experimental instructions. These invariants also apply to direct construction, `dataclasses.replace`,
and captured definitions. Registry construction separately checks tool references
and handoff graphs. The loader has no field-validation helper chain or parallel
key allowlist; remaining JSON fields are checked by the model constructor's
signature. The nested `resources` and `resources.context` objects reject unknown keys;
tool objects are read for their supported fields, and
Markdown is read as instruction text without frontmatter interpretation.
The development loader retains
legacy frontmatter and field aliases for saved drafts, captures, and migration
commands without exposing those formats to live discovery. Historical flat resource
fields are supported only by that development loader; combining them with
`resources` is rejected to avoid ambiguous permissions.

`domain.assistants.registry` loads immutable specifications for runtime use.
Registry construction rejects missing tools, handoff targets, and cycles.
`Assistant.from_name(...)` constructs the selected SDK subclass and its handoffs
before execution. Every graph node owns its class-specific rendering behavior. Tool access is additive across the groups and names
declared in `agent.json`; registration alone does not grant an assistant access.
Python callers use `AssistantName` from `domain.assistants.constants` for
assistant API names; assistant specs retain their names as declarative strings.
Instruction callbacks require `AssistantRunContext` supplied through the SDK
runner's `context` argument. Direct SDK consumers construct it explicitly;
missing application context fails instead of silently omitting request policy
and resource permissions.

The streaming `/api/chat` boundary uses `chat` as its default root. API callers
can select another registered root with the `X-Chat-Assistant` header. The
header is validated before streaming, and the selected specification controls
request instructions, reachable tools, handoffs, and tracing metadata without
granting capabilities outside the registered graph.

All prepared-resource configuration lives under `resources` in `agent.json`.
`resources.context.repository` enables repository reference access and defaults
to false. Skill and playbook access use independent optional `resources.skills`
and `resources.playbooks` arrays. Omission permits every discovered resource in that
category for an eligible assistant; an empty array denies the category. Each
category requires repository context or its own nonempty allowlist, and reads
require the read tool. The shipped chat spec declares empty lists for both categories;
there is no hardcoded assistant-name restriction. Instructions expose
only permitted metadata; bodies arrive through exact `read_resource` calls.
Skills contain reusable general guidance, while playbooks contain specific task
guides. For example:

```json
{
  "resources": {
    "context": {"repository": true},
    "skills": ["tft-statistical-interpretation"],
    "playbooks": ["specific-guide"]
  }
}
```

Omitting `resources` is equivalent to an empty object; it does not enable
repository context. Tools and handoffs remain separate top-level settings.
The loaders map this object to `AssistantSpec.repository_context`, `skill_names`,
and `playbook_names`; assistant configuration uses those validated fields to select
catalogues when runtime coordinates invocation setup.

Version 2 captured graphs freeze spec-owned exposure, including both allowlists.
The development replay adapter preserves the implicit chat workflow restriction
for version 1 graphs. Historical captures without `playbook_names` deny playbook
access, preserving their original capabilities.
See [skill and playbook authoring](../content_providers/skills.md).

Backend code imports this public surface through the installed `domain.assistants`
package. It must not mix that package with repository-qualified
`app.backend.src.domain.assistants` imports, because Python would initialize two
copies of the package and split registry state between them.

The direct tool set and reachable tool set are intentionally different. A
top-level assistant may reach tools only through a handoff, so UI discovery
uses the registry's `reachable_tool_names[name]` rather than only
`tool_names[name]`. Chat retains one registry reference for both graph
construction and request metadata, so a reload cannot mix definitions within a
request.
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
`EvidenceStore`. Runtime creates the store inside `AssistantRunContext.evidence`;
chat shares that context across handoffs and its tool-free maximum-turn fallback.
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

## Runtime context and execution

All execution surfaces use `domain.runtime.execution`:

- `create_context(assistant, ...)` gathers the reachable graph's resource catalogue
  and access permissions, and creates fresh evidence, activity, and read provenance.
- `run(assistant, input, ...)` and `run_sync(assistant, input, ...)` prepare context
  when omitted, apply the root task wrapper, and call the matching SDK Runner API.
- `run_streamed(assistant, input, ...)` is an async context manager yielding the
  SDK streaming result. `stream_events(result)` consumes its unmodified events and
  cancels SDK work before closing an interrupted iterator.

Context options include set number, surface, request ID, system prefix, and timing.
They belong to runtime, never assistant construction. A prepared context can be
supplied for recording or multiple execution attempts; callers cannot also pass
context-creation options. Async entry points gather resources in a worker thread.
The synchronous entry point preserves SDK event-loop behavior and rejects use
inside an active event loop.

Each invocation owns fresh mutable state. Its handoffs share that context and its
resource permissions. The library supplies cached metadata; preparing another
invocation recomputes permissions and starts with empty reads and activity.
`domain.assistants.utils.select_resource_catalogues` interprets spec exposure
and selects applicable references for the requested set. Runtime retains the
returned catalogues in `PreparedResources.catalogues`, alongside a fresh read
record; it owns no resource selection or response-formatting implementation.
Each catalogue shares the library's body cache. Assistant renderers use the
library's metadata listing; the read tool loads content and formats its response.
`domain.resources` has no assistant, spec, or invocation dependencies.
Resource flags do not grant missing tools. Skills and playbooks retain separate
allowlists. Reads require membership in the supplied catalogue even when another
assistant has already cached the body. Children and links stay within that catalogue.
`domain.resources` owns library loading and content without depending on assistants.

Runtime input assembly copies supported conversation messages and applies
`task.md` only to the latest user message. It never modifies caller history.
`input_prepared=True` on streamed execution preserves already assembled SDK
items, including tool replay during fallback, without wrapping input twice.

```python
from domain.assistants import Assistant
from domain.runtime.execution import run_sync

assistant = Assistant.from_name("chat")
result = run_sync(assistant, "Which carries are strongest?", surface="api")
print(result.final_output)
```

Streaming consumers close the event iterator before leaving the runtime context:

```python
from contextlib import aclosing
from domain.runtime.execution import run_streamed, stream_events

async with run_streamed(assistant, "Which carries are strongest?", surface="chat") as result:
    async with aclosing(stream_events(result)) as events:
        async for event in events:
            ...  # Translate the SDK event for this transport.
```

Runtime finalizes activity on success, failure, cancellation, and early stream
closure. Cancellation precedes closing the SDK iterator because closing alone can
wait for an unfinished model call. Services retain HTTP/browser formatting and
surface-specific tracing. Chat also owns the maximum-turn fallback policy: it
clones the root without tools or handoffs, reuses the original context/evidence,
and executes the prepared continuation through runtime.

API, CLI, transcription, chat, Specs trials, and captured evaluations all use this
boundary. Evaluation adapters first validate captures and replace candidate
prompts, then construct ordinary assistants. They attach instruction recording and
retain failure provenance while runtime owns execution cleanup. Captured model
identifiers are applied by the development adapter, with an explicit request model
still taking precedence across all handoffs.

To customize an assistant, subclass `Assistant`, override `render_instructions`,
and add its explicit name-to-class mapping. SDK model/tool/output fields remain
available for ordinary customization. Prompt content and default configuration
remain readable through repository specs; runtime configuration is invocation-local.

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
uv run pytest -q tests/test_runtime_execution.py tests/test_assistant_runtime.py tests/test_assistants.py tests/test_chat_service.py tests/test_task_service.py
uv run --extra evals pytest -q tests/test_workspace_trials.py evals/langfuse/tests/test_assistant_workspace.py
uv run --extra evals chat-tft-evals validate
```

Live evals additionally require model credentials and, for data-backed cases,
an evaluation database. Langfuse owns evaluation datasets, prompt candidates,
experiment comparisons, and annotations. Captured experiments and Specs trials
adapt frozen definitions through `devtools.assistants`, then execute through runtime
with application context and the same resource restrictions.
Historical bundles without captured execution remain readable but cannot run;
export a fresh captured bundle to execute their dataset.
Candidates never change normal conversations. Suite discovery reads the exported
local catalog and works when Langfuse is stopped. See
[Tests and evaluations](../development/testing-and-evals.md).

## Captured definitions and Specs drafts

The [assistant workspace](../development/assistant-workspace.md) separates saved
drafts from active repository behavior. `AssistantRegistry` contains immutable
runtime definitions and precomputed graph metadata. `devtools.assistants` pairs
validated registries with source inventories, freezes model defaults, and owns
publication to the live runtime.
Captured worker execution builds a graph from its isolated registry. Runtime
uses that graph for task wrapping and resource permissions; callbacks retain its specs. Typed invocation
context, per-assistant access policy, activity, and evidence handling use the normal
application pipeline. Applying a validated draft publishes a replacement live
registry for newly created assistants; existing assistant instances retain their
constructed graph and captured specifications.
