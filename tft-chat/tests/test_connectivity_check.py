"""Tests for the standalone AWS and PostgreSQL connectivity check script."""

from __future__ import annotations

import connectivity_check


def test_main_loads_configuration_before_connectivity_checks(monkeypatch) -> None:
    """Load dotenv-backed settings before checks read process environment values."""
    events: list[str] = []

    def fake_load_config() -> None:
        """Record the configuration initialization performed by the CLI."""
        events.append("load_config")

    def fake_s3() -> bool:
        """Record the S3 check after configuration initialization."""
        events.append("s3")
        return True

    def fake_rds() -> bool:
        """Record the RDS check after configuration initialization."""
        events.append("rds")
        return True

    monkeypatch.setattr(connectivity_check, "load_config", fake_load_config)
    monkeypatch.setattr(connectivity_check, "connect_to_s3", fake_s3)
    monkeypatch.setattr(connectivity_check, "connect_to_rds", fake_rds)

    assert connectivity_check.main() == 0
    assert events == ["load_config", "s3", "rds"]
