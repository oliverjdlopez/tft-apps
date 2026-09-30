# Runtime Flow

## Chat flow

1. The browser sends messages to `/api/chat`.
2. The chat service passes the request to the backend chat assistant. The
   assistant runtime discovers scoped tools and asks its domain context and
   skill providers for task-relevant material.
3. The prompt includes bounded repository excerpts and the `data_analyst`
   handoff. The handoff also receives one focused skill when its metadata
   matches the latest user task.
4. The Agents SDK streams model output and handoff events back to the UI.
5. Chat answers non-statistical conversation directly and hands every data-
   backed TFT question to `data_analyst`, which owns focused ranking, cohort,
   and delta tools. After gathering evidence, the analyst hands off to the
   tool-free `final_responder` for the user-facing answer.

The assistant owns the decision to attach task context to direct runs. Markdown
discovery, parsing, local shortlisting, optional model reranking, and rendering
stay behind the `domain.providers.context.ContextProvider`
dependency; they are not assistant methods and do not require a dedicated HTTP
endpoint.

Repository skill loading and deterministic task selection likewise stay behind
`domain.providers.skills.SkillProvider`. The chat service retains
the policy for rendering selected skill instructions only into contextualized
handoffs.

## Name normalization flow

1. Ingestion loads the current Community Dragon catalogue through
   `TFTNameResolver`.
2. Unit, item, and trait identifiers are normalized before storage.
3. Analysis resolves player-language input against the names actually present
   in the scoped store with `resolve_tft_names`.

## Ingestion flow

1. A caller runs `tft-ingest`.
2. Concurrent Riot producers fetch accounts, ladders, match IDs, and match
   details into bounded queues.
3. One database writer validates and writes the normalized graph, preserving
   per-platform ordering and isolating bad matches with savepoints.
4. Each committed raw batch is followed by an idempotent scoped analytics
   batch; publication and full validation occur once during finalization.
5. Each raw payload is optionally uploaded to S3 when `CHAT_TFT_S3_UPLOAD` is on.

## Analysis flow

1. The `data_analyst` invokes the narrowest typed ranking for the requested
   lookup, ranking, exact relationship, or conditioned board context.
2. The tool opens a fresh database connection and runs the bounded query
   through the data layer.
3. Results are returned as JSON-compatible dictionaries for the analyst to
   interpret and pass to `final_responder` for terminal synthesis.

## Explorer flow

The Data pages expose ordinary FastAPI endpoints for models, tables, native
tool schemas, and raw upstream API calls.
