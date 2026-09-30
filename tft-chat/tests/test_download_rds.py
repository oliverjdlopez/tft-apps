from __future__ import annotations

import pytest

from core.config import DatabaseAuthMode, DatabaseTarget
from scripts import download_rds


def _rds_target(
    *, auth_mode: DatabaseAuthMode = "iam", password: str = ""
) -> DatabaseTarget:
    """Build a representative configured RDS target for downloader tests.

    Args:
        auth_mode: Authentication mode under test.
        password: Configured database password when password auth is selected.

    Returns:
        Credential-safe application database target.
    """
    return DatabaseTarget(
        url="postgresql://chat_admin@source.example.com:5432/chat_tft",
        connect_url="postgresql://chat_admin@source.example.com:5432/chat_tft",
        purpose="app",
        auth_mode=auth_mode,
        host="source.example.com",
        port=5432,
        admin="chat_admin",
        database="chat_tft",
        password=password,
    )


def test_download_rds_uses_iam_token_and_default_local_database(monkeypatch) -> None:
    """Verify IAM downloads create a same-named local database."""
    source = _rds_target()
    synced_targets: list[DatabaseTarget] = []
    copied: list[tuple[object, str]] = []

    monkeypatch.setattr(
        download_rds,
        "sync_rds_security_group_ip",
        lambda *, target: synced_targets.append(target),
    )
    monkeypatch.setattr(download_rds, "generate_rds_auth_token", lambda _info: "iam-token")
    monkeypatch.setattr(download_rds, "rds_connection_info", lambda target: target)
    monkeypatch.setattr(
        download_rds,
        "copy_rds_database",
        lambda options, *, source_password: copied.append((options, source_password)),
    )

    destination = download_rds.download_rds_database(source)

    options, password = copied[0]
    assert synced_targets == [source]
    assert password == "iam-token"
    assert options.source == "postgresql://chat_admin@source.example.com:5432/chat_tft?sslmode=require"
    assert options.destination == "postgresql:///chat_tft"
    assert options.create_destination is True
    assert destination == "postgresql:///chat_tft"


def test_download_rds_uses_configured_password_and_restore_options(monkeypatch) -> None:
    """Verify password downloads forward explicit local restore controls."""
    source = _rds_target(auth_mode="password", password="secret")
    copied: list[tuple[object, str]] = []

    monkeypatch.setattr(download_rds, "sync_rds_security_group_ip", lambda *, target: None)
    monkeypatch.setattr(
        download_rds,
        "copy_rds_database",
        lambda options, *, source_password: copied.append((options, source_password)),
    )

    destination = download_rds.download_rds_database(
        source,
        local_database="local copy",
        drop_existing_objects=True,
        jobs=3,
        verbose=True,
    )

    options, password = copied[0]
    assert password == "secret"
    assert options.destination == "postgresql:///local%20copy"
    assert options.drop_existing_objects is True
    assert options.jobs == 3
    assert options.verbose is True
    assert destination == "postgresql:///local%20copy"


def test_download_rds_rejects_maintenance_dsn_source(monkeypatch) -> None:
    """Verify the focused command rejects sources outside configured RDS."""
    configured = _rds_target()
    source = DatabaseTarget(
        url=configured.url,
        connect_url=configured.connect_url,
        purpose="app",
        auth_mode="maintenance_dsn",
        host=configured.host,
        port=configured.port,
        admin=configured.admin,
        database=configured.database,
    )
    synced_targets: list[DatabaseTarget] = []
    monkeypatch.setattr(
        download_rds,
        "sync_rds_security_group_ip",
        lambda *, target: synced_targets.append(target),
    )

    with pytest.raises(ValueError, match="configured RDS"):
        download_rds.download_rds_database(source)

    assert synced_targets == []


def test_download_rds_rejects_invalid_jobs_before_ingress_sync(monkeypatch) -> None:
    """Verify invalid restore concurrency cannot trigger an AWS update."""
    source = _rds_target()
    synced_targets: list[DatabaseTarget] = []
    monkeypatch.setattr(
        download_rds,
        "sync_rds_security_group_ip",
        lambda *, target: synced_targets.append(target),
    )

    with pytest.raises(ValueError, match="jobs"):
        download_rds.download_rds_database(source, jobs=0)

    assert synced_targets == []
