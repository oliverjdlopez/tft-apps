from __future__ import annotations

from scripts import sync_rds_ip


def test_sync_rds_ip_cli_reports_disabled(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sync_rds_ip, "rds_ip_sync_enabled", lambda: False)

    assert sync_rds_ip.main([]) == 1
    assert "RDS IP sync is disabled" in capsys.readouterr().err


def test_sync_rds_ip_cli_reports_synced_cidr(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sync_rds_ip, "rds_ip_sync_enabled", lambda: True)
    monkeypatch.setattr(
        sync_rds_ip,
        "sync_rds_security_group_ip",
        lambda: "203.0.113.5/32",
    )

    assert sync_rds_ip.main([]) == 0
    assert capsys.readouterr().out.strip() == (
        "RDS security group now allows 203.0.113.5/32"
    )
