"""Run the suite's declared validation tiers with bounded, owned processes.

Use --list to inspect commands without executing them. Dependencies are installed
explicitly by setup/CI; this runner never changes an application's environment.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "tft-chat"
VOD = ROOT / "vod-review"
DESKTOP = ROOT / "desktop"
TIERS = ("offline", "postgres", "browser", "native", "pdf", "gpu", "external", "windows")


def python(root):
    """Resolve an explicitly overridden or checkout-local application interpreter."""
    key = "CHAT_TEST_PYTHON" if root == CHAT else "VOD_TEST_PYTHON"
    return os.environ.get(key, str(root / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")))


def commands(tier, component, output, coverage=False):
    """Describe each tier as named commands with their owning working directories."""
    jobs = []
    for app, root in (("chat", CHAT), ("vod", VOD), ("desktop", DESKTOP)):
        if component not in ("all", app):
            continue
        if tier == "offline":
            if app == "desktop":
                jobs.extend([(app + "-js", root, ["node", "--test", "tests/*.test.mjs"]),
                             (app + "-python", root, [python(CHAT), "-m", "pytest", "-q", "-ra", f"--junitxml={output / 'desktop.xml'}"])])
            else:
                args = [python(root), "-m", "pytest", "-q", "-ra", f"--junitxml={output / (app + '.xml')}"]
                args += ["--database-tests=exclude"] if app == "chat" else ["--import-mode=importlib"]
                if coverage:
                    args += ["--cov=app/backend" if app == "chat" else "--cov=backend", f"--cov-report=xml:{output / (app + '-coverage.xml')}"]
                jobs.append((app + "-python", root, args))
                frontend = root / ("app/frontend" if app == "chat" else "frontend")
                jobs.extend([(app + "-ui", frontend, ["npm", "test", *(["--", "--coverage"] if coverage else [])]),
                             (app + "-build", frontend, ["npm", "run", "build"])])
                if app == "chat":
                    jobs.append(("eval-definitions", root, [python(root), "-m", "evals", "validate"]))
                    jobs.append(("eval-fixture", root, [python(root), "-m", "evals.validation_fixture"]))
                    jobs.append(("semantic-corpus", root, [python(root), "-m", "evals.calibration"]))
        elif tier == "postgres" and app == "chat":
            jobs.append(("postgres", root, [python(root), "-m", "pytest", "-q", "-ra", "--database-tests=only", "--require-test-database", f"--junitxml={output / 'postgres.xml'}"]))
        elif tier == "pdf" and app == "chat":
            jobs.append(("pdf", root, [python(root), "-m", "pytest", "-q", "tests/test_export_eval_pdfs.py", f"--junitxml={output / 'pdf.xml'}"]))
        elif tier == "gpu" and app == "chat":
            jobs.append(("gpu", root, [python(root), "-m", "pytest", "-q", "tests/compositions/test_acceleration.py", "tests/compositions/test_hdbscan_gpu.py", "tests/compositions/test_benchmarks.py", f"--junitxml={output / 'gpu.xml'}"]))
    if tier == "browser":
        jobs.extend([("browser-chat-build", CHAT / "app/frontend", ["npm", "run", "build"]),
                     ("browser-vod-build", VOD / "frontend", ["npm", "run", "build"])])
        jobs.append(("flowchart-browser", CHAT, ["node", "tests/flowchart_browser_smoke.mjs"]))
        journey = ROOT / "tests/browser/journeys.mjs"
        if journey.exists():
            jobs.append(("application-journeys", ROOT, ["node", str(journey)]))
    if tier in ("native", "external", "windows"):
        executable = os.environ.get("ELECTRON_TEST_BINARY", str(DESKTOP / "node_modules/electron/dist/electron"))
        scripts = {"native": ["workspace-electron.mjs", "suite-electron.mjs"],
                   "external": ["online-vod-electron.mjs"], "windows": ["test-wsl.mjs"]}[tier]
        for script in scripts:
            command = ["node", "tests/" + script] if tier == "windows" else [executable, "--disable-gpu", "tests/" + script]
            if script == "suite-electron.mjs":
                command.append("--disposable-ports")
            jobs.append((script.removesuffix(".mjs"), DESKTOP, command))
    return jobs


def environment(tier, output):
    """Disable unintended live integrations and isolate generated application state."""
    env = dict(os.environ)
    for name in list(env):
        if name.startswith(("RDS_", "LANGFUSE_")) or name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CHAT_TFT_RUN_CONFIGURED_DB_SMOKE_TESTS"):
            if tier != "postgres" or not name.startswith("RDS_TEST_"):
                env.pop(name, None)
    for prefix in ("RDS_", "RDS_EVAL_"):
        for field in ("HOST", "ADMIN", "DB", "PASSWORD"):
            env[prefix + field] = ""
        env[prefix + "SYNC_LOCAL_IP"] = "0"
    if tier != "postgres":
        env.update(RDS_TEST_HOST="127.0.0.1", RDS_TEST_PORT="1", RDS_TEST_ADMIN="tft",
                   RDS_TEST_PASSWORD="unused", RDS_TEST_DB="validation_test", CI="false")
    env.update(TFT_MEDIA_DIR=str(output / "media"), VOD_DATA_DIR=str(output / "vod"),
               VOD_GDRIVE_TOKEN_FILE=str(output / "vod/gdrive/token.json"), VOD_GDRIVE_CLIENT_FILE="",
               VOD_TRACE_JSONL=str(output / "vod-trace.jsonl"), VOD_OCR_CACHE_DIR=str(output / "vod/ocr_cache"),
               VOD_FRAMES_DIR=str(output / "vod/frames"), VOD_BOXES_DIR=str(output / "vod/boxes"),
               VOD_SAVE_FRAMES="0", VOD_SAVE_BOXES="0",
               OPENAI_API_KEY="", ANTHROPIC_API_KEY="", LANGFUSE_PUBLIC_KEY="", LANGFUSE_SECRET_KEY="", VITE_API_BASE="",
               LANGFUSE_TRACING_ENABLED="false", LANGFUSE_RUNTIME_DIR=str(output / "eval-runtime"),
               VALIDATION_ARTIFACTS=str(output), HYPOTHESIS_STORAGE_DIRECTORY=str(output / "hypothesis"),
               COVERAGE_FILE=str(output / ".coverage"), RDS_TEST_SYNC_LOCAL_IP="0")
    env.pop("ELECTRON_RUN_AS_NODE", None)
    if tier == "gpu":
        env["CHATTFT_HDBSCAN_CUDA_TEST"] = "1"
        env["CHATTFT_BENCHMARK_CUDA_TEST"] = "1"
    return env


def stop(process):
    """Terminate a validation process group, escalating only its owned children."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def execute(name, cwd, command, env, output, timeout=600):
    """Capture a bounded command and return a serializable outcome with its log."""
    started = time.monotonic()
    log = output / (name + ".log")
    print(f"Running {name}: {' '.join(command)}", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=os.name == "posix")
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = 124
        finally:
            stop(process)
    result = {"name": name, "command": command, "cwd": str(cwd), "exit_code": code,
              "seconds": round(time.monotonic() - started, 2), "log": str(log)}
    print(f"{name}: {'PASS' if code == 0 else 'FAIL'} ({result['seconds']}s); {log}", flush=True)
    return result


