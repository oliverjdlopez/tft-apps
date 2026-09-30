"""Build or serve the project documentation site (Sphinx).

Renders the hand-written Markdown under ``docs/`` plus an autodoc API
reference generated from ``app/backend`` docstrings into a browsable site,
using the ``docs/conf.py`` Sphinx config.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO_ROOT / "docs"
BUILD_DIR = REPO_ROOT / "docs" / "_build" / "html"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build a static site into docs/_build/html instead of serving it live.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port to serve on when not using --build (default: 8001).",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Don't open a browser tab when serving.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.build:
        if shutil.which("sphinx-build") is None:
            sys.exit(
                "sphinx-build is not installed. Install docs deps with: pip install -e '.[docs]'"
            )
        command = ["sphinx-build", "-b", "html", str(SOURCE_DIR), str(BUILD_DIR)]
    else:
        if shutil.which("sphinx-autobuild") is None:
            sys.exit(
                "sphinx-autobuild is not installed. Install docs deps with: pip install -e '.[docs]'"
            )
        command = [
            "sphinx-autobuild",
            str(SOURCE_DIR),
            str(BUILD_DIR),
            "--port",
            str(args.port),
        ]
        if not args.no_open:
            command.append("--open-browser")

    result = subprocess.run(command, cwd=REPO_ROOT)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
