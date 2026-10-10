# Assistants and Tasks

The assistant layer is defined by repository specifications and constructed as
fresh OpenAI Agents SDK graphs for each logical invocation. Assistant behavior,
tool access, handoffs, request-specific context, and synchronous task pipelines
remain separate concerns.

## Assistant specifications

Use the [assistant spec management commands](../development/assistant-specs.md)
to create, copy, or remove specs and synchronize their Langfuse prompts.
`AGENTS.md` and `README.md` are documentation, not executable assistants.

Each assistant lives under `app/backend/src/domain/assistant_specs/<name>/`:

- `system.md` contains plain Markdown instructions without frontmatter.
- `agent.json` optionally declares the description, model and reasoning
  overrides, tool groups, individual tools, skill access, and handoffs.
- `task.md` optionally wraps task-style input. Most assistants do not need one.

All current assistant definitions use this same layout. The transcript assistants
keep their existing input instructions in `task.md`; their system instructions,
names, and descriptions no longer live in `system.md` frontmatter. The loader
retains legacy frontmatter compatibility for older saved drafts and imported
definitions, but new repository definitions should use these explicit files.

`domain.assistants.registry` discovers and caches immutable specifications.
`domain.assistants.create_assistant` resolves the declared graph and constructs
fresh SDK `Agent` objects. Tool access is additive across the groups and names
declared in `agent.json`; registration alone does not grant an assistant access.
Python callers use `AssistantName` from `domain.assistants.constants` for
assistant API names; assistant specs retain their names as declarative strings.

The streaming `/api/chat` boundary uses `chat` as its default root. API callers
can select another registered root with the `X-Chat-Assistant` header. The
header is validated before streaming, and the selected specification controls
request instructions, reachable tools, handoffs, and tracing metadata without
granting capabilities outside the registered graph.

Skill access uses the optional `skills` array in `agent.json`. When the field is
omitted, the assistant may read every discovered skill. When it is present,
only the named skills may be rendered into that assistant's instructions; an
empty array denies all skill access. Instruction assembly enforces this boundary
again for preselected skills, so a caller cannot bypass the assistant's
allowlist. For example:

```json
{"skills": ["tft-statistical-investigation"]}
```
Backend code imports this public surface through the installed `domain.assistants`
package. It must not mix that package with repository-qualified
`app.backend.src.domain.assistants` imports, because Python would initialize two
copies of the package and split registry state between them.

The direct tool set and reachable tool set are intentionally different. A
top-level assistant may reach tools only through a handoff, so UI discovery
uses `assistant_reachable_tool_names` rather than only the assistant's direct
tools. The `chat` assistant directly owns context retrieval, bounded rankings,
and rolldown probability estimation. Multi-step investigations can still follow
the `chat` to `data_analyst` to `final_responder` path: the analyst runs bounded
rankings and anonymous-board cohort investigations, with `query_cohorts` kept
separate from the `deltas` group for frequency-first entity breakouts, and the
responder is the terminal user-facing synthesizer. Delta guidance keeps the
cohort as the contextual shell, distinguishes within-cohort `delta` from
same-entity-outside-cohort `relative_delta`, and treats missing comparators as
unavailable evidence.

`final_responder` owns only the `evidence` tool group and has no handoffs. Its
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

Chat calls `domain.assistants.prepare_resources` once before execution. It uses
the latest user message for selection, or up to four recent user messages when
the latest message matches the existing follow-up heuristic. Assistant replies
remain in SDK conversation history but are not part of the selector query.
The selected references and skills are retained in `PreparedResources`.

`domain.runtime.models.AssistantRunContext` holds explicit runtime settings,
prepared resources, provider dependencies, evidence, activity, and optional
request timing. Each chat invocation receives fresh state. SDK local context is
not automatically model-visible; callbacks and tools expose only their intended
instructions and result fields. The object is not serialized into browser events
or persisted as cross-turn conversation state.

`domain.assistants.create_assistant` installs each agent's instruction callback
as part of normal construction, including every nested handoff. Each callback
captures its own immutable specification, so a later registry reload does not
change an existing graph's prompt or resource permissions. There is no separate
callback map for the chat service to build or attach.

