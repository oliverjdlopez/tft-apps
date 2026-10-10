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

- `system.md` contains durable language and behavior policy.
- `agent.json` optionally declares the description, model and reasoning
  overrides, tool groups, individual tools, skill access, and handoffs.
- `task.md` optionally wraps task-style input. Most assistants do not need one.

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

`unit_expert` is also a terminal assistant. Its spec directly grants `ranking`,
`query_cohorts`, and `evidence`, with no handoffs. A normal `/api/chat` request
selecting `X-Chat-Assistant: unit_expert` therefore uses the ordinary factory,
shared invocation evidence store, and existing presentation stream. It can
display its own ranking rows, grouped cohort rows, or target/baseline summary
without delegating to another assistant. The default `chat` root continues to
use its analyst/responder graph.

The unit expert answers the requested comparison rather than forcing a
three-or-four-unit composition report. It checks exact builds before expanding
to board context, uses item investment as a disclosed role proxy, and checks
loadout coverage before generalizing AP/AD marker items. Its durable prompt
contains these rules because root agents do not receive selected skill bodies.
The analyst and selected statistical/itemization skills use the same focused
investigation and stopping policy. The unit expert, final responder, and chat
lead with the answer, use compact evidence where useful, and end without a
mandatory repeated conclusion or generic disclaimer. See the
[annotated review follow-through](../development/unit-expert-review.md).

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

Use `AssistantName` members from `domain.assistants.constants` for built-in
assistant identifiers in Python, including tests, handoff assertions, and prompt
keys. The browser uses the matching frozen `AssistantName` mapping in
`app/frontend/src/assistant-names.js`; a Python regression checks both mappings.
The enum also names the fixture assistant and chat's synthetic final-response
agent. JSON specs, saved snapshots, and API payloads still serialize the string
values. Dynamically discovered or user-created assistant names remain supported;
the enum is not a restriction on the registry's catalogue. UI tabs and INI
sections named `chat` are separate identifiers.

`domain.assistants.create_assistant` constructs `AssistantAgent`, an SDK
`Agent[AssistantRunContext]` subclass, at every node of the handoff graph. Each
instance owns an immutable `AssistantSpec` snapshot, its `is_root` role, and
default context and skill providers. Optional `context_provider` and
`skill_provider` factory arguments set defaults throughout the graph; otherwise
the subclass uses the repository providers. Later registry reloads do not change
an existing graph's specification.

The exported factory assembles a whole registered graph: it configures tool
resolution, loads specifications, rejects handoff cycles, propagates caller
overrides, and records graph diagnostics. Direct `AssistantAgent(...)`
construction initializes one node from already-resolved inputs. Its constructor
does not discover tools or rebuild handoffs, which also lets SDK `clone()` retain
or replace the supplied graph without repeating registry assembly.

`AssistantRunContext` holds explicit runtime settings, prepared resources,
optional provider overrides, evidence, activity, and request timing. Context and
skill providers resolve independently: a non-`None` invocation override wins,
otherwise the executing agent's default applies. Overrides never mutate agent
defaults. Mutable resources, evidence, and activity remain invocation-local;
provider objects are shared dependencies, not request-state containers.

Chat constructs its root and calls `await agent.prepare_resources(messages,
run_context)` once before execution. This method uses the resolved providers,
stores `PreparedResources` on the context, and returns that snapshot for browser
events and trace metadata. It uses the latest user message for selection, or up
to four recent user messages when the latest matches the follow-up heuristic.
Assistant replies remain in SDK history but are excluded from the selector query.
The standalone `domain.assistants.prepare_resources` operation remains available
for callers explicitly managing preparation dependencies.

By default, the subclass installs a shared SDK `instructions` callback that calls
`agent.render_instructions(context)` on the executing instance. Each model step
renders the shared selections under that agent's repository-context and skill
permissions. Rendering performs no selection or configuration loading. Only the
root receives the caller system prefix and excludes selected skill bodies.
Callers without typed context receive the durable prompt without retrieval.
Explicit instruction strings and callbacks bypass the default renderer.

The callback captures neither an agent nor invocation state, so SDK clones use
their own specification and providers. Chat's maximum-turn fallback clones the
root with empty tools and handoffs, retaining its subclass, root role, model,
instructions, and provider defaults while sharing the original invocation.

The standard call sequence is:

```python
agent = create_assistant(name, model=model)
context = AssistantRunContext(runtime=runtime, evidence=evidence_store)
await agent.prepare_resources(messages, context)
result = Runner.run_streamed(agent, input=messages, context=context)
```

For a request-specific provider, pass `context_provider=custom_provider` or
`skill_provider=custom_provider` to `AssistantRunContext`. Initial selection is
shared across the graph; per-agent defaults do not trigger handoff reselection.
`request_additional_context` resolves the executing agent's factual provider with
the same override precedence and returns additional references as tool output.
It does not replace the initial resources. SDK local context is not automatically
model-visible, serialized into browser events, or persisted between chat turns.

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
constructs agents through the ordinary factory, prepares resources through the
root, supplies shared `ActivityRunHooks`, and owns tracing and the maximum-turn
fallback. The assistant
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
uv run pytest -q tests/test_runtime_instructions.py tests/test_openai_tools.py tests/test_evidence.py
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
