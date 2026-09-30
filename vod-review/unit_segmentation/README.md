# Unit bounding-box detection

This package trains and runs an Ultralytics YOLO object detector that locates
units with bounding boxes. It no longer produces pixel-level segmentation masks.

## Dataset

Use the standard YOLO detection layout. Each label row is:

```text
class_id x_center y_center width height
```

Coordinates are normalized from `0` to `1`. For a single unit class, every row
starts with `0`.

```text
dataset/
  data.yaml
  images/
    train/
    val/
  labels/
    train/
    val/
```

Example `data.yaml`:

```yaml
path: /absolute/path/to/dataset
train: images/train
val: images/val
names:
  0: unit
```

Keep frames from the same source video in one split to prevent leakage.

The local annotation workspace creates this layout beneath
`data/datasets/unit_segmentation/`, including `data.yaml`. Saving a frame with
no boxes creates an empty YOLO label file, which is a valid negative example.
Each source video is locked to one split for this task after its first save or
skip.

## Training

After `uv sync`, fine-tune the pretrained nano detection model:

```bash
uv run python -m unit_segmentation.train \
  --data /path/to/dataset/data.yaml \
  --model yolo26n.pt \
  --epochs 100 \
  --image-size 640 \
  --batch-size 16
```

Ultralytics writes checkpoints and metrics beneath
`artifacts/unit-detection/train/`. The best checkpoint is normally
`weights/best.pt` inside that run directory.

## Inference

Run the trained detector over every image below `frames/`:

```bash
uv run python -m unit_segmentation.inference \
  --model artifacts/unit-detection/train/weights/best.pt \
  --frames-dir frames \
  --output-dir output
```

Annotated images are written below `output/images/`. Detection text files are
written below `output/labels/` in YOLO format with confidence appended to each
row. Source subdirectories are preserved.
