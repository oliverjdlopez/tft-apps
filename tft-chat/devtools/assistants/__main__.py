"""Run assistants manually with ``python -m devtools.assistants``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from domain.assistants import Assistant
from domain.runtime.execution import run_sync
from domain.assistants.registry import current_registry
from domain.assistants.constants import AssistantName


def main() -> None:
    """Run a selected assistant on inline, file, or standard-input text."""
    parser = argparse.ArgumentParser(description="Run ChatTFT assistants.")
    parser.add_argument(
        "assistant",
        nargs="?",
        default=AssistantName.DISTILL_TRANSCRIPT,
        choices=list(current_registry().assistant_names),
        help="Assistant to run.",
    )
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--input", help="Inline input text to pass to the assistant.")
    input_group.add_argument(
        "--input-file",
        type=Path,
        help="Path to an input text file to pass to the assistant.",
    )
    args = parser.parse_args()
    if args.input_file is not None:
        input_text = args.input_file.read_text(encoding="utf-8")
    elif args.input is not None:
        input_text = args.input
    elif not sys.stdin.isatty():
        input_text = sys.stdin.read()
    else:
        input_text = ""
    print(run_sync(Assistant.from_name(args.assistant), input_text, surface="cli").final_output)


if __name__ == "__main__":
    main()
