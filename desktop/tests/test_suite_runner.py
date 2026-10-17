"""Acceptance checks for tier isolation, process deadlines, and failure reports."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("test_suite_runner", ROOT / "scripts/test_suite.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_offline_environment_cannot_opt_into_configured_services(tmp_path, monkeypatch):
    """Inherited production targets and paid credentials cannot leak into tests."""
    for name in ("RDS_HOST", "RDS_EVAL_PASSWORD", "OPENAI_API_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.setenv(name, "private")
    monkeypatch.setenv("CHAT_TFT_RUN_CONFIGURED_DB_SMOKE_TESTS", "1")
    env = runner.environment("offline", tmp_path)
    assert env["RDS_HOST"] == "" and env["RDS_TEST_PORT"] == "1"
    assert env["OPENAI_API_KEY"] == "" and env["LANGFUSE_SECRET_KEY"] == ""
    assert "CHAT_TFT_RUN_CONFIGURED_DB_SMOKE_TESTS" not in env
    assert env["TFT_MEDIA_DIR"] == str(tmp_path / "media")
    assert env["VOD_GDRIVE_TOKEN_FILE"] == str(tmp_path / "vod/gdrive/token.json")
    assert env["VOD_GDRIVE_CLIENT_FILE"] == ""


@pytest.mark.parametrize("contents", ["<testsuite tests='0'/>", "<testsuite tests='1' skipped='1'/>"])
def test_required_tier_rejects_empty_or_skipped_inventory(tmp_path, contents):
    """A green pytest exit code cannot conceal a missing integration capability."""
    (tmp_path / "postgres.xml").write_text(contents)
    with pytest.raises(RuntimeError, match="did not fully execute"):
        runner.junit_summary(tmp_path, required=True)


def test_bounded_failure_preserves_diagnostics_and_reaps_child(tmp_path):
    """Kill only a disposable hung command and retain its failure status and log."""
    result = runner.execute("stall", tmp_path, [sys.executable, "-u", "-c", "import time; print('started'); time.sleep(60)"],
                            dict(os.environ), tmp_path, timeout=0.3)
    assert result["exit_code"] == 124
    assert result["seconds"] < 8
    assert "started" in (tmp_path / "stall.log").read_text()


def test_declared_commands_are_inspectable_without_dependencies(tmp_path):
    """Listing tiers does not install packages, open databases, or create output."""
    result = subprocess.run([sys.executable, str(ROOT / "scripts/test_suite.py"), "--tier", "postgres", "--list", "--output", str(tmp_path / "absent")],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    jobs = json.loads(result.stdout)
    assert len(jobs) == 1 and "--require-test-database" in jobs[0]["command"]
    assert not (tmp_path / "absent").exists()
