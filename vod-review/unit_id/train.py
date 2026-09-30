"""Discover exactly N unit identities from unlabeled crop images."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from unit_id.artifact import UnitIdArtifact
from unit_id.audit import generate_audit_report
from unit_id.clustering import DiscoveryResult, discover_clusters
from unit_id.data import (
    ImageRecord,
    dataset_fingerprint,
    inspect_unit_segmentation_dataset,
)
from unit_id.embeddings import (
    DEFAULT_BACKBONE,
    DINOv2Embedder,
    PathEmbedder,
    extract_with_cache,
)
from unit_id.preprocessing import DEFAULT_IMAGE_SIZE


def _assignment_rows(
    records: list[ImageRecord], result: DiscoveryResult
) -> list[dict[str, Any]]:
    sorted_scores = np.sort(result.similarities, axis=1)
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        assignment = int(result.assignments[index])
        ordering = np.argsort(-result.similarities[index], kind="stable")
        rows.append(
            {
                "path": record.relative_path,
                "source_image": record.relative_path.rsplit("#box-", 1)[0],
                "bounding_box": (
                    {
                        "x_center": record.normalized_box[0],
                        "y_center": record.normalized_box[1],
                        "width": record.normalized_box[2],
                        "height": record.normalized_box[3],
                    }
                    if record.normalized_box is not None
                    else None
                ),
                "sha256": record.sha256,
                "label_id": f"cluster_{assignment:03d}",
                "cosine_similarity": float(result.similarities[index, assignment]),
                "top_two_margin": float(sorted_scores[index, -1] - sorted_scores[index, -2]),
                "candidates": [
                    {
                        "label_id": f"cluster_{int(candidate):03d}",
                        "rank": rank,
                        "cosine_similarity": float(result.similarities[index, candidate]),
                    }
                    for rank, candidate in enumerate(ordering, start=1)
                ],
            }
        )
    return rows


def train_discovery(
    data_dir: Path,
    output_dir: Path,
    num_classes: int,
    *,
    backbone: str = DEFAULT_BACKBONE,
    image_size: int = DEFAULT_IMAGE_SIZE,
    batch_size: int = 64,
    device: str | None = None,
    pca_dimensions: int = 128,
    seed: int = 0,
    n_init: int = 20,
    stability_runs: int = 5,
    examples_per_view: int = 12,
    embedder: PathEmbedder | None = None,
) -> UnitIdArtifact:
    if num_classes < 2:
        raise ValueError("num_classes must be at least 2")
    if image_size < 1:
        raise ValueError("image_size must be at least 1")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    records = inspect_unit_segmentation_dataset(data_dir)
    if len(records) < num_classes:
        raise ValueError(f"Need at least {num_classes} unit boxes, found {len(records)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    embedder = embedder or DINOv2Embedder(backbone, device, image_size)
    if embedder.backbone != backbone or embedder.image_size != image_size:
        raise ValueError("Embedder configuration does not match requested backbone preprocessing")
    embeddings = extract_with_cache(
        records, embedder, output_dir / "embeddings-cache.npz", batch_size
    )
    result = discover_clusters(
        embeddings,
        [record.relative_path for record in records],
        num_classes,
        pca_dimensions=pca_dimensions,
        seed=seed,
        n_init=n_init,
        stability_runs=stability_runs,
    )
    metadata: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "num_classes": num_classes,
        "cluster_ids": [f"cluster_{index:03d}" for index in range(num_classes)],
        "backbone": backbone,
        "backbone_repository": str(
            getattr(embedder, "backbone_repository", "custom-or-test-embedder")
        ),
        "image_size": image_size,
        "preprocessing_version": 1,
        "embedding_dimensions": int(embeddings.shape[1]),
        "dataset_fingerprint": dataset_fingerprint(records),
        "dataset_size": len(records),
        "source_dataset_format": "unit_segmentation_yolo",
        "random_seed": seed,
        "kmeans_n_init": n_init,
        "metrics": result.metrics,
        "score_semantics": "cosine_similarity_not_calibrated_probability",
    }
    artifact = UnitIdArtifact(
        metadata=metadata,
        pca_mean=result.pca_mean,
        pca_components=result.pca_components,
        centroids=result.centroids,
    )
    artifact.save(output_dir)
    rows = _assignment_rows(records, result)
    (output_dir / "assignments.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    generate_audit_report(
        records,
        result,
        output_dir / "audit",
        examples_per_view=examples_per_view,
    )
    return artifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover exactly N visual unit identities from unit_segmentation boxes"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="unit_segmentation YOLO root containing images/ and labels/",
    )
    parser.add_argument("--num-classes", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backbone", default=DEFAULT_BACKBONE)
    parser.add_argument("--image-size", type=int, default=DEFAULT_IMAGE_SIZE)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", help="PyTorch device such as cpu, cuda, or cuda:0")
    parser.add_argument("--pca-dimensions", type=int, default=128)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-init", type=int, default=20)
    parser.add_argument("--stability-runs", type=int, default=5)
    parser.add_argument("--examples-per-view", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact = train_discovery(
        data_dir=args.data_dir,
        output_dir=args.output,
        num_classes=args.num_classes,
        backbone=args.backbone,
        image_size=args.image_size,
        batch_size=args.batch_size,
        device=args.device,
        pca_dimensions=args.pca_dimensions,
        seed=args.seed,
        n_init=args.n_init,
        stability_runs=args.stability_runs,
        examples_per_view=args.examples_per_view,
    )
    print(
        json.dumps(
            {
                "artifact": str(args.output),
                "num_classes": artifact.num_classes,
                "metrics": artifact.metadata["metrics"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
