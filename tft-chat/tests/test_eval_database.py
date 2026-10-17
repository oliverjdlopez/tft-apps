"""Evaluation target fallback through the captured assistant worker."""

import os
from types import SimpleNamespace

import pytest

from db.session import resolve_database_target as resolve_runtime_database_target
from evals import worker
from evals.database import resolve_eval_target


@pytest.fixture
def app_rds(monkeypatch):
    """Provide synthetic RDS settings without reading local credentials.

    Returns:
        Monkeypatch context for per-case evaluation overrides.
    """
    monkeypatch.setattr("core.config.load_dotenv", lambda *_args, **_kwargs: None)
    for key in os.environ:
        if key.startswith("RDS_"):
            monkeypatch.delenv(key)
    for name, value in {
        "HOST": "app.example", "PORT": "5434", "ADMIN": "app-user",
        "DB": "app_test", "PASSWORD": "app-secret", "INSTANCE_ID": "app-instance",
    }.items():
        monkeypatch.setenv(f"RDS_{name}", value)
    return monkeypatch


@pytest.mark.parametrize("mode", ["missing", "blank", "partial", "explicit", "iam"])
def test_captured_worker_uses_resolved_eval_fallback(app_rds, mode):
    """Captured executions inherit missing fields and preserve explicit values."""
    import evals.assistant_execution as captured_execution
    from devtools.assistants import capture, registry_from_files

    if mode == "blank":
        for name in ("HOST", "PORT", "ADMIN", "DB", "PASSWORD", "INSTANCE_ID"):
            app_rds.setenv(f"RDS_EVAL_{name}", "  ")
    elif mode == "partial":
        app_rds.setenv("RDS_EVAL_DB", "eval_test")
    elif mode == "explicit":
        for name, value in {
            "HOST": "eval.example", "PORT": "5435", "ADMIN": "eval-user",
            "DB": "eval_test", "PASSWORD": "eval-secret", "INSTANCE_ID": "eval-instance",
        }.items():
            app_rds.setenv(f"RDS_EVAL_{name}", value)
    elif mode == "iam":
        app_rds.delenv("RDS_PASSWORD")
        app_rds.delenv("RDS_PORT")

    targets = []

    def run_captured(prompt, config):
        """Record the real database scope without database or model calls."""
        targets.append(resolve_runtime_database_target("app"))
        result = SimpleNamespace(
            final_output="answer",
            context_wrapper=SimpleNamespace(usage=SimpleNamespace(
                input_tokens=0, output_tokens=0, total_tokens=0, requests=0,
            )),
        )
        return result, {"instruction_hashes": {}}

    app_rds.setattr(captured_execution, "run_captured", run_captured)
    app_rds.setattr(worker, "extract_trace", lambda _, **kwargs: SimpleNamespace(
        to_dict=lambda: {}, summary=lambda: "",
    ))
    frozen = capture(registry_from_files({"fixture": {"system.md": "Fixture"}}))
    result = worker.run_assistant("question", {
        "assistant": "fixture", "captured_graph": frozen, "workspace_trial": True,
    }, {})

    target, = targets
    assert result["output"] == "answer"
    assert result["metadata"]["database"] == target.database
    assert target.purpose == "eval"
    assert target.host == ("eval.example" if mode == "explicit" else "app.example")
    assert target.port == (5435 if mode == "explicit" else 5432 if mode == "iam" else 5434)
    assert target.admin == ("eval-user" if mode == "explicit" else "app-user")
    assert target.database == ("eval_test" if mode in {"partial", "explicit"} else "app_test")
    assert target.instance_id == ("eval-instance" if mode == "explicit" else "app-instance")
    assert target.password == ("eval-secret" if mode == "explicit" else "" if mode == "iam" else "app-secret")
    assert target.auth_mode == ("iam" if mode == "iam" else "password")
    assert "secret" not in target.url


def test_named_eval_database_preserves_fallback_coordinates(app_rds):
    """A frozen database name uses inherited coordinates and authentication."""
    target = resolve_eval_target("frozen_test")
    assert target.database == "frozen_test"
    assert target.host == "app.example"
    assert target.port == 5434
    assert target.connect_url == "postgresql://app-user:app-secret@app.example:5434/frozen_test"
    assert "secret" not in target.url


def test_eval_target_rejects_incomplete_resolved_coordinates(app_rds):
    """Fallback still fails when neither target supplies required coordinates."""
    for name in ("HOST", "ADMIN", "DB"):
        app_rds.delenv(f"RDS_{name}")
    with pytest.raises(ValueError, match="incomplete eval RDS configuration"):
        resolve_eval_target()
