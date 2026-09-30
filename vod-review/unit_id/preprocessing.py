"""Aspect-ratio-preserving preprocessing for unit crops."""

from __future__ import annotations

from PIL import Image
import torch
from torchvision.transforms import functional


DEFAULT_IMAGE_SIZE = 224
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def letterbox(image: Image.Image, size: int = DEFAULT_IMAGE_SIZE) -> Image.Image:
    """Fit an RGB image inside a square black canvas without cropping it."""
    if size < 1:
        raise ValueError("Image size must be at least 1")
    image = image.convert("RGB")
    scale = min(size / image.width, size / image.height)
    resized_width = max(1, min(size, round(image.width * scale)))
    resized_height = max(1, min(size, round(image.height * scale)))
    resized = image.resize((resized_width, resized_height), Image.Resampling.BICUBIC)
    canvas = Image.new("RGB", (size, size), (0, 0, 0))
    canvas.paste(resized, ((size - resized_width) // 2, (size - resized_height) // 2))
    return canvas


def prepare_image(image: Image.Image, size: int = DEFAULT_IMAGE_SIZE) -> torch.Tensor:
    tensor = functional.pil_to_tensor(letterbox(image, size)).to(torch.float32).div_(255.0)
    return functional.normalize(tensor, IMAGENET_MEAN, IMAGENET_STD)
