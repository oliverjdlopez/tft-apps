"""Run the unified ChatTFT API/UI: ``python -m api``."""

from __future__ import annotations

import argparse

from core.config import load_config

load_config()

import uvicorn


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the unified ChatTFT API/UI.")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable Uvicorn auto-reload for local development.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    config = load_config()
    host = config.chat.ui_host
    port = config.chat.ui_port
    uvicorn.run("api.app:app", host=host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
