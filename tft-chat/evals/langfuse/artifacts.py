"""Export completed dataset runs as private, readable Markdown artifacts."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re

from .utils import atomic_write, content_hash, markdown_arguments, markdown_content, markdown_scalar

logger = logging.getLogger(__name__)


def render_run_artifact(bundle: dict, report: dict, *, state: str, error: str | None = None) -> str:
    """Render frozen prompts, complete responses, and ordered argument-only traces.

    Args:
        bundle: Frozen dataset inputs and run selection.
        report: Execution reports retained through native grading.
        state: Terminal job outcome, independent of artifact export success.
        error: Optional job-level failure to explain missing responses.

    Returns:
        Markdown covering each selected case for each executed experiment.
    """
    selected = set(bundle.get("config", {}).get("cases", []))
    items = [item for item in bundle["items"] if item.get("status", "ACTIVE") == "ACTIVE"
             and (not selected or item["id"] in selected)]
    lines = ["# Dataset run — prompts, final outputs, and tool arguments", "",
             "Dataset: " + markdown_scalar(bundle.get("dataset_name") or bundle["suite"]["name"]),
             "", "Run outcome: " + markdown_scalar(state), "",
             "Tool calls appear in recorded order. Arguments include explicit nulls; tool return values are omitted.", ""]
    if report.get("started_at"):
        lines += ["Started: " + markdown_scalar(report["started_at"]), ""]
    if error or report.get("grading_error"):
        lines += ["Run error: " + markdown_scalar(error or report["grading_error"]), ""]
    # Even an early failure must say that responses are unavailable, rather than
    # silently producing an empty or apparently successful report.
    experiments = report.get("experiments") or [{"name": "Run", "items": []}]
    for experiment in experiments:
        lines += ["## " + markdown_scalar(experiment["name"]), ""]
        if experiment.get("dataset_run_id"):
            lines += ["Langfuse run ID: " + markdown_scalar(experiment["dataset_run_id"]), ""]
        rows = {row["id"]: row for row in experiment["items"]}
        for item in items:
            row = rows.get(item["id"], {})
            value = row.get("result")
            # Schema-v1 and offline execution retain the execution wrapper;
            # natural hosted runs return the actual assistant output directly.
            wrapper = isinstance(value, dict) and row.get("result_is_execution_wrapper", bundle["schema_version"] == 1)
            output = value.get("output") if wrapper else value
            execution_error = row.get("execution_error") or (value.get("error") if wrapper else None)
            lines += ["### " + markdown_scalar(item["id"]), "", "#### Prompt", "",
                      markdown_content(item["input"]), "", "#### Final output", ""]
            if output is None or execution_error and output == "":
                lines += ["No final response recorded.", ""]
            else:
                lines += [markdown_content(output), ""]
            if execution_error:
                lines += ["Execution error: " + markdown_scalar(execution_error), ""]
            lines += ["#### Tool trace — arguments only", ""]
            calls = row.get("tool_calls")
            if calls is None:
                lines += ["Tool arguments were not captured for this case.", ""]
            elif not calls:
                lines += ["No tool calls recorded.", ""]
            else:
                for number, call in enumerate(calls, 1):
                    lines += [f"##### {number}. " + markdown_scalar(call["name"]), ""]
                    if call.get("agent"):
                        lines += ["Agent: " + markdown_scalar(call["agent"]), ""]
                    arguments = call.get("arguments")
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except ValueError:
                            # Preserve malformed argument text for diagnosis.
                            lines += ["Arguments were not valid JSON; captured text:", "",
                                      markdown_scalar(arguments), ""]
                            continue
                    lines += (markdown_arguments(arguments) if arguments != {} else ["No arguments."]) + [""]
    return "\n".join(lines)


def write_run_artifact(bundle: dict, report: dict, directory: Path, run_id: str,
                       *, state: str, error: str | None = None) -> None:
    """Write a terminal-run artifact and record its path or a separate export error.

    Args:
        bundle: Frozen dataset definition used for the run.
        report: Mutable report receiving ``markdown_artifact`` status.
        directory: Private runtime artifact directory.
        run_id: Unique job or comparison identity used for an idempotent filename.
        state: Terminal evaluation outcome.
        error: Optional job-level execution or grading failure.
    """
    if state not in {"completed", "failed"}:
        raise ValueError("Markdown artifacts require a terminal evaluation outcome")
    safe_id = run_id if re.fullmatch(r"[A-Za-z0-9_-]+", run_id) else content_hash(run_id.encode())
    path = directory.resolve() / f"{safe_id}.md"
    try:
        text = render_run_artifact(bundle, report, state=state, error=error)
        directory.mkdir(parents=True, exist_ok=True)
        atomic_write(path, text.encode("utf-8"))
        report["markdown_artifact"] = {"status": "written", "path": str(path)}
    except Exception as exc:
        # Disk/export failure must not erase results or change grading outcomes.
        report["markdown_artifact"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        logger.exception("Unable to export dataset-run Markdown for %s", run_id)
