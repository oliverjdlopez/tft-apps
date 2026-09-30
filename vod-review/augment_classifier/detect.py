from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from augment_classifier.detector import TemplateMatcher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect TFT augments with template matching")
    parser.add_argument("image", type=Path)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument(
        "--scales",
        default="1.0",
        help="Comma-separated template scales, for example 0.9,1.0,1.1",
    )
    parser.add_argument("--nms-iou", type=float, default=0.3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read input image: {args.image}")
    matcher = TemplateMatcher(
        args.templates,
        threshold=args.threshold,
        scales=(float(value) for value in args.scales.split(",")),
        nms_iou_threshold=args.nms_iou,
    )
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    print(json.dumps([detection.to_dict() for detection in matcher.detect(rgb_image)], indent=2))


if __name__ == "__main__":
    main()
