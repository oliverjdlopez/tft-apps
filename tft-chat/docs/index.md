# TFT intelligence, documented.

<div class="docs-hero">
  <p class="docs-kicker">ChatTFT engineering guide</p>
  <p class="docs-lede">Follow the complete path from Riot match ingestion to scoped PostgreSQL analytics, bounded model tools, and streamed assistant answers.</p>
  <div class="docs-actions">
    <a class="docs-button docs-button-primary" href="architecture/flow.html">Explore the architecture <span aria-hidden="true">→</span></a>
    <a class="docs-button docs-button-secondary" href="reference/api/index.html">Browse the API reference</a>
  </div>
  <div class="docs-signal-row" aria-label="Technology overview">
    <span><strong>Sources</strong> Riot + Community Dragon</span>
    <span><strong>Core</strong> PostgreSQL + FastAPI</span>
    <span><strong>Interface</strong> React + Agents SDK</span>
  </div>
</div>

## Start with the system

The guides below cover the runtime by responsibility. Architecture explains
how the pieces communicate; the remaining sections document each boundary in
enough detail to operate or extend it.

```{toctree}
:maxdepth: 2
:caption: Architecture

architecture/flow
architecture/web-runtime
architecture/compositions/index
architecture/assistants-and-tasks
```

```{toctree}
:maxdepth: 2
:caption: Data

data/storage
data/analysis
data/ingestion
data/persistence-and-analytics
data/relational-v2-migration
data/new-db-models
data/old-vs-new-db-models
```

```{toctree}
:maxdepth: 2
:caption: Configuration and infrastructure

configuration
aws-integrations
```

```{toctree}
:maxdepth: 2
:caption: Tools

tools/README
tool_groups/query_cohorts
tool_groups/deltas
tool_groups/evidence
tool_groups/ranking
tool_groups/probability
```

```{toctree}
:maxdepth: 2
:caption: Content providers

content_providers/context
content_providers/skills
```

```{toctree}
:maxdepth: 2
:caption: Reference

reference/backend
reference/modules
reference/api/index
```

```{toctree}
:maxdepth: 2
:caption: Apps

apps/cli-and-ui
apps/desktop
apps/flowchart
apps/transcription
```

```{toctree}
:maxdepth: 2
:caption: Development

development/testing-and-evals
development/langfuse-onboarding
development/langfuse-local
development/langfuse-content
development/langfuse-execution
development/langfuse-validation
```
