# Augment template matcher

This package detects TFT augment artwork with normalized template matching. It
does not use PyTorch and has no training step.

Store one or more reference images under a directory named for each label:

```text
templates/
  jeweled_lotus/
    standard.png
  tiny_titans/
    standard.png
    alternate.png
```

The annotation workspace writes captured video frames to
`data/datasets/augment_classifier/templates/<label>/`, which can be passed
directly to `--templates`.

Reference images should be tightly cropped from the same UI scale and visual
theme as the images being searched. Use multiple templates or `--scales` when
the source UI can render an augment at different sizes.

Run detection from the repository root:

```bash
uv run python -m augment_classifier.detect frame.png \
  --templates templates \
  --threshold 0.85 \
  --scales 0.9,1.0,1.1
```

The command prints JSON detections containing the label, confidence, bounding
box, and matched template path. Overlapping candidates are collapsed with
non-maximum suppression.
