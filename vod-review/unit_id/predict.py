"""Ranked inference for a discovered unit-ID artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from unit_id.artifact import UnitIdArtifact
from unit_id.data import discover_images
from unit_id.embeddings import DINOv2Embedder, PathEmbedder


class UnitIdentifier:
    def __init__(
        self,
        artifact_dir: Path,
        *,
        device: str | None = None,
        embedder: PathEmbedder | None = None,
    ) -> None:
        self.artifact = UnitIdArtifact.load(artifact_dir)
        backbone = str(self.artifact.metadata["backbone"])
        backbone_repository = str(self.artifact.metadata.get("backbone_repository", "facebookresearch/dinov2"))
        image_size = int(self.artifact.metadata["image_size"])
        self.embedder = embedder or DINOv2Embedder(
            backbone, device, image_size, backbone_repository
        )
        if self.embedder.backbone != backbone or self.embedder.image_size != image_size:
            raise ValueError("Embedder does not match the artifact backbone and preprocessing")

    def predict_paths(
        self,
        paths: list[Path],
        *,
        batch_size: int = 64,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        if not paths:
            return []
        embeddings = self.embedder.extract(paths, batch_size)
        predictions = self.artifact.ranked_predictions(embeddings, top_k=top_k)
        return [
            {"path": str(path), **prediction}
            for path, prediction in zip(paths, predictions, strict=True)
        ]

    def predict_batch(
        self,
        crops: list[Any],
        *,
        batch_size: int = 64,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Rank identities for in-memory PIL or NumPy crops."""
        if not crops:
            return []
        extract_images = getattr(self.embedder, "extract_images", None)
        if extract_images is None:
            raise TypeError("Configured embedder does not support in-memory images")
        embeddings = extract_images(crops, batch_size)
        return self.artifact.ranked_predictions(embeddings, top_k=top_k)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rank unit identity candidates for crop images")
    parser.add_argument("input", type=Path, help="One image or a directory searched recursively")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="JSONL output; defaults to stdout")
    parser.add_argument("--top-k", type=int, help="Limit candidates; defaults to all N")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", help="PyTorch device such as cpu, cuda, or cuda:0")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = discover_images(args.input) if args.input.is_dir() else [args.input]
    if not paths:
        raise SystemExit(f"No supported images found under {args.input}")
    identifier = UnitIdentifier(args.artifact, device=args.device)
    rows = identifier.predict_paths(paths, batch_size=args.batch_size, top_k=args.top_k)
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
