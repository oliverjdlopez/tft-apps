"""Human-review artifacts for discovered unit clusters."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from unit_id.clustering import DiscoveryResult
from unit_id.data import ImageRecord, load_record_image


THUMBNAIL_SIZE = 144
LABEL_HEIGHT = 36


def _contact_sheet(entries: list[tuple[ImageRecord, str]], output: Path, columns: int = 4) -> None:
    if not entries:
        return
    rows = (len(entries) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * THUMBNAIL_SIZE, rows * (THUMBNAIL_SIZE + LABEL_HEIGHT)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for index, (record, caption) in enumerate(entries):
        x = (index % columns) * THUMBNAIL_SIZE
        y = (index // columns) * (THUMBNAIL_SIZE + LABEL_HEIGHT)
        thumbnail = load_record_image(record)
        thumbnail.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
        image_x = x + (THUMBNAIL_SIZE - thumbnail.width) // 2
        image_y = y + (THUMBNAIL_SIZE - thumbnail.height) // 2
        sheet.paste(thumbnail, (image_x, image_y))
        draw.text((x + 3, y + THUMBNAIL_SIZE + 2), caption[:42], fill="black")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="JPEG", quality=90)


def generate_audit_report(
    records: list[ImageRecord],
    result: DiscoveryResult,
    output_dir: Path,
    *,
    examples_per_view: int = 12,
) -> dict[str, object]:
    """Write representative, outlier, and ambiguity montages plus HTML/JSON."""
    if examples_per_view < 1:
        raise ValueError("examples_per_view must be at least 1")
    output_dir.mkdir(parents=True, exist_ok=True)
    assigned_scores = result.similarities[np.arange(len(records)), result.assignments]
    sorted_scores = np.sort(result.similarities, axis=1)
    margins = sorted_scores[:, -1] - sorted_scores[:, -2]

    clusters: list[dict[str, object]] = []
    for cluster in range(result.centroids.shape[0]):
        members = np.flatnonzero(result.assignments == cluster)
        nearest = members[np.argsort(-assigned_scores[members], kind="stable")][
            :examples_per_view
        ]
        outliers = members[np.argsort(assigned_scores[members], kind="stable")][
            :examples_per_view
        ]
        label_id = f"cluster_{cluster:03d}"
        representative_file = f"{label_id}_representatives.jpg"
        outlier_file = f"{label_id}_outliers.jpg"
        _contact_sheet(
            [(records[index], f"{assigned_scores[index]:.3f} {records[index].relative_path}") for index in nearest],
            output_dir / representative_file,
        )
        _contact_sheet(
            [(records[index], f"{assigned_scores[index]:.3f} {records[index].relative_path}") for index in outliers],
            output_dir / outlier_file,
        )
        clusters.append(
            {
                "label_id": label_id,
                "size": int(len(members)),
                "representatives": representative_file,
                "outliers": outlier_file,
                "similarity_minimum": float(assigned_scores[members].min()),
                "similarity_mean": float(assigned_scores[members].mean()),
                "similarity_maximum": float(assigned_scores[members].max()),
            }
        )

    ambiguous = np.argsort(margins, kind="stable")[:examples_per_view]
    ambiguous_file = "smallest_margins.jpg"
    ambiguous_examples = []
    for index in ambiguous:
        ordering = np.argsort(-result.similarities[index], kind="stable")
        ambiguous_examples.append(
            {
                "path": records[index].relative_path,
                "top_two_margin": float(margins[index]),
                "candidates": [
                    {
                        "label_id": f"cluster_{int(candidate):03d}",
                        "cosine_similarity": float(result.similarities[index, candidate]),
                    }
                    for candidate in ordering
                ],
            }
        )
    _contact_sheet(
        [
            (
                records[index],
                f"{int(np.argsort(-result.similarities[index])[0]):03d}/"
                f"{int(np.argsort(-result.similarities[index])[1]):03d} "
                f"m={margins[index]:.3f} {records[index].relative_path}",
            )
            for index in ambiguous
        ],
        output_dir / ambiguous_file,
    )

    by_hash: dict[str, list[str]] = defaultdict(list)
    for record in records:
        by_hash[record.content_sha256 or record.sha256].append(record.relative_path)
    duplicates = [paths for paths in by_hash.values() if len(paths) > 1]
    report: dict[str, object] = {
        "metrics": result.metrics,
        "clusters": clusters,
        "smallest_margins": ambiguous_file,
        "smallest_margin_examples": ambiguous_examples,
        "exact_duplicate_groups": duplicates,
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    sections = []
    for cluster in clusters:
        sections.append(
            f"<section><h2>{html.escape(str(cluster['label_id']))} "
            f"({cluster['size']} crops)</h2>"
            f"<p>Assigned similarity: {cluster['similarity_minimum']:.3f}–"
            f"{cluster['similarity_maximum']:.3f}; mean {cluster['similarity_mean']:.3f}</p>"
            f"<h3>Representatives</h3><img src=\"{cluster['representatives']}\">"
            f"<h3>Outliers</h3><img src=\"{cluster['outliers']}\"></section>"
        )
    metrics_json = html.escape(json.dumps(result.metrics, indent=2))
    duplicate_json = html.escape(json.dumps(duplicates, indent=2))
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Unit discovery audit</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem}}img{{max-width:100%;border:1px solid #ccc}}pre{{background:#f4f4f4;padding:1rem;overflow:auto}}section{{border-top:1px solid #ddd;margin-top:2rem}}</style>
</head><body><h1>Unit discovery audit</h1>
<p>Cosine similarities are ranking scores, not calibrated probabilities. Review representatives, outliers, and ambiguous crops before accepting this artifact.</p>
<h2>Metrics</h2><pre>{metrics_json}</pre>
<h2>Smallest top-two margins</h2><img src="{ambiguous_file}">
<h2>Exact duplicate groups</h2><pre>{duplicate_json}</pre>
{''.join(sections)}</body></html>
"""
    (output_dir / "index.html").write_text(page, encoding="utf-8")
    return report
