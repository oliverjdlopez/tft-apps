# tft-apps agent documentation router

The user entry point is `desktop/`. ChatTFT and VOD retain separate dependency
environments, application layouts and process lifetimes. VOD Review and Wisps
are two persistent views of one VOD frontend/backend pair.

Read [suite architecture and setup](docs/desktop.md) before launcher changes.
For `tft-chat/**`, read [ChatTFT instructions](tft-chat/AGENTS.md) and applicable
nested instructions; resolve their app-relative paths under `tft-chat/`.
For `vod-review/**`, read [VOD guide](vod-review/README.md).
For evaluations, also read [migration contract](docs/migration.md).

Keep credentials, bulk datasets, dependency installs, runtime databases, media,
caches and evaluation results ignored. Original checkouts are migration sources;
never edit them or reuse their services, runner state or Compose volumes. Keep
complete external RDS settings; use isolated `_test` targets for database tests.
Do not run ingestion, projection rebuilds or paid evaluations for validation.
Shared media uses the suite-owned catalogue described in [media sharing](docs/shared-media.md).
Keep the independently vendored media protocols synchronized; a shared Python
package remains deferred.

Use Google-style docstrings for functions and models, explain non-obvious code,
preserve user changes, and update applicable `docs/**` with every change.
Run desktop tests from `desktop/`, Python suites from their respective app roots,
and frontend tests/builds from each frontend. Report actual validation limits.
