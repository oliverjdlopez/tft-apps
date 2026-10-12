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

All current assistant definitions use this same layout. The `distill-transcript`
assistant keeps its source-input wrapper in `task.md` and its distillation policy
in `system.md`; names, descriptions, and access policy live in `agent.json`. The loader
retains legacy frontmatter compatibility for older saved drafts and imported
definitions, but new repository definitions should use these explicit files.

`domain.assistants.registry` discovers and caches immutable specifications.
`Assistant.build_agent()` resolves the declared graph and constructs
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
unavailable evidence. The [decision workflow design](decision-workflows.md)
explains the prompt boundaries, alternatives, and same-copy item constraints.

`final_responder` owns only the `evidence` tool group, permits only the
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

Chat, direct assistant API, CLI, transcript distillation, and captured evaluations use
`domain.assistants.Assistant` to prepare each invocation. The class calls
`prepare_resources` once before execution when the graph can consume selected
resources. Graphs without repository context skip factual selection. Skill
selection skips graphs without an eligible recipient: chat is never eligible;
otherwise an assistant may receive skills when it can use repository context
or explicitly names one or more skills. Skills are selected once from the
union of reachable recipients' allowlists (or the full catalog if any recipient
is unrestricted), then filtered again at each agent's instruction boundary.
This lets a directly invoked contextualized analyst receive its permitted
skills, and a no-facts assistant explicitly opt in to named skills. It uses
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

`Assistant.build_agent()` installs each agent's instruction callback
as part of normal construction, including every nested handoff. Each callback
captures its own immutable specification, so a later registry reload does not
change an existing graph's prompt or resource permissions. There is no separate
callback map for the chat service to build or attach.

With `AssistantRunContext`, the callbacks render prepared resources on every
model step according to that agent's repository-context and skill policies.
All handoff depths follow the same per-agent rules; contextualization no longer
depends on whether a target is directly reachable from the root. Only the root
receives the optional caller system prefix. Chat is excluded from skill
injection; other root assistants follow the same context and explicit-skill
eligibility rules as handoff targets. Chat's callback is reused by the tool-free
fallback under a different agent name.
Rendering never selects resources or loads runtime configuration.

The consumer entry point is `Assistant(name, model=model)`. Construction captures
an independent registry snapshot and resolved model defaults. Default context
and skill providers use that same snapshot, including selector specifications.
Reusing the instance retains definitions; each `prepare`, `run`, or `run_sync`
call creates fresh agents, resources, context, evidence, and activity hooks.
Construct a new instance to pick up subsequently applied definitions.

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

`prepare` accepts user text or user/assistant conversation history. Selectors
receive original, unwrapped user messages; the SDK receives the root's task
wrapper applied to the latest user message, preserving previous history and
caller-owned messages. `run_sync` rejects active event loops with guidance to
await `run`. Completed or failed ordinary runs finalize unfinished activity;
streaming consumers retain cancellation and cleanup ownership.

`Assistant.from_capture(graph, name)` verifies a captured graph and retains
its model defaults independently of active repository definitions. Optional
`base_instructions_by_name` replaces durable prompt text in the private snapshot
while preserving task wrappers, models, handoffs, tools, context policy, and
skill access. It also keeps selector definitions on that same snapshot.
`prepare(record=True)` retains actual model-facing instructions and model settings
in the returned `AssistantInvocation`, including evidence from failed execution.
Chat does not enable instruction recording.

Live assistant evaluations and Playground requests require captured graphs and use
`Assistant.from_capture(...).prepare(..., record=True)`. Fresh exports capture
repository definitions for every live assistant dataset format. Historical bundles
without captures remain readable; execution rejects them before dispatch and asks
for a fresh export. Selector benchmarks use `Assistant.run_sync` for their model
calls. Static instruction assembly, the `create_assistant` factory, and the
`render_assistant_input` wrapper have been removed.

Dynamic callbacks use
`render_instruction_layers` to combine the stable assistant prompt with only
request-specific layers the target is allowed to receive. Prepared invocations
also apply the root policy before rendering:

- the top-level chat assistant receives selected factual references, but not
  selected skill bodies;
- contextualized, skill-eligible assistants receive factual references and
  focused workflow material permitted by their spec, including a directly
  invoked analytical root; and
- `distill-transcript` receives no repository context or skills and has no tools
  or handoffs.

Fresh handoff agents retain the request's model choice, preventing an
Anthropic-backed chat request from silently switching providers during a
handoff.

Prompt candidates use `base_instructions_by_name`, replacing durable text while
retaining callbacks and access policy. Raw instruction overrides are no longer
part of graph construction. Construction-time token diagnostics
mark dynamic instruction counts and their combined static total as unresolved
(`null`), rather than counting a callback representation. Static counts remain
unchanged.

## Execution surfaces

Callers execute assistants through `Runner.run`, `Runner.run_sync`, or
`Runner.run_streamed`. `services/chat_service.py` obtains an `AssistantInvocation` through
`Assistant.prepare`, then owns tracing, streamed execution, and the maximum-turn
fallback using the prepared context and hooks. The `Assistant` class owns
definition snapshots, provider dependencies, resource selection, task input
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
execute through `Assistant.from_capture`
and `prepare(record=True)`, preserving dynamic context and skill restrictions.
Historical bundles without captured execution remain readable but cannot run;
export a fresh captured bundle to execute their dataset.
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
