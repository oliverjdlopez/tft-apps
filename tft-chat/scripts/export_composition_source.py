"""Refresh the checked-in composition population on a database-connected machine."""

import argparse
from pathlib import Path
from services.compositions.source import export_frozen_source
from services.compositions.snapshot import frozen_source_path


def main():
    """Capture all eligible scoped facts using only the configured typed app target."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=frozen_source_path())
    args = parser.parse_args()
    source = export_frozen_source(args.output)
    print(f"Exported {source.eligible_boards:,} boards; patch {source.patch}, "
          f"set {source.set_number}, queue {source.queue_id}; "
          f"{args.output.stat().st_size:,} bytes to {args.output}")


if __name__ == "__main__":
    main()
