---
id: change-configuration
title: Change configuration
summary: Add or modify typed INI, secret, database-target, or AWS configuration.
paths:
  - "app/backend/src/core/config.py"
  - "app/backend/src/core/settings.py"
  _ "chat_tft.ini.example"
  - ".env.example"
  - "app/backend/src/aws/**"
task_types: [change-config, add-setting, change-rds-auth]
keywords: [setting, config, INI, environment variable, RDS]
requires: [docs/configuration.md]
last_verified: "2026-08-01"
---

# Change configuration

## Use this workflow when

Adding/changing an application option, secret, typed RDS target field, model key, S3 setting, or AWS connection behavior.

## Before editing

Classify the value: ordinary behavior belongs in `chat_tft.ini`; secrets and infrastructure coordinates belong in environment variables; one_off source/destination DSNs belong only to explicit maintenance CLI arguments.

## Implementation sequence

1. Add a typed dataclass field and loader/default/validation in `core/config.py`.
2. Update `chat_tft.ini.example` or `.env.example`, not ignored local files.
3. Update compatibility access in `core/settings.py` only if existing callers use that facade.
4. Thread the typed value through its consumer and safe CLI/API override surface.
5. Preserve redaction in labels, exceptions, logs, and subprocess commands.
6. Add parse/default/override/invalid-value tests and repository consistency checks as needed.

## Required patterns

- Complete app RDS targets; eval per-field fallback; isolated non-fallback test target ending `_test`.
- Password presence selects password auth; absence selects per-connection IAM + TLS.
- No runtime full-DSN fallback and no process-environment mutation for eval scoping.

## Validation

```bash
uv run pytest -q tests/test_config.py tests/test_repository_consistency.py tests/test_ingestion_cli_config.py tests/test_chat_service.py
uv run pytest -q tests/test_rds_ip_sync.py tests/test_sync_rds_ip_cli.py tests/test_copy_rds.py
```

## Completion checklist

- Tracked example is complete and parseable.
- Secrets never appear in display-safe URLs/logs.
- CLI/API override policy is explicit and least-privileged.
- Retired environment names were not reintroduced.

## Common mistakes

Adding behavior-only environment variables, forgetting eval fallback semantics, or logging `DatabaseTarget.connect_url` instead of its safe label.
