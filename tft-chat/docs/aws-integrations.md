# AWS integrations

## RDS targets

The app, eval runner, and database-backed tests use typed RDS configurations.
The eval prefix overrides the corresponding application setting when present;
otherwise it falls back to `RDS_*`. Each prefix supports `INSTANCE_ID`, `HOST`,
`PORT`, `ADMIN`, `DB`, and optional `PASSWORD`:

| Target | Prefix |
| --- | --- |
| Application | `RDS_` |
| Evaluations | `RDS_EVAL_` |
| Tests | `RDS_TEST_` |

The resolved app/eval target requires `HOST`, `ADMIN`, and `DB` together.
Password absence selects IAM
authentication; a new IAM token is minted for every physical connection.
`RDS_TEST_DB` must end in `_test`, and test coordinates must differ from app and
eval coordinates.

Each target may also define `SECURITY_GROUP_ID`, `SYNC_LOCAL_IP`,
`SECURITY_GROUP_RULE_DESCRIPTION`, `IP_CACHE_FILE`, and `IP_CHECK_URL`. When a
security group is configured, the active RDS module uses one fixed public IPv4
lookup and updates the managed TCP rule on the target port. AWS credentials and
region are consumed through boto3's normal provider chain.

## Maintenance commands

Application runtime never reads a full database DSN from the environment.
Explicit DSNs remain available only to controlled maintenance commands:
`tft-migrate-relational-v2 --dsn`, `tft-add-analysis-indexes --dsn`, rebuild or
update overrides, `tft-freeze-patch-db --source-dsn`, and `tft-copy-rds`.

`tft-freeze-patch-db PATCH` uses `RDS_INSTANCE_ID` as its source instance unless
`--source-instance-id` is supplied. It snapshots the configured scope in one
repeatable-read read-only transaction, provisions a deterministic target,
rebuilds and validates it, and retains the target if a later stage fails. On
success it prints the exact `RDS_INSTANCE_ID`, `RDS_HOST`, `RDS_PORT`,
`RDS_ADMIN`, and `RDS_DB` values needed for an explicit cutover.

Run `tft-sync-rds-ip` to force an ingress sync outside an application process.
It requires `RDS_SECURITY_GROUP_ID` and is disabled by setting
`RDS_SYNC_LOCAL_IP=0`.

## S3

S3 is an opt-in raw-payload mirror configured with `CHAT_TFT_S3_UPLOAD`,
`CHAT_TFT_S3_BUCKET`, and `CHAT_TFT_S3_PREFIX`. No AWS credentials are copied
into application settings; boto3 resolves them from its standard provider
chain.