@contextmanager
def server(module, cwd, interpreter, env, output):
    """Own a temporary HTTP fixture server on a kernel-selected loopback port."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with (output / (module.split('.')[-1] + "-server.log")).open("w") as stream:
        process = subprocess.Popen([interpreter, "-m", "uvicorn", "--app-dir", "tests", module + ":app", "--host", "127.0.0.1", "--port", str(port)],
                                   cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Fixture {module} exited during startup")
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        break
                time.sleep(0.1)
            else:
                raise TimeoutError(f"Fixture {module} failed to listen")
            yield f"http://127.0.0.1:{port}"
        finally:
            stop(process)


def junit_summary(output, required=False):
    """Report test counts and reject empty or skipped required integration runs."""
    reports = {}
    for path in output.glob("*.xml"):
        if "coverage" in path.name:
            continue
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        counts = {key: sum(int(suite.get(key, 0)) for suite in suites) for key in ("tests", "failures", "errors", "skipped")}
        reports[path.name] = counts
        if required and (counts["tests"] == 0 or counts["skipped"]):
            raise RuntimeError(f"Required tier did not fully execute: {path.name}: {counts}")
    if required and not reports:
        raise RuntimeError("Required tier produced no test inventory")
    return reports


def runtime_versions():
    """Record executable versions without including inherited secrets or settings."""
    versions = {"platform": sys.platform, "runner_python": sys.version.split()[0]}
    for name, command in (("chat_python", [python(CHAT), "--version"]),
                          ("vod_python", [python(VOD), "--version"]), ("node", ["node", "--version"])):
        try:
            versions[name] = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, timeout=5).strip()
        except (OSError, subprocess.SubprocessError):
            versions[name] = "unavailable"
    return versions


def main():
    """Run one explicit tier and leave diagnostics even when a command fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=TIERS, default="offline")
    parser.add_argument("--component", choices=("all", "chat", "vod", "desktop"), default="all")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/validation")
    args = parser.parse_args()
    def interrupted(signum, frame):
        """Unwind owned-process contexts on cancellation so diagnostics survive."""
        raise KeyboardInterrupt(f"Validation interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    output = args.output.resolve() / (args.tier + "-" + args.component) / (time.strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}")
    jobs = commands(args.tier, args.component, output, args.coverage)
    if args.list:
        print(json.dumps([{"name": name, "cwd": str(cwd), "command": command} for name, cwd, command in jobs], indent=2))
        return 0
    if not jobs:
        parser.error("No checks exist for this tier/component combination")
    output.mkdir(parents=True, exist_ok=True)
    env = environment(args.tier, output)
    env["FLOWCHART_PLAYWRIGHT_MODULE"] = str(ROOT / "tests/browser/node_modules/playwright/index.mjs")
    env["FLOWCHART_SMOKE_SCREENSHOT"] = str(output / "flowchart.png")
    results, error = [], None
    try:
        if args.tier == "windows" and not os.environ.get("WSL_DISTRO_NAME"):
            raise RuntimeError("Windows/WSL acceptance requires the existing WSL-to-Windows bridge")
        for name, cwd, command in jobs:
            if name == "flowchart-browser":
                with server("flowchart_smoke_server", CHAT, python(CHAT), env, output) as url:
                    result = execute(name, cwd, command, {**env, "FLOWCHART_SMOKE_URL": url}, output)
            else:
                result = execute(name, cwd, command, env, output)
            results.append(result)
        inventory = junit_summary(output, required=args.tier in ("postgres", "pdf", "gpu"))
    except (OSError, RuntimeError, TimeoutError, KeyboardInterrupt) as exc:
        error, inventory = str(exc), {}
        print(error, file=sys.stderr)
    report = {"tier": args.tier, "component": args.component, "results": results, "inventory": inventory,
              "environment": runtime_versions(), "excluded_tiers": [tier for tier in TIERS if tier != args.tier],
              "error": error, "passed": not error and bool(results) and all(row["exit_code"] == 0 for row in results)}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
