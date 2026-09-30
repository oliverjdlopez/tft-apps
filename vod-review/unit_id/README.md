# Unsupervised unit identification

This package discovers exactly `N` recurring visual identities from the unit
boxes in the `unit_segmentation` dataset. It uses a frozen, pretrained DINOv2
ViT-S/14 backbone, PCA, and normalized k-means. No unit-name annotation is
required.

The discovered names are opaque (`cluster_000`, `cluster_001`, and so on).
They are stable when loading a saved artifact, but a newly trained roster is a
new ID namespace. The system cannot infer semantic names such as character
names without a separate reference or one-time cluster-naming step.

## Dataset

Pass the root of the existing YOLO detection dataset produced by
`unit_segmentation`:

```text
data/datasets/unit_segmentation/
  images/
    train/
      frame-a.png
    val/
      frame-b.png
  labels/
    train/
      frame-a.txt
    val/
      frame-b.txt
```

Every non-empty label row must use YOLO detection format:

```text
class_id x_center y_center width height
```

The loader pairs files by their paths below `images/` and `labels/`, requires
class ID `0`, converts every bounding box into an independent unit crop in
memory, and combines both splits for unsupervised discovery. It does not write
or retain duplicate crop images. Empty label files are valid negative detector
frames and yield no unit-ID samples. A missing or malformed corresponding label
file is reported as an error.

Every one of the `N` identities must occur in the boxes often enough to form a
cluster. Avoid collecting many adjacent, nearly identical video frames because
they can dominate a cluster.

## Discover identities

After `uv sync`, run:

```bash
uv run python -m unit_id.train \
  --data-dir data/datasets/unit_segmentation \
  --num-classes 60 \
  --output artifacts/unit-id/roster-2026-08 \
  --device cuda
```

The first run downloads a pinned revision of the official DINOv2 repository and
pretrained weights through PyTorch Hub. The revision is recorded in the model
metadata. On an RTX 4070, feature extraction is the only substantial GPU work;
PCA and clustering run on CPU. Subsequent runs reuse
`embeddings-cache.npz` for boxes whose source image and YOLO row have not
changed.

The artifact contains:

- `metadata.json` and `model.npz`: portable inference state.
- `assignments.jsonl`: each source image and box, its discovered assignment,
  all `N` ranked candidates, and their scores.
- `audit/index.html`: cropped representatives, outliers, ambiguous examples,
  metrics, and exact-duplicate groups.
- `embeddings-cache.npz`: resumable training cache, not required for inference.

Review the audit report before accepting the artifact. Silhouette and bootstrap
adjusted-rand scores measure separation and stability, but cannot prove that a
cluster represents one semantic unit.

## Ranked inference

Classify one already-cropped image or every crop image beneath a directory:

```bash
uv run python -m unit_id.predict /path/to/new-crops \
  --artifact artifacts/unit-id/roster-2026-08 \
  --output predictions.jsonl \
  --device cuda
```

By default, every result contains all `N` labels sorted by cosine similarity,
plus the top-two margin. `--top-k K` can reduce output size. Cosine similarities
are ranking scores, not calibrated probabilities, and the classifier does not
silently reject difficult crops as `unknown`.

For a detector pipeline that already has crops in memory, instantiate
`UnitIdentifier(artifact_path)` and call `predict_batch(crops)`. It accepts PIL
images or NumPy image arrays and returns the same ranked candidate objects.

## Existing annotation workspace

The supervised `unit_id` annotation task remains available, but its named class
folders are not used by this discovery workflow.
