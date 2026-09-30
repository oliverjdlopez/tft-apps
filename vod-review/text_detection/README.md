# Text bounding-box detection

This package fine-tunes and runs an Ultralytics YOLO object detector that finds
visible text regions. It detects where text appears; it does not transcribe the
text.

## Dataset

Use standard YOLO detection data. Each label row is
`class_id x_center y_center width height`, with coordinates normalized from 0
to 1. This detector has one class, `text`, so every row starts with `0`.

```text
dataset/
  data.yaml
  images/{train,val}/
  labels/{train,val}/
```

The annotation workspace creates this layout under
`data/datasets/text_detection/`. Empty label files are valid negative examples.

## Training

The default checkpoint is a text-specific YOLO11n model from
[`RoyRud1902/yolo11n-text`](https://huggingface.co/RoyRud1902/yolo11n-text).
The first inference or training command downloads it to
`artifacts/text-detection/train/weights/best.pt`. You can use it directly
without training, or fine-tune it briefly on the TFT screenshots:

```bash
uv run python -m text_detection.train \
  --data data/datasets/text_detection/data.yaml \
  --epochs 10
```

Training starts from and updates
`artifacts/text-detection/train/weights/best.pt`. Pass `--model` only to use a
different local checkpoint.

## Inference

```bash
uv run python -m text_detection.inference \
  --images-dir frames \
  --output-dir output/text-detection
```

Annotated images are written under `output/text-detection/images/`; YOLO label
files with confidence values are written under `output/text-detection/labels/`.
