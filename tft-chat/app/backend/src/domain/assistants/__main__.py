"""Run assistants with ``python -m domain.assistants``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from agents import Runner

from domain.assistants import (
    build_assistant_instructions,
    create_assistant,
    list_assistants,
    render_assistant_input,
)
from domain.assistants.constants import AssistantName


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ChatTFT assistants.")
    parser.add_argument(
        "assistant",
        nargs="?",
        default=AssistantName.CLEAN_TRANSCRIPT,
        choices=list_assistants(),
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
    print(
        Runner.run_sync(
            create_assistant(
                args.assistant,
                instructions=build_assistant_instructions(args.assistant, input_text),
            ),
            input=render_assistant_input(args.assistant, input_text),
        ).final_output
    )


if __name__ == "__main__":
    main()
