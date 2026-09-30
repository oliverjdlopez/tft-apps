---
id: change-assistant
title: Change an assistant
summary: Change assistant specs, prompts, tools, handoffs, and regression evals together.
paths:
  - "app/backend/src/domain/assistants/**"
  - "app/backend/src/domain/assistant_specs/**"
  - "evals/langfuse/**"
task_types: [add-assistant, change-prompt, change-handoff, prompt-tuning]
keywords: [assistant, system.md, agent.json, handoff, eval]
requires: [docs/architecture/assistants-and-tasks.md]
last_verified: "2026-09-13"
---

# Change an assistant

## Use this workflow when

Adding an assistant or changing prompt policy, model settings, tool access, handoffs, chat context injection, or assistant eval expectations.

## Before editing

Inspect the target `system.md`, optional `agent.json`/`task.md`, registry construction, callers, structural tests, and its Langfuse dataset plus exported snapshot. Map both direct and reachable tools.

## Implementation sequence

1. Put stable behavior in `system.md`; put tools/handoffs/model/reasoning in `agent.json`.
2. Use SDK `Agent`, `Runner`, run input, and dynamic instructions directly; add a local helper only for repeated application-specific assembly.
3. Construct fresh agents with chat request-specific instructions. Preserve request-model propagation across fresh handoffs.
4. Update graph-sensitive tests and the suite's cases/check parameters in Langfuse, then export a snapshot through the dataset's Custom Experiment `export` action. Keep deterministic evaluator implementations in Python. For a new assistant, add a meaningful suite only if there is behavior to evaluate—do not add empty templates.
5. Validate manifests before any live run. Run a narrow live suite only when credentials/data are available and the task warrants token spend.

## Required repository patterns

- Top-level chat does not receive private analyst schema or skill bodies.
- `data_analyst` hands off to `final_responder`. Graph changes require prompt, registry, UI discovery, validation, and eval updates together.
- Every invocation uses explicit target-specific instruction text. Keep repository/schema eligibility in `agent.json`; top-level chat still excludes private schema and skills.

## Validation

```bash
uv run pytest -q tests/test_assistants.py tests/test_chat_service.py tests/test_agent_workflow_evals.py tests/test_context_service.py tests/test_skill_provider.py
uv run --extra evals chat-tft-evals validate
```

Optional live check:

```bash
uv run --extra evals chat-tft-evals run --suite <assistant>
```

For prompt experiments, edit a versioned Langfuse prompt and select its version in
the dataset Custom Experiment configuration. Set `repetitions` to run separate
experiments for comparison. These candidates affect evaluations only; promoting
a candidate to normal application behavior requires editing the repository spec.

## Completion checklist

- Spec discovery, direct tools, reachable tools, handoffs, and model settings are intentional.
- Prompt change has deterministic regression coverage and manifest validation.
- Every logical invocation owns a fresh SDK agent and handoff graph.
- Live results and annotations stay in Langfuse; exported definitions stay in Git snapshots.
- UI-authored changes have a reviewed snapshot, and normal assistant behavior remains independent of Langfuse.

## Common mistakes

Encoding graph behavior only in prose, changing prompts without eval constraints, or testing a stochastic prompt with a single run and treating it as definitive.
