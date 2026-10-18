# Assistant spec directories

Each assistant lives in its own directory:

```text
domain/assistants/specs/<assistant_name>/
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
  "resources": {
    "context": {"repository": true},
    "skills": [],
    "playbooks": []
  },
  "handoffs": ["other_assistant_name"]
}
```

Tool access is additive. Set `include_all` for every native TFT tool, use `groups` for registered tool groups, and use `names` for individual native tool functions. Omitted tools and handoffs mean the assistant has no access to them.

Resource access is declared under `resources`. `context.repository` permits
repository reference discovery and exact reads and defaults to false. Independent
`skills` and `playbooks` arrays restrict those categories: omission permits all
for an eligible assistant, while `[]` permits none. Access also requires the read
tool; chat cannot read skills or playbooks.

Spec loading is shared across agents, but SDK agent instances are not.
`domain.assistants.Assistant.from_name` constructs a fresh SDK subclass and
recursive handoff graph. Assistants own prompt rendering and model/tool settings;
`domain.runtime.execution` prepares invocation resources and runs the graph.
