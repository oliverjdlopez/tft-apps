# Assistant-spec agent instructions

These rules apply under `app/backend/src/domain/assistant_specs/`.

- Read `docs/architecture/assistants-and-tasks.md` and `.agent/workflows/change-assistant.md`.
- Put durable language policy in `system.md`; put tool groups/names, handoffs, description, model, and reasoning settings in `agent.json`; add `task.md` only when task-style wrapping is real behavior.
- Tool/handoff names must resolve through the registries. Preserve the intended direct-versus-reachable distinction.
- Do not inject private analyst schema or selected TFT skill bodies into the top-level chat prompt.
- Update structural tests and the relevant eval manifest with behavior changes. Run `uv run python -m evals --validate` before any live eval.
- Do not create empty prompt, task, or eval templates.
