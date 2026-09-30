"""The single application configuration loader.

Secrets and infrastructure coordinates are read from ``.env``.  Operator
behaviour belongs in ``chat_tft.ini`` and command line options are deliberately
handled by the command that owns them.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

from dotenv import load_dotenv

from common.paths import find_repo_root
from common.secrets import redact_url_credentials

DatabasePurpose = Literal["app", "eval", "test"]
DatabaseAuthMode = Literal["iam", "password", "maintenance_dsn"]


def _env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def _env_int(name: str, default: int) -> int:
    raw = _env_value(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_value(name)
    if not raw:
        return default
    if raw.lower() in {"1", "true", "yes", "on"}:
        return True
    if raw.lower() in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean, got {raw!r}")


def _ini_value(ini: configparser.ConfigParser, section: str, key: str, default: str = "") -> str:
    raw = ini.get(section, key, fallback="").strip()
    return raw if raw else default


def _ini_int(ini: configparser.ConfigParser, section: str, key: str, default: int) -> int:
    raw = _ini_value(ini, section, key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"[{section}] {key} must be an integer, got {raw!r}") from exc


def _ini_optional_int(ini: configparser.ConfigParser, section: str, key: str) -> int | None:
    raw = _ini_value(ini, section, key)
    return None if not raw else _ini_int(ini, section, key, 0)


def _ini_bool(ini: configparser.ConfigParser, section: str, key: str, default: bool) -> bool:
    raw = _ini_value(ini, section, key)
    if not raw:
        return default
    if raw.lower() in {"1", "true", "yes", "on"}:
        return True
    if raw.lower() in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"[{section}] {key} must be a boolean, got {raw!r}")


def _ini_flowchart_source(ini: configparser.ConfigParser) -> str:
    """Read the default flowchart workspace source for the desktop Flowchart tab.

    Args:
        ini: Parsed application settings.

    Returns:
        ``database`` (editable PostgreSQL workspaces) or ``json`` (checked-in
        ``gameplans/`` documents); an empty value keeps the database default.
    """
    raw = (_ini_value(ini, "chat", "flowchart_source") or "database").lower()
    if raw not in {"database", "json"}:
        raise ValueError(f"[chat] flowchart_source must be database or json, got {raw!r}")
    return raw


@dataclass(frozen=True)
class SecretConfig:
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    riot_api_key: str = ""
    mcp_token: str = ""


@dataclass(frozen=True)
class ModelConfig:
    openai_model: str = "gpt-5"
    anthropic_model: str = "claude-sonnet-5"


@dataclass(frozen=True)
class ChatConfig:
    """Typed chat runtime options, including explicitly opted-in development export."""

    max_tool_rounds: int = 6
    mcp_url: str = "http://127.0.0.1:8000/mcp"
    mcp_name: str = "chat_tft_mcp"
    mcp_timeout: int = 30
    mcp_headers: str = ""
    ui_host: str = "127.0.0.1"
    ui_port: int = 8300
    composition_workbench: bool = True
    composition_offline: bool = False
    flowchart_source: str = "database"
    patch: str | None = None
    set_number: int | None = None
    rebuild_query_tables_on_startup: str = "false"
    langfuse_tracing: bool = False
    local_tracing: bool = True
    trace_dir: Path | None = None


@dataclass(frozen=True)
class IngestConfig:
    """Persistent defaults for CLI and API-triggered match ingestion."""

    platform: str = "na1"
    platforms: str | None = None
    queue: str = "RANKED_TFT"
    max_new_matches: int = 50
    matches_per_player: int = 10
    player_batch_size: int | None = None
    tiers: str = "challenger,grandmaster,master"
    patch_override: str | None = None
    fetch_concurrency: int = 10
    insert_to_db: bool = True
    commit_every: int = 25
    analysis_every: int = 500
    endless: bool = False
    cycle_delay: int = 60
    endless_matches_per_player: int = 5
    endless_player_batch_size: int = 50
    log_level: str | None = None


@dataclass(frozen=True)
class S3Config:
    upload: bool = False
    bucket: str = ""
    prefix: str = ""


@dataclass(frozen=True)
class RdsUpgradeConfig:
    instance_id: str = ""


@dataclass(frozen=True)
class RdsTargetConfig:
    instance_id: str = ""
    host: str = ""
    port: int = 5432
    admin: str = ""
    db: str = ""
    password: str = ""
    sync_local_ip: bool = True
    security_group_id: str = ""
    security_group_rule_description: str = "chat_tft_rds_local_ip"
    ip_cache_file: Path = field(default_factory=lambda: Path.home() / ".cache" / "chat_tft_rds_ip.txt")
    ip_check_url: str = "https://checkip.amazonaws.com"

    @property
    def configured(self) -> bool:
        return any((self.instance_id, self.host, self.admin, self.db))


@dataclass(frozen=True)
class AppConfig:
    secrets: SecretConfig = field(default_factory=SecretConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    s3: S3Config = field(default_factory=S3Config)
    rds_upgrade: RdsUpgradeConfig = field(default_factory=RdsUpgradeConfig)
    rds: RdsTargetConfig = field(default_factory=RdsTargetConfig)
    rds_eval: RdsTargetConfig = field(default_factory=RdsTargetConfig)
    rds_test: RdsTargetConfig = field(default_factory=RdsTargetConfig)


@dataclass(frozen=True)
class DatabaseTarget:
    """A resolved database target whose public URL never contains a secret."""

    url: str
    purpose: DatabasePurpose
    auth_mode: DatabaseAuthMode
    host: str = ""
    port: int = 5432
    admin: str = ""
    database: str = ""
    instance_id: str | None = None
    password: str = field(default="", repr=False, compare=False)
    connect_url: str = field(default="", repr=False, compare=False)

    @property
    def credential_safe_url(self) -> str:
        return self.url


def _read_ini(path: Path | None) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config_path = path or find_repo_root() / "chat_tft.ini"
    if config_path.exists():
        config.read(config_path)
    allowed = {
        "models": {"openai_model", "anthropic_model"},
        "chat": {
            "max_tool_rounds", "mcp_url", "mcp_name", "mcp_timeout", "mcp_headers",
            "ui_host", "ui_port", "composition_workbench", "composition_offline", "flowchart_source", "patch", "set_number", "rebuild_query_tables_on_startup",
            "local_tracing", "trace_dir", "langfuse_tracing",
        },
        "ingest": {
            "platform", "platforms", "queue", "max_new_matches", "matches_per_player", "player_batch_size",
            "tiers", "patch_override", "fetch_concurrency", "insert_to_db", "commit_every", "analysis_every", "endless", "cycle_delay",
            "endless_matches_per_player", "endless_player_batch_size", "log_level",
        },
        "rds-upgrade": {"instance_id"},
    }
    for section in config.sections():
        if section not in allowed:
            raise ValueError(f"Unknown INI section [{section}]")
        unknown = set(config[section]) - allowed[section]
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"Unknown INI key(s) in [{section}]: {names}")
    return config


def _rds_target(prefix: str, fallback: RdsTargetConfig | None = None) -> RdsTargetConfig:
    cache_default = Path.home() / ".cache" / f"chat_tft_{prefix.lower()}_ip.txt"
    return RdsTargetConfig(
        instance_id=_env_value(f"{prefix}INSTANCE_ID", fallback.instance_id if fallback else ""),
        host=_env_value(f"{prefix}HOST", fallback.host if fallback else ""),
        port=_env_int(f"{prefix}PORT", fallback.port if fallback else 5432),
        admin=_env_value(f"{prefix}ADMIN", fallback.admin if fallback else ""),
        db=_env_value(f"{prefix}DB", fallback.db if fallback else ""),
        password=_env_value(f"{prefix}PASSWORD", fallback.password if fallback else ""),
        sync_local_ip=_env_bool(
            f"{prefix}SYNC_LOCAL_IP", fallback.sync_local_ip if fallback else True
        ),
        security_group_id=_env_value(
            f"{prefix}SECURITY_GROUP_ID", fallback.security_group_id if fallback else ""
        ),
        security_group_rule_description=_env_value(
            f"{prefix}SECURITY_GROUP_RULE_DESCRIPTION",
            fallback.security_group_rule_description if fallback else "chat_tft_rds_local_ip",
        ),
        ip_cache_file=Path(
            _env_value(
                f"{prefix}IP_CACHE_FILE",
                str(fallback.ip_cache_file) if fallback else str(cache_default),
            )
        ).expanduser(),
        ip_check_url=_env_value(
            f"{prefix}IP_CHECK_URL",
            fallback.ip_check_url if fallback else "https://checkip.amazonaws.com",
        ),
    )


def load_config(path: Path | None = None) -> AppConfig:
    """Load the repository configuration exactly once at the application boundary."""
    load_dotenv(find_repo_root() / ".env")
    ini = _read_ini(path)
    trace_dir = _ini_value(ini, "chat", "trace_dir") or None
    rds = _rds_target("RDS_")
    return AppConfig(
        secrets=SecretConfig(
            anthropic_api_key=_env_value("ANTHROPIC_API_KEY"),
            openai_api_key=_env_value("OPENAI_API_KEY"),
            riot_api_key=_env_value("RIOT_API_KEY"),
            mcp_token=_env_value("CHAT_TFT_MCP_TOKEN"),
        ),
        models=ModelConfig(
            openai_model=_ini_value(ini, "models", "openai_model", "gpt-5"),
            anthropic_model=_ini_value(ini, "models", "anthropic_model", "claude-sonnet-5"),
        ),
        chat=ChatConfig(
            max_tool_rounds=_ini_int(ini, "chat", "max_tool_rounds", 6),
            mcp_url=_ini_value(ini, "chat", "mcp_url", "http://127.0.0.1:8000/mcp"),
            mcp_name=_ini_value(ini, "chat", "mcp_name", "chat_tft_mcp"),
            mcp_timeout=_ini_int(ini, "chat", "mcp_timeout", 30),
            mcp_headers=_ini_value(ini, "chat", "mcp_headers"),
            ui_host=_ini_value(ini, "chat", "ui_host", "127.0.0.1"),
            ui_port=_ini_int(ini, "chat", "ui_port", 8300),
            composition_workbench=_ini_bool(ini, "chat", "composition_workbench", True),
            composition_offline=_ini_bool(ini, "chat", "composition_offline", False),
            flowchart_source=_ini_flowchart_source(ini),
            patch=_ini_value(ini, "chat", "patch") or None,
            set_number=_ini_optional_int(ini, "chat", "set_number"),
            rebuild_query_tables_on_startup=_ini_value(ini, "chat", "rebuild_query_tables_on_startup", "false"),
            langfuse_tracing=_ini_bool(ini, "chat", "langfuse_tracing", False),
            local_tracing=_ini_bool(ini, "chat", "local_tracing", True),
            trace_dir=Path(trace_dir).expanduser() if trace_dir else None,
        ),
        ingest=IngestConfig(
            platform=_ini_value(ini, "ingest", "platform", "na1"),
            platforms=_ini_value(ini, "ingest", "platforms") or None,
            queue=_ini_value(ini, "ingest", "queue", "RANKED_TFT"),
            max_new_matches=_ini_int(ini, "ingest", "max_new_matches", 50),
            matches_per_player=_ini_int(ini, "ingest", "matches_per_player", 10),
            player_batch_size=_ini_optional_int(ini, "ingest", "player_batch_size"),
            tiers=_ini_value(ini, "ingest", "tiers", "challenger,grandmaster,master"),
            patch_override=_ini_value(ini, "ingest", "patch_override") or None,
            fetch_concurrency=_ini_int(ini, "ingest", "fetch_concurrency", 10),
            insert_to_db=_ini_bool(ini, "ingest", "insert_to_db", True),
            commit_every=_ini_int(ini, "ingest", "commit_every", 25),
            analysis_every=_ini_int(ini, "ingest", "analysis_every", 500),
            endless=_ini_bool(ini, "ingest", "endless", False),
            cycle_delay=_ini_int(ini, "ingest", "cycle_delay", 60),
            endless_matches_per_player=_ini_int(ini, "ingest", "endless_matches_per_player", 5),
            endless_player_batch_size=_ini_int(ini, "ingest", "endless_player_batch_size", 50),
            log_level=_ini_value(ini, "ingest", "log_level") or None,
        ),
        s3=S3Config(
            upload=_env_bool("CHAT_TFT_S3_UPLOAD", False),
            bucket=_env_value("CHAT_TFT_S3_BUCKET"),
            prefix=_env_value("CHAT_TFT_S3_PREFIX").strip("/"),
        ),
        rds_upgrade=RdsUpgradeConfig(
            instance_id=_ini_value(ini, "rds-upgrade", "instance_id"),
        ),
        rds=rds,
        rds_eval=_rds_target("RDS_EVAL_", fallback=rds),
        rds_test=_rds_target("RDS_TEST_"),
    )


def _redacted_rds_url(target: RdsTargetConfig) -> str:
    return f"postgresql://{quote(target.admin)}@{target.host}:{target.port}/{quote(target.db, safe='')}"


def resolve_database_target(
    purpose: DatabasePurpose = "app", explicit_dsn: str | None = None
) -> DatabaseTarget:
    """Resolve one isolated RDS target, or an explicitly supplied maintenance DSN."""
    if purpose not in {"app", "eval", "test"}:
        raise ValueError(f"unknown database purpose: {purpose!r}")
    if explicit_dsn:
        if not explicit_dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("database DSNs must use postgresql:// or postgres://")
        parsed = urlsplit(explicit_dsn)
        return DatabaseTarget(
            url=redact_url_credentials(explicit_dsn),
            connect_url=explicit_dsn,
            purpose=purpose,
            auth_mode="maintenance_dsn",
            host=parsed.hostname or "",
            port=parsed.port or 5432,
            admin=parsed.username or "",
            database=(parsed.path or "/").lstrip("/"),
        )

    config = load_config()
    settings = {"app": config.rds, "eval": config.rds_eval, "test": config.rds_test}[purpose]
    missing = [name for name, value in (("HOST", settings.host), ("ADMIN", settings.admin), ("DB", settings.db)) if not value]
    if missing:
        raise ValueError(f"incomplete {purpose} RDS configuration; missing: " + ", ".join(f"RDS_{'EVAL_' if purpose == 'eval' else 'TEST_' if purpose == 'test' else ''}{name}" for name in missing))
    if purpose == "test" and not settings.db.endswith("_test"):
        raise ValueError("RDS_TEST_DB must end with _test")
    if purpose == "test":
        test_tuple = (settings.host, settings.port, settings.db)
        for other_name, other in (("app", config.rds), ("eval", config.rds_eval)):
            if other.host and other.db and test_tuple == (other.host, other.port, other.db):
                raise ValueError(f"RDS_TEST_* target must be isolated from the {other_name} target")
    auth_mode: DatabaseAuthMode = "password" if settings.password else "iam"
    safe_url = _redacted_rds_url(settings)
    connect_url = f"postgresql://{quote(settings.admin)}@{settings.host}:{settings.port}/{quote(settings.db, safe='')}"
    if settings.password:
        connect_url = f"postgresql://{quote(settings.admin)}:{quote(settings.password, safe='')}@{settings.host}:{settings.port}/{quote(settings.db, safe='')}"
    return DatabaseTarget(
        url=safe_url,
        connect_url=connect_url,
        purpose=purpose,
        auth_mode=auth_mode,
        host=settings.host,
        port=settings.port,
        admin=settings.admin,
        database=settings.db,
        instance_id=settings.instance_id or None,
        password=settings.password,
    )


__all__ = [
    "AppConfig", "ChatConfig", "DatabaseAuthMode", "DatabasePurpose", "DatabaseTarget",
    "IngestConfig", "ModelConfig", "RdsTargetConfig", "RdsUpgradeConfig", "S3Config", "SecretConfig",
    "load_config", "resolve_database_target",
]
