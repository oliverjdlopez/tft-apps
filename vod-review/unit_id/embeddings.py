"""Pretrained DINOv2 feature extraction and resumable embedding caching."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from unit_id.data import ImageRecord, load_record_image
from unit_id.preprocessing import DEFAULT_IMAGE_SIZE, prepare_image


DEFAULT_BACKBONE = "dinov2_vits14"
DEFAULT_BACKBONE_REVISION = "7764ea0f912e53c92e82eb78a2a1631e92725fc8"
DEFAULT_BACKBONE_REPOSITORY = f"facebookresearch/dinov2:{DEFAULT_BACKBONE_REVISION}"


class PathEmbedder(Protocol):
    backbone: str
    image_size: int

    def extract(self, paths: list[Path], batch_size: int) -> np.ndarray: ...

    def extract_records(
        self, records: list[ImageRecord], batch_size: int
    ) -> np.ndarray: ...


class DINOv2Embedder:
    """Batch extractor for an official DINOv2 PyTorch Hub backbone."""

    def __init__(
        self,
        backbone: str = DEFAULT_BACKBONE,
        device: str | None = None,
        image_size: int = DEFAULT_IMAGE_SIZE,
        backbone_repository: str = DEFAULT_BACKBONE_REPOSITORY,
    ) -> None:
        import torch

        if image_size < 14 or image_size % 14:
            raise ValueError("DINOv2 image_size must be a positive multiple of its 14-pixel patch size")
        self.torch = torch
        self.backbone = backbone
        self.backbone_repository = backbone_repository
        self.image_size = image_size
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        try:
            self.model = torch.hub.load(backbone_repository, backbone)
        except Exception as exc:
            raise RuntimeError(
                "Could not load the DINOv2 backbone. The first run requires network "
                "access so PyTorch Hub can download the official repository and weights."
            ) from exc
        self.model.to(self.device).eval()

    def extract(self, paths: list[Path], batch_size: int = 64) -> np.ndarray:
        if batch_size < 1:
            raise ValueError("Batch size must be at least 1")
        batches: list[np.ndarray] = []
        for offset in range(0, len(paths), batch_size):
            images = []
            for path in paths[offset : offset + batch_size]:
                with Image.open(path) as image:
                    images.append(image.convert("RGB"))
            batches.append(self._embed_batch(images))
            print(f"embedded={min(offset + batch_size, len(paths))}/{len(paths)}")
        if not batches:
            return np.empty((0, 0), dtype=np.float32)
        return np.concatenate(batches).astype(np.float32, copy=False)

    def extract_images(self, images: list[Any], batch_size: int = 64) -> np.ndarray:
        """Extract features from PIL images or NumPy-compatible image arrays."""
        if batch_size < 1:
            raise ValueError("Batch size must be at least 1")
        batches: list[np.ndarray] = []
        for offset in range(0, len(images), batch_size):
            pil_images = [
                image.convert("RGB")
                if isinstance(image, Image.Image)
                else Image.fromarray(np.asarray(image)).convert("RGB")
                for image in images[offset : offset + batch_size]
            ]
            batches.append(self._embed_batch(pil_images))
        if not batches:
            return np.empty((0, 0), dtype=np.float32)
        return np.concatenate(batches).astype(np.float32, copy=False)

    def extract_records(
        self, records: list[ImageRecord], batch_size: int = 64
    ) -> np.ndarray:
        """Extract features from bounding-box crop records without materializing files."""
        if batch_size < 1:
            raise ValueError("Batch size must be at least 1")
        batches: list[np.ndarray] = []
        for offset in range(0, len(records), batch_size):
            images = [
                load_record_image(record)
                for record in records[offset : offset + batch_size]
            ]
            batches.append(self._embed_batch(images))
            print(f"embedded={min(offset + batch_size, len(records))}/{len(records)}")
        if not batches:
            return np.empty((0, 0), dtype=np.float32)
        return np.concatenate(batches).astype(np.float32, copy=False)

    def _embed_batch(self, images: list[Image.Image]) -> np.ndarray:
        tensors = [prepare_image(image, self.image_size) for image in images]
        inputs = self.torch.stack(tensors).to(self.device, non_blocking=True)
        with self.torch.inference_mode():
            with self.torch.autocast(
                device_type=self.device.type,
                dtype=self.torch.float16,
                enabled=self.device.type == "cuda",
            ):
                features = self.model(inputs)
        if isinstance(features, dict):
            features = features.get("x_norm_clstoken")
        if features is None or getattr(features, "ndim", None) != 2:
            raise RuntimeError("DINOv2 backbone did not return one feature vector per image")
        features = self.torch.nn.functional.normalize(features.float(), dim=1)
        return features.cpu().numpy()


def _load_cache(
    cache_path: Path, backbone: str, backbone_repository: str, image_size: int
) -> dict[tuple[str, str], np.ndarray]:
    if not cache_path.is_file():
        return {}
    try:
        with np.load(cache_path, allow_pickle=False) as cache:
            metadata = json.loads(str(cache["metadata"].item()))
            if metadata != {
                "backbone": backbone,
                "backbone_repository": backbone_repository,
                "image_size": image_size,
            }:
                return {}
            paths = cache["paths"].tolist()
            hashes = cache["hashes"].tolist()
            embeddings = cache["embeddings"].astype(np.float32)
        return {
            (str(path), str(file_hash)): embedding
            for path, file_hash, embedding in zip(paths, hashes, embeddings, strict=True)
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {}


def _save_cache(
    cache_path: Path,
    records: list[ImageRecord],
    embeddings: np.ndarray,
    backbone: str,
    backbone_repository: str,
    image_size: int,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{cache_path.name}.", suffix=".npz", dir=cache_path.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        np.savez_compressed(
            temporary,
            metadata=np.asarray(
                json.dumps(
                    {
                        "backbone": backbone,
                        "backbone_repository": backbone_repository,
                        "image_size": image_size,
                    }
                )
            ),
            paths=np.asarray([record.relative_path for record in records]),
            hashes=np.asarray([record.sha256 for record in records]),
            embeddings=embeddings.astype(np.float32),
        )
        os.replace(temporary, cache_path)
    finally:
        temporary.unlink(missing_ok=True)


def extract_with_cache(
    records: list[ImageRecord],
    embedder: PathEmbedder,
    cache_path: Path,
    batch_size: int,
) -> np.ndarray:
    """Reuse embeddings whose relative path and content hash are unchanged."""
    backbone_repository = str(
        getattr(embedder, "backbone_repository", "custom-or-test-embedder")
    )
    cached = _load_cache(
        cache_path, embedder.backbone, backbone_repository, embedder.image_size
    )
    missing = [
        record for record in records if (record.relative_path, record.sha256) not in cached
    ]
    if missing:
        extract_records = getattr(embedder, "extract_records", None)
        if extract_records is None:
            if any(record.crop_box is not None for record in missing):
                raise TypeError(
                    "Configured embedder must support extract_records for bounding-box crops"
                )
            new_embeddings = embedder.extract(
                [record.path for record in missing], batch_size
            )
        else:
            new_embeddings = extract_records(missing, batch_size)
        if new_embeddings.shape[0] != len(missing):
            raise RuntimeError("Embedding extractor returned the wrong number of rows")
        cached.update(
            {
                (record.relative_path, record.sha256): embedding
                for record, embedding in zip(missing, new_embeddings, strict=True)
            }
        )
    rows = np.stack([cached[(record.relative_path, record.sha256)] for record in records])
    rows = rows.astype(np.float32, copy=False)
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    if np.any(norms <= 1e-12):
        raise ValueError("Embedding extractor produced a zero-length feature vector")
    rows /= norms
    _save_cache(
        cache_path,
        records,
        rows,
        embedder.backbone,
        backbone_repository,
        embedder.image_size,
    )
    return rows
