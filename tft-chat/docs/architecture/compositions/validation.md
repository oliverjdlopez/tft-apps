# Composition validation

HDBSCAN tests cover density discovery, native noise and persistence diagnostics,
portable saved models, versioned classification behavior, CPU fallback, optional
CUDA fitting, and rejection of retired algorithm IDs. Persistence tests use isolated
SQLite fixtures; PostgreSQL integration uses only a guarded `RDS_TEST_*` database
ending in `_test` and real worker processes. Source-capture tests confirm anonymous
keys never escape and source analytics remain unchanged.

Run focused coverage with:

```sh
uv run --extra compositions pytest -q tests/compositions
```

Set `RDS_TEST_*` to a disposable `_test` target to include PostgreSQL worker
integration. Optional GPU fitting and classifier checks require the GPU extra and
explicit opt-in flags; see the [HDBSCAN guide](hdbscan.md#validation-and-limits).

## Native UI checks

`desktop/tests/workspace-electron.mjs` checks the real Electron shell, configurable
Compositions visibility, retained view state, sandbox isolation, and renderer
cleanup. `desktop/tests/compositions-electron.mjs` exercises the production
Compositions page with an isolated test database and verifies family browsing,
HDBSCAN diagnostics, and saved history after reload.

For that page smoke, build the frontend and configure `RDS_TEST_*`, then run in
separate terminals:

```sh
uv run --extra compositions uvicorn tests.compositions.smoke_app:app --host 127.0.0.1 --port 58341
cd desktop
npx --no-install electron tests/compositions-electron.mjs
```

The test-only ASGI entrypoint uses the guarded test database, never the application
target. It enables the composition gate only in its own process. Do not run
database-resetting pytest cases concurrently against that same isolated database.

`scripts/export_composition_contracts.py` regenerates shared JSON schemas and
valid/invalid fixtures consumed by the Pydantic and Zod tests.
