"""Isolated eval database targeting."""

from __future__ import annotations

from dataclasses import replace
import os
from urllib.parse import quote

from core.config import DatabaseTarget, resolve_database_target
from db.session import database_target_override


def resolve_eval_target(name_or_dsn: str | None = None, *, require_explicit: bool = False) -> DatabaseTarget:
    """Resolve the eval RDS target, optionally selecting another database."""

    if require_explicit:
        from core.config import load_config
        load_config()  # Load this checkout's ignored environment before checking.
        required = ('RDS_EVAL_HOST', 'RDS_EVAL_PORT', 'RDS_EVAL_ADMIN', 'RDS_EVAL_DB')
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise ValueError('Captured executions require a complete RDS_EVAL target; missing: ' + ', '.join(missing))
        # IAM settings may inherit credentials/region, but coordinates never
        # inherit the normal application's database for a workspace test.
    if name_or_dsn and name_or_dsn.startswith(("postgresql://", "postgres://")):
        return resolve_database_target("eval", name_or_dsn)

    target = resolve_database_target("eval")
    if not name_or_dsn or name_or_dsn == target.database:
        return target

    # A named eval database still uses the isolated RDS_EVAL coordinates.  It
    # is useful for frozen patch databases and never borrows the app target.
    database = name_or_dsn
    username = quote(target.admin)
    database_name = quote(database, safe="")
    safe_url = (
        f"postgresql://{username}@{target.host}:{target.port}/{database_name}"
    )
    connect_url = safe_url
    if target.password:
        password = quote(target.password, safe="")
        connect_url = (
            f"postgresql://{username}:{password}@{target.host}:{target.port}/"
            f"{database_name}"
        )
    return replace(target, database=database, url=safe_url, connect_url=connect_url)


def eval_database_override(target: DatabaseTarget | str | None):
    """Scope all database tools to an eval target without changing the environment."""
    if target is None or isinstance(target, DatabaseTarget):
        resolved = target
    else:
        resolved = resolve_eval_target(target)
    return database_target_override(resolved)


__all__ = [
    "eval_database_override",
    "resolve_eval_target",
]
