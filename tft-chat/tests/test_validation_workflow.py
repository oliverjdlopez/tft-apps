"""Protect executable CI commands and explicitly paid baseline dispatch."""

from pathlib import Path
import subprocess
import sys

import yaml

from evals.baselines import validate_baselines

ROOT = Path(__file__).resolve().parents[2]


def test_manual_workflow_choices_resolve_reviewed_baselines():
    """Every offered suite resolves to authored cases and the current paid CLI."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/evals.yml").read_text())
    # YAML 1.1 maps the unquoted GitHub key 'on' to True.
    trigger = workflow.get("on", workflow.get(True))
    choices = trigger["workflow_dispatch"]["inputs"]["suite"]["options"]
    assert set(choices) <= set(validate_baselines())
    commands = "\n".join(step.get("run", "") for step in workflow["jobs"]["evaluate"]["steps"])
    assert "--selection-live" not in commands
    assert "evals.baseline_run" in commands
    result = subprocess.run([sys.executable, "-m", "evals.baseline_run", "--help"], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and "--data-snapshot-label" in result.stdout


def test_required_ci_tiers_are_declared_once():
    """A duplicated adapter run or an omitted composition dependency cannot drift back."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    commands = "\n".join(step.get("run", "") for step in jobs["test"]["steps"])
    assert "--extra compositions --group test" in commands
    assert "--tier offline --component chat" in commands
    assert "--tier postgres --component chat" in commands
    assert "pytest -q evals/langfuse/tests" not in commands
    assert {"browser", "native", "pdf"} <= jobs.keys()
    assert all(job.get("timeout-minutes") for job in jobs.values())
