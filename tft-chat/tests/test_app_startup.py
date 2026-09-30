from __future__ import annotations

import re
import sys

from fastapi.testclient import TestClient

import app.backend.api.app as app_module
from db import session as db_session


def test_app_uses_one_canonical_assistant_package() -> None:
    """API startup should not initialize a second assistant package identity."""
    assert "domain.assistants" in sys.modules
    assert "app.backend.src.domain.assistants" not in sys.modules


def test_database_warmup_degrades_when_rds_values_are_missing(monkeypatch) -> None:
    """Missing application RDS values should return a safe warning, not raise."""

    def missing_database() -> None:
        """Match the configuration error raised by database target resolution."""
        raise ValueError(
            "incomplete app RDS configuration; missing: RDS_HOST, RDS_ADMIN, RDS_DB"
        )

    monkeypatch.setattr(db_session, "open_db", missing_database)

    status = app_module._warm_database_at_startup()

    assert status == {
        "available": False,
        "configured": False,
        "warning": (
            "Database features are unavailable because the RDS connection values "
            "are not configured. Add RDS_HOST, RDS_ADMIN, and RDS_DB to enable them."
        ),
    }


def test_app_serves_frontend_warning_in_degraded_database_mode(monkeypatch) -> None:
    """The full FastAPI lifespan should serve UI config after failed DB warmup."""

    def missing_database() -> None:
        """Raise the same incomplete-target error as production configuration."""
        raise ValueError(
            "incomplete app RDS configuration; missing: RDS_HOST, RDS_ADMIN, RDS_DB"
        )

    monkeypatch.setattr(app_module, "_install_local_trace_recorder", lambda: None)
    monkeypatch.setattr(db_session, "open_db", missing_database)

    asset_response = None
    with TestClient(app_module.create_app()) as client:
        index = client.get("/")
        config = client.get("/api/config")
        retired_presentation = client.post("/api/presentation/investigate", json={})
        if index.status_code == 200:
            asset_path = re.search(r'(?:src|href)="(/assets/[^"]+)"', index.text).group(1)
            asset_response = client.get(asset_path)

    if app_module.STATIC_DIR.joinpath("index.html").exists():
        assert index.status_code == 200
        assert asset_response is not None
        assert asset_response.status_code == 200
    else:
        assert index.status_code == 503
        assert "npm run build" in index.text
    assert retired_presentation.status_code == 404
    assert config.status_code == 200
    assert config.json()["database"] == {
        "available": False,
        "configured": False,
        "warning": (
            "Database features are unavailable because the RDS connection values "
            "are not configured. Add RDS_HOST, RDS_ADMIN, and RDS_DB to enable them."
        ),
    }


def test_app_explains_missing_frontend_build(monkeypatch, tmp_path) -> None:
    """A clean checkout receives an actionable frontend build response."""
    monkeypatch.setattr(app_module, "STATIC_DIR", tmp_path)
    monkeypatch.setattr(app_module, "_install_local_trace_recorder", lambda: None)

    def missing_database() -> None:
        """Raise the same incomplete-target error as production configuration."""
        raise ValueError(
            "incomplete app RDS configuration; missing: RDS_HOST, RDS_ADMIN, RDS_DB"
        )

    monkeypatch.setattr(db_session, "open_db", missing_database)

    with TestClient(app_module.create_app()) as client:
        response = client.get("/")

    assert response.status_code == 503
    assert "npm ci" in response.text
    assert "npm run build" in response.text
