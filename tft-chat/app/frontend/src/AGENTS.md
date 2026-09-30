# Frontend agent instructions

These rules apply under `app/frontend/src/`.

- Read `docs/architecture/web-runtime.md` and `.agent/workflows/change-api-or-ui.md`.
- This frontend is a Vite-managed ES module application. `app/frontend/index.html`
  is the entry document and `src/main.jsx` mounts the React application; every
  dependency must be imported explicitly.
- Install the locked dependencies with `npm ci`, run `npm test` for browser
  behavior, and run `npm run build` before handing work back. FastAPI serves the
  generated `app/frontend/dist` directory and does not build it at runtime.
- Keep `STREAM_EVENT_PREFIX` and `STREAM_EVENT_SUFFIX` aligned with
  `services.streaming`; update the producer and stream parser together.
- Use the existing `api`, `apiGet`, and `apiPost` helpers and preserve API error
  handling.
- Evidence views render validated resolved presentation events. Preserve the
  backend-owned values; local sorting, grouping, search, and row limits must not
  add network requests or chat-history content. Reset clears display state.
- Keep tab modules focused on their views and import shared app helpers from
  `app.jsx`; avoid reintroducing global symbols or script-order assumptions.
