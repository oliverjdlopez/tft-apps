"""Public Python entrypoint for the Langfuse evaluation workspace."""
from __future__ import annotations


def main() -> None:
    """Dispatch local platform and snapshot commands without importing the SDK."""
    from .langfuse.launcher import main as launch
    raise SystemExit(launch())


if __name__ == "__main__":
    main()
