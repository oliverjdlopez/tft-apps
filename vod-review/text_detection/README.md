# Runtime text detection

Round OCR imports `text_detection.model` to locate text in each selected crop
before recognition. `profiling.py` records runtime detector timings. These modules
and their tests remain part of the VOD review flow.

The default text-specific YOLO checkpoint is downloaded on first use to
`artifacts/text-detection/train/weights/best.pt`. This legacy path is retained so
existing model files continue to work. Model assets and authored datasets are
preserved. Standalone training and image-export commands have been removed.