With `AssistantRunContext`, the callbacks render prepared resources on every
model step according to that agent's repository-context and skill policies.
All handoff depths follow the same per-agent rules; contextualization no longer
depends on whether a target is directly reachable from the root. Only the root
receives the optional caller system prefix and excludes selected skill bodies.
Its callback is reused by the tool-free fallback under a different agent name.
Rendering never selects resources or loads runtime configuration.

The standard call is `create_assistant(name, model=model)`, followed by an SDK
runner call with `context=run_context`. Preparation, invocation state, lifecycle
hooks, and transport remain caller-owned. Callers without typed context receive
the specification's durable prompt without retrieval; this supports selectors,
transcript tasks, and legacy bare-evidence-store runs.

`domain.assistants.build_assistant_instructions` renders instructions for the
target assistant. It
combines the stable assistant prompt with only the request-specific layers that
target is allowed to receive:

- the top-level chat assistant receives selected factual references, but not
  selected skill bodies;
- contextualized handoff assistants receive the factual references and focused
  workflow material permitted by their spec; and
- transcript assistants receive no product context.

Fresh handoff agents retain the request's model choice, preventing an
Anthropic-backed chat request from silently switching providers during a
handoff.

Explicit `instructions` and `instructions_by_name` overrides retain precedence
over the installed default, including frozen evaluation strings and custom SDK
callbacks. Root `instructions` wins over its entry in `instructions_by_name`.
Direct/evaluation callers that already assemble explicit prompts retain that
behavior. Construction-time token diagnostics
mark dynamic instruction counts and their combined static total as unresolved
(`null`), rather than counting a callback representation. Static counts remain
unchanged.

## Execution surfaces

Callers execute assistants through `Runner.run`, `Runner.run_sync`, or
`Runner.run_streamed`. `services/chat_service.py` creates the invocation context,
prepares resources, constructs agents through the ordinary factory, supplies shared
`ActivityRunHooks`, and owns tracing and the maximum-turn fallback. The assistant
layer owns resource selection and prompt policy; tools own evidence operations;
the streaming adapter preserves the browser protocol. Direct assistant API, CLI, eval, and chat-handoff paths
all use the same registry and target-specific instruction construction.

## Registered tasks

`domain.tasks` contains synchronous, multi-step application workflows. The
transcript pipeline runs clean, applies structured edits, compacts the cleaned
text, and analyzes the result. Invalid clean-edit JSON degrades to the original
transcript rather than failing the entire pipeline. `services/task_service.py`
exposes the task catalog and response contract over HTTP.

## Validation surfaces

Structural assistant and chat behavior is covered by:

```bash
uv run pytest -q tests/test_assistants.py tests/test_chat_service.py tests/test_agent_workflow_evals.py
uv run pytest -q tests/test_runtime_instructions.py tests/test_runtime_tools.py tests/test_runtime_streaming.py
uv run --extra evals chat-tft-evals validate
```

Live evals additionally require model credentials and, for data-backed cases,
an evaluation database. Langfuse owns evaluation datasets, prompt candidates,
experiment comparisons, and annotations. Its Python service applies frozen
candidates through `instructions_by_name` and the same target-specific assembly
used by application execution, preserving dynamic context and skill restrictions.
Candidates never change normal conversations. Suite discovery reads the exported
local catalog and works when Langfuse is stopped. See
[Tests and evaluations](../development/testing-and-evals.md).

## Captured definitions and Specs drafts

The [assistant workspace](../development/assistant-workspace.md) separates saved
drafts from active repository behavior. `AssistantRegistry` can be constructed from
immutable specs, captured per invocation, and installed as a complete snapshot.
`domain/assistants/capture.py` validates full graphs and freezes model defaults.
Captured worker execution threads this isolated registry through graph building,
task wrapping, resource selectors, and instruction callbacks. Typed invocation
context, per-assistant access policy, activity, and evidence handling use the normal
application pipeline. Draft execution never substitutes the global registry.
