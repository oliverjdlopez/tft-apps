# Assistant spec directories

Each assistant lives in its own directory:

```text
domain/assistant_specs/<assistant_name>/
  agent.json
  system.md
  task.md
```

`system.md` is the assistant's default system instructions. `task.md` is optional and is used by CLI/task-style assistant runs as the task wrapper before the user input.

`agent.json` is optional, but it is the preferred place for non-prompt behavior:

```json
{
  "name": "assistant_name",
  "description": "Short UI description.",
  "handoff_description": "Description used when another agent can hand off here.",
  "model": "gpt-5",
  "tools": {
    "include_all": false,
    "groups": ["ranking", "query_cohorts"]
  },
  "context": {
    "repository": true
  },
  "handoffs": ["other_assistant_name"]
}
```

Tool access is additive. Set `include_all` for every native TFT tool, use `groups` for registered tool groups, and use `names` for individual native tool functions. Omitted tools and handoffs mean the assistant has no access to them.

Context access is explicit. `repository` enables task-selected factual excerpts
and defaults to false, which keeps non-analysis assistants such as transcript
processors isolated.

Spec loading is shared across agents, but SDK agent instances are not.
`domain.assistants.factory.create_agent` constructs a fresh agent and recursive handoff
graph for each logical invocation. Per-run prompt material and model overrides
are applied during construction. The base class exposes resolved SDK tools and
retains only that invocation's run result.
