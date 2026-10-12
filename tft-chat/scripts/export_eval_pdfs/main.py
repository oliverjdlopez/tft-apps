"""Export the latest finished local dataset evaluations without rerunning them."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys

from .utils import atomic_write, block_resource, content, dataset_name, document_stem, heading, image_label

CHAT_ROOT = Path(__file__).resolve().parents[2]
PRINT_CSS = """
@page { size: A4; margin: 18mm;
  @bottom-right { content: counter(page); font-size: 9pt; color: #666; } }
body { font: 10pt/1.5 "DejaVu Sans", sans-serif; color: #202020; }
h1, h2, h3, h4, h5, h6 { break-after: avoid; line-height: 1.25; }
h2 { border-bottom: 1px solid #bbb; padding-bottom: 5pt; }
h4 { margin-top: 20pt; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; }
th, td { border: 1px solid #ccc; padding: 4pt; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 8pt; background: #f4f4f4; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt; }
p, li, a { overflow-wrap: anywhere; }
blockquote { border-left: 2pt solid #bbb; margin-left: 0; padding-left: 10pt; }
"""


def read_latest_runs(database: Path, *, recent: int = 1, datasets: list[str] | None = None) -> list[dict]:
    """Read the newest finished jobs per dataset using a read-only SQLite snapshot.

    Args:
        database: Existing runner jobs database; never initialized or migrated.
        recent: Number of runs per dataset, ordered by submission time.
        datasets: Optional frozen dataset or suite names to include.

    Returns:
        Selected jobs in newest-first order, with decoded frozen bundles/results.

    Raises:
        ValueError: Selection is empty, a filter is absent, or recent is invalid.
    """
    if recent < 1:
        raise ValueError("--recent must be at least 1")
    requested = set(datasets or [])
    matched: set[str] = set()
    counts: Counter = Counter()
    selected = []
    # Avoid JobStore: its constructor creates directories/tables. mode=ro also
    # prevents a typo in --database from silently creating an empty database.
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for row in connection.execute(
            "SELECT id,state,created,bundle,result,error FROM jobs "
            "WHERE state IN ('completed','failed') ORDER BY created DESC,id DESC"
        ):
            bundle = json.loads(row["bundle"])
            if "suite" not in bundle or "items" not in bundle:
                continue
            name = dataset_name(bundle)
            aliases = {name, bundle["suite"]["name"]}
            if requested and not requested.intersection(aliases):
                continue
            matched.update(requested.intersection(aliases))
            if counts[name] >= recent:
                continue
            job = dict(row)
            job.update(bundle=bundle, result=json.loads(row["result"] or "{}"))
            selected.append(job)
            counts[name] += 1
    if requested - matched:
        raise ValueError("No finished evaluations for: " + ", ".join(sorted(requested - matched)))
    if not selected:
        raise ValueError("No finished dataset evaluations found")
    return selected


def render_markdown(jobs: list[dict]) -> str:
    """List every selected frozen input and final output in saved case order."""
    lines = ["# Latest ChatTFT evaluations", "", "Runs are ordered newest first; cases follow their frozen dataset order.", ""]
    number = 0
    for job in jobs:
        bundle, report = job["bundle"], job["result"]
        created = datetime.fromtimestamp(job["created"], timezone.utc).isoformat()
        lines += ["## " + heading(dataset_name(bundle)), "", "Job: " + heading(job["id"]), "",
                  "Submitted (UTC): " + created, "", "State: " + heading(job["state"]), ""]
        if job["error"] or report.get("grading_error"):
            lines += ["Run error: " + heading(job["error"] or report["grading_error"]), ""]
        chosen = set(bundle.get("config", {}).get("cases", []))
        items = [item for item in bundle["items"] if item.get("status", "ACTIVE") == "ACTIVE"
                 and (not chosen or item["id"] in chosen)]
        for experiment in report.get("experiments") or [{"name": "Run", "items": []}]:
            lines += ["### " + heading(experiment["name"]), ""]
            rows = {row["id"]: row for row in experiment.get("items", [])}
            for item in items:
                number += 1
                row = rows.get(item["id"], {})
                value = row.get("result")
                # Legacy/offline reports wrap output in execution metadata;
                # hosted structured answers may also have an 'output' field.
                wrapper = isinstance(value, dict) and row.get(
                    "result_is_execution_wrapper", bundle.get("schema_version", 1) == 1)
                output = value.get("output") if wrapper else value
                error = row.get("execution_error") or (value.get("error") if wrapper else None)
                lines += [f"#### Eval {number}: " + heading(item["id"]), "", "##### Input", "",
                          content(item["input"]), "", "##### Output", "",
                          "No final response recorded." if output is None or error and output == "" else content(output), ""]
                if error:
                    lines += ["Execution error: " + heading(error), ""]
    return "\n".join(lines)


def render_pdf(markdown: str) -> bytes:
    """Typeset Markdown tables, Unicode text, and code into a paginated PDF.

    Raw HTML stays escaped and image references become alt text, so rendering
    saved assistant output neither loads local files nor makes network requests.
    """
    from markdown_it import MarkdownIt
    from weasyprint import CSS, HTML

    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    parser.renderer.rules["image"] = image_label
    body = parser.render(markdown)
    document = '<!doctype html><html><head><meta charset="utf-8"><title>ChatTFT evaluations</title></head><body>' + body + "</body></html>"
    return HTML(string=document, url_fetcher=block_resource).write_pdf(stylesheets=[CSS(string=PRINT_CSS)])


def export_documents(jobs: list[dict], directory: Path) -> list[Path]:
    """Write a combined document and one Markdown/PDF pair per dataset.

    Markdown is retained if PDF rendering fails, allowing inspection/recovery.
    Files are atomically replaced without changing the source jobs or artifacts.
    """
    groups = {dataset_name(job["bundle"]) for job in jobs}
    documents = [("latest-evals", jobs)] + [
        (document_stem(name), [job for job in jobs if dataset_name(job["bundle"]) == name])
        for name in sorted(groups)
    ]
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for stem, selected in documents:
        markdown = render_markdown(selected)
        md_path, pdf_path = directory / f"{stem}.md", directory / f"{stem}.pdf"
        atomic_write(md_path, markdown.encode("utf-8"))
        atomic_write(pdf_path, render_pdf(markdown))
        paths.extend([md_path, pdf_path])
    return paths


def main(argv: list[str] | None = None) -> int:
    """Run the installed export command with no assistant or grading calls."""
    runtime = Path(os.environ.get("LANGFUSE_RUNTIME_DIR", str(CHAT_ROOT / "evals/langfuse/.runtime")))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=runtime / "jobs.sqlite3", help="Existing runner jobs database")
    parser.add_argument("--output-dir", type=Path, default=CHAT_ROOT / "dev/exports",
                        help="Directory for combined and per-dataset Markdown/PDF pairs (default: dev/exports)")
    parser.add_argument("--dataset", action="append", help="Dataset or suite name; repeat to select several")
    parser.add_argument("--recent", type=int, default=1, help="Newest finished runs per dataset (default: 1)")
    args = parser.parse_args(argv)
    try:
        jobs = read_latest_runs(args.database, recent=args.recent, datasets=args.dataset)
        paths = export_documents(jobs, args.output_dir.resolve())
    except (OSError, ValueError, sqlite3.Error, ImportError) as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        if isinstance(exc, (ImportError, OSError)):
            print("Install PDF dependencies with uv sync --extra eval-pdfs; WeasyPrint also requires system Pango libraries. "
                  "Any Markdown already written remains in the output directory.", file=sys.stderr)
        return 1
    print(f"Exported {len(jobs)} saved runs:")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
