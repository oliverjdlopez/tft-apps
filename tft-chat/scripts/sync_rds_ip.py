#!/usr/bin/env python3
"""CLI to sync this host's public IP into the configured RDS security group."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the script runnable directly from a checkout as well as through its
# installed console command.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "backend" / "src"))

from aws.rds import rds_ip_sync_enabled, sync_rds_security_group_ip  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Allow this host's current public IP in the configured RDS security group."
    )


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)

    if not rds_ip_sync_enabled():
        print(
            "RDS IP sync is disabled: set RDS_SECURITY_GROUP_ID "
            "(and leave RDS_SYNC_LOCAL_IP unset or 1) to enable it.",
            file=sys.stderr,
        )
        return 1

    try:
        cidr = sync_rds_security_group_ip()
    except Exception as exc:  # noqa: BLE001
        print(f"RDS IP sync failed: {exc}", file=sys.stderr)
        return 1

    print(f"RDS security group now allows {cidr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
