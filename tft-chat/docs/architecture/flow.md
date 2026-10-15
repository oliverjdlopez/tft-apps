# Runtime Flow

## Chat flow

1. The browser sends messages to `/api/chat`.
2. `Assistant.prepare` builds a fresh graph, runtime context, evidence store,
   activity hooks, and permission-filtered resource metadata.
3. Instructions contain durable policy plus root resource descriptions. The
   assistant chooses index and leaf reads through `read_resource`; `domain.resources`
   owns validation, caching, exact reads, and actual-read provenance. There is no
   provider selection or selector assistant stage before generation.
4. Chat can answer direct reference questions and run bounded ranking or rolldown
   tools. Conditional cohort or multi-step questions can hand off to `data_analyst`.
5. Analytical results transfer to `final_responder`, which owns evidence displays
   and permitted resource reads. SDK history and invocation context are shared
   across handoffs; resource bodies stay in read results rather than instructions.
6. SDK events drive browser text, tool/source activity, and handoff events.

Resource IDs remain stable across file moves. Every index or leaf read checks the
active assistant's frozen access and configured set. Skills and their supporting
references inherit the same package permission; chat cannot read skill bodies.

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
