"""Start the local ChatTFT UI and keep its service process running."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from io import TextIOBase
from pathlib import Path
from typing import Sequence


# Import config loader from the backend.
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "app" / "backend" / "src"))
from core.config import load_config


@dataclass(frozen=True)
class Service:
    name: str
    module: str
    default_host: str
    default_port: str
    endpoint_path: str = ""

    def url(self) -> str:
        config = load_config()
        host = config.chat.ui_host if self.name == "ui" else self.default_host
        port = str(config.chat.ui_port) if self.name == "ui" else self.default_port
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        return f"http://{display_host}:{port}{self.endpoint_path}"


SERVICES: tuple[Service, ...] = (
    Service(
        "ui",
        "api",
        "127.0.0.1",
        "8300",
    ),
)

LEGACY_SERVICE_ALIASES = {"chat": "ui", "data-ui": "ui"}


def _service_by_name() -> dict[str, Service]:
    services = {service.name: service for service in SERVICES}
    services.update(
        {alias: services[target] for alias, target in LEGACY_SERVICE_ALIASES.items()}
    )
    return services


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the unified ChatTFT UI.")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for supported services during local development.",
    )
    parser.add_argument(
        "--only",
        choices=tuple(_service_by_name()),
        action="append",
        help="Start only this service. May be passed more than once.",
    )
    parser.add_argument(
        "--skip",
        choices=tuple(_service_by_name()),
        action="append",
        help="Skip this service. May be passed more than once.",
    )
    return parser


def _select_services(args: argparse.Namespace) -> list[Service]:
    services = list(SERVICES)
    by_name = _service_by_name()
    if args.only:
        requested = {LEGACY_SERVICE_ALIASES.get(name, name) for name in args.only}
        services = [service for service in SERVICES if service.name in requested]
    if args.skip:
        skipped = {LEGACY_SERVICE_ALIASES.get(name, name) for name in args.skip}
        services = [service for service in services if service.name not in skipped]
    if not services:
        raise SystemExit("No services selected.")
    return services


def _stream_output(name: str, pipe: TextIOBase | None) -> None:
    if pipe is None:
        return
    for line in pipe:
        print(f"[{name}] {line}", end="", flush=True)


def _start_service(service: Service, *, reload: bool = False) -> subprocess.Popen[str]:
    command = [sys.executable, "-m", service.module]
    if reload:
        command.append("--reload")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=os.name != "nt",
    )
    threading.Thread(
        target=_stream_output,
        args=(service.name, process.stdout),
        daemon=True,
    ).start()
    return process


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.terminate()
    else:
        os.killpg(process.pid, signal.SIGTERM)


def _kill_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.kill()
    else:
        os.killpg(process.pid, signal.SIGKILL)


def _stop_all(processes: Sequence[subprocess.Popen[str]]) -> None:
    for process in processes:
        _stop_process(process)

    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if all(process.poll() is not None for process in processes):
            return
        time.sleep(0.1)

    for process in processes:
        _kill_process(process)


def main() -> None:
    load_config()
    args = _build_parser().parse_args()
    services = _select_services(args)

    processes: list[tuple[str, subprocess.Popen[str]]] = []
    print("Starting ChatTFT services:", flush=True)
    for service in services:
        process = _start_service(service, reload=args.reload)
        processes.append((service.name, process))
        print(f"  {service.name:<7} {service.url()}", flush=True)

    try:
        while True:
            for name, process in processes:
                returncode = process.poll()
                if returncode is not None:
                    print(
                        f"{name} exited with status {returncode}; stopping stack.",
                        file=sys.stderr,
                        flush=True,
                    )
                    _stop_all([candidate for _, candidate in reversed(processes)])
                    raise SystemExit(returncode)
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nStopping ChatTFT services...", flush=True)
        _stop_all([process for _, process in reversed(processes)])


if __name__ == "__main__":
    main()
