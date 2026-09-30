---
id: change-api-or-ui
title: Change API or UI
summary: Coordinate route, service, stream protocol, and Vite frontend changes.
paths:
  - "app/backend/api/**"
  - "app/backend/src/services/**"
  - "app/frontend/src/**"
task_types: [change-api, change-ui, change-streaming]
keywords: [endpoint, response, stream, frontend, tab]
requires: [docs/architecture/web-runtime.md]
last_verified: "2026-08-01"
---

# Change API or UI

## Use this workflow when

Adding/changing an endpoint, service response, startup behavior, stream event, page/view, explorer tab, or UI API call.

## Before editing

Trace route → service → domain function and the matching `apiGet`/`apiPost`/stream consumer. For chat, inspect marker parsing and SDK event conversion. For frontend changes, inspect the Vite entry, imports, and proxy/build configuration.

## Implementation sequence

1. Define typed validation at the route boundary and keep domain policy in domain/services.
2. Keep synchronous DB/SDK work off the event loop.
3. Update service output and browser consumer together; preserve credential-safe errors.
4. For streaming, change producer, shared markers, parser, and event renderer in one change.
5. For a new frontend module, use explicit imports/exports and keep the build output under `app/frontend/dist`; do not reintroduce global script ordering.
6. Add backend and frontend tests, then manually exercise affected UI behavior when a reachable app target is available.

## Validation

```bash
uv run pytest -q tests/test_chat_service.py tests/test_start_cli.py tests/test_tracing_service.py tests/test_config.py
```

Add the route/service-specific test file when the endpoint belongs to ingestion or database tooling.

## Completion checklist

- Route validation rejects unknown/sensitive fields where applicable.
- Browser and server agree on payload/event shapes.
- HTML fallback and `/api/` 404 behavior remain correct.
- Vite builds successfully and the API serves the generated asset directory.

## Common mistakes

Forgetting the Vite build prerequisite, returning an ORM object, or changing stream framing on only the server or client.
