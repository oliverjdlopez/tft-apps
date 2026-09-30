"""Render a portable, interactive HTML report without a server or chart dependency."""

import json
from pathlib import Path


def render_report(report):
    """Embed escaped JSON in the local report template without executable run content."""
    payload = (
        json.dumps(report, ensure_ascii=True, allow_nan=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return (
        Path(__file__)
        .with_name("report.html")
        .read_text(encoding="utf-8")
        .replace("__BENCHMARK_DATA__", payload)
    )
