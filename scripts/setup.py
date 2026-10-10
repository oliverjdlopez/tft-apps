"""Compatibility setup entry point; application dependencies live in Docker."""
from pathlib import Path
import subprocess


def main() -> None:
    """Delegate setup to Node without requiring host application environments."""
    subprocess.run(["node", str(Path(__file__).resolve().with_suffix(".mjs"))], check=True)


if __name__ == "__main__":
    main()
