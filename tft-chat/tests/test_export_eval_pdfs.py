"""Verify recent-run selection and document export without model calls."""
from copy import deepcopy
import json
import sqlite3

import pytest

from scripts.export_eval_pdfs import main as exporter


@pytest.fixture
def saved_jobs(tmp_path):
    """Build an isolated runner-shaped database with old, pending, and failed jobs."""
    database = tmp_path / "jobs.sqlite3"
    bundle = {"schema_version": 3, "dataset_name": "chattft/unit-expert",
              "suite": {"name": "unit-expert"}, "config": {"cases": ["a", "b"]}, "items": [
                  {"id": "a", "input": "Exact input\n\n第二段"},
                  {"id": "b", "input": {"question": "structured"}},
                  {"id": "excluded", "input": "UNSELECTED"},
                  {"id": "archived", "status": "ARCHIVED", "input": "ARCHIVED"}]}
    report = {"experiments": [{"name": "baseline", "items": [
        {"id": "b", "result": "", "execution_error": "Timed out"},
        {"id": "a", "result": "**Exact output**\n\nα ≥ β", "tool_calls": [{"name": "PRIVATE_TOOL"}]}]}]}
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE jobs (id TEXT, state TEXT, created REAL, bundle TEXT, result TEXT, error TEXT)")
        for identity, state, created in [("old", "completed", 1), ("latest", "failed", 2),
                                          ("pending", "awaiting_scores", 3), ("export", "exported", 4),
                                          ("interrupted", "interrupted", 5)]:
            connection.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                               (identity, state, created, json.dumps(bundle), json.dumps(report), None))
        other = deepcopy(bundle)
        other.update(dataset_name="chattft/item-expert", suite={"name": "item-expert"})
        connection.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                           ("other", "completed", 1.5, json.dumps(other), json.dumps(report), None))
    return database


def test_select_latest_per_dataset_read_only(saved_jobs):
    """Select failed runs too, exclude unfinished jobs, and leave source bytes intact."""
    original = saved_jobs.read_bytes()
    jobs = exporter.read_latest_runs(saved_jobs)
    assert [job["id"] for job in jobs] == ["latest", "other"]
    assert [job["id"] for job in exporter.read_latest_runs(saved_jobs, recent=2)] == ["latest", "other", "old"]
    assert [job["id"] for job in exporter.read_latest_runs(saved_jobs, datasets=["unit-expert"])] == ["latest"]
    assert saved_jobs.read_bytes() == original
    with pytest.raises(ValueError, match="No finished evaluations for"):
        exporter.read_latest_runs(saved_jobs, datasets=["missing"])
    with pytest.raises(ValueError, match="at least 1"):
        exporter.read_latest_runs(saved_jobs, recent=0)


def test_inputs_outputs_order_and_missing_answers(saved_jobs):
    """Preserve content and frozen ordering despite out-of-order experiment results."""
    jobs = exporter.read_latest_runs(saved_jobs, datasets=["unit-expert"])
    text = exporter.render_markdown(jobs)
    assert "Exact input\n\n第二段" in text and "**Exact output**\n\nα ≥ β" in text
    assert text.index("#### Eval 1: a") < text.index("#### Eval 2: b")
    assert text.count("##### Input") == text.count("##### Output") == 2
    assert "No final response recorded." in text and "Execution error: Timed out" in text
    assert '```json\n{\n  "question": "structured"\n}\n```' in text
    assert all(value not in text for value in ["UNSELECTED", "ARCHIVED", "PRIVATE_TOOL"])
    jobs[0]["result"] = {}
    jobs[0]["error"] = "Early failure"
    text = exporter.render_markdown(jobs)
    assert text.count("No final response recorded.") == 2 and "Early failure" in text


@pytest.mark.parametrize("wrapped", [True, False])
def test_explicit_wrapper_flag_preserves_structured_outputs(saved_jobs, wrapped):
    """Distinguish a legacy execution wrapper from an answer with an output field."""
    jobs = exporter.read_latest_runs(saved_jobs, datasets=["unit-expert"])
    row = jobs[0]["result"]["experiments"][0]["items"][1]
    row.update(result={"output": "answer", "metadata": "answer field", "error": False},
               result_is_execution_wrapper=wrapped)
    text = exporter.render_markdown(jobs)
    assert ('"metadata": "answer field"' in text) is not wrapped
    assert "answer" in text


def test_missing_database_is_not_created(tmp_path, capsys):
    """Reject an absent database before making an output directory."""
    database, output = tmp_path / "absent.sqlite3", tmp_path / "output"
    assert exporter.main(["--database", str(database), "--output-dir", str(output)]) == 1
    assert not database.exists() and not output.exists()
    assert "Export failed" in capsys.readouterr().err


def test_pdf_failure_keeps_markdown_and_source(saved_jobs, tmp_path, monkeypatch, capsys):
    """Return failure while retaining Markdown when the PDF library cannot load."""
    def unavailable(markdown):
        """Simulate a missing optional renderer."""
        raise ImportError("No module named 'weasyprint'")

    monkeypatch.setattr(exporter, "render_pdf", unavailable)
    original = saved_jobs.read_bytes()
    output = tmp_path / "output"
    assert exporter.main(["--database", str(saved_jobs), "--output-dir", str(output)]) == 1
    assert (output / "latest-evals.md").is_file() and not (output / "latest-evals.pdf").exists()
    assert "uv sync --extra eval-pdfs" in capsys.readouterr().err
    assert saved_jobs.read_bytes() == original


def test_real_pdf_export(saved_jobs, tmp_path, capsys):
    """Render actual PDFs, including Markdown tables and Unicode, when installed."""
    pytest.importorskip("weasyprint")
    from scripts.export_eval_pdfs.utils import document_stem

    output = tmp_path / "documents"
    assert exporter.main(["--database", str(saved_jobs), "--output-dir", str(output)]) == 0
    assert len(list(output.glob("*.md"))) == len(list(output.glob("*.pdf"))) == 3
    assert "Exported 2 saved runs" in capsys.readouterr().out
    for pdf in output.glob("*.pdf"):
        assert pdf.read_bytes().startswith(b"%PDF-") and pdf.stat().st_size > 1000
    dataset = output / (document_stem("chattft/unit-expert") + ".md")
    assert "unit\\-expert" in dataset.read_text() and "item\\-expert" not in dataset.read_text()
    markdown = '| A | B |\n| --- | --- |\n| α | β |\n\n<script>bad()</script>\n\n![private](file:///secret)'
    assert exporter.render_pdf(markdown).startswith(b"%PDF-")


def test_pdf_rendering_disables_external_resources(monkeypatch):
    """Inspect generated HTML and reject external fetches while preserving alt text."""
    weasyprint = pytest.importorskip("weasyprint")
    captured = {}

    class CapturingHTML:
        """Capture the document at the renderer boundary."""

        def __init__(self, **kwargs):
            """Record HTML and the resource policy."""
            captured.update(kwargs)

        def write_pdf(self, **kwargs):
            """Return a fake PDF after HTML parsing has occurred."""
            return b"%PDF-test"

    monkeypatch.setattr(weasyprint, "HTML", CapturingHTML)
    assert exporter.render_pdf('| A |\n| --- |\n| β |\n\n<script>bad()</script>\n\n![private](https://example.com/secret)\n\n![local](file:///secret)') == b"%PDF-test"
    assert "<table>" in captured["string"] and "&lt;script&gt;" in captured["string"]
    assert "[Image: private]" in captured["string"] and "<img" not in captured["string"]
    with pytest.raises(ValueError, match="External resources"):
        captured["url_fetcher"]("file:///secret")
