"""GPU-accelerated template matching with CPU fallback."""
from pathlib import Path
import cv2
import numpy as np
import torch
import torch.nn.functional as F

DETECTION_THRESHOLD = 0.5  # Placeholder, not calibrated against real wisps.
TEMPLATE_PATH = Path(__file__).with_name('generic_wisp.png')


def inference_device():
    """Prefer CUDA, then Apple's MPS backend, and finally the CPU."""
    if torch.cuda.is_available():
        return torch.device('cuda')
    if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        return torch.device('mps')
    return torch.device('cpu')


class TemplateMatcher:
    def __init__(self, template_path=TEMPLATE_PATH, threshold=DETECTION_THRESHOLD):
        self.template = cv2.imread(str(template_path), cv2.IMREAD_UNCHANGED)
        if self.template is None or self.template.size == 0:
            raise ValueError(f'Cannot load wisp template: {template_path}')
        # Preserve the file's channel layout; OpenCV decodes color images as BGR.
        self.grayscale = self.template.ndim == 2
        if not self.grayscale:
            conversion = cv2.COLOR_BGRA2RGB if self.template.shape[2] == 4 else cv2.COLOR_BGR2RGB
            self.template = cv2.cvtColor(self.template, conversion)
        if self.template.dtype != np.uint8:
            raise ValueError('Wisp templates must use 8-bit pixels')
        self.threshold = threshold
        self.device = inference_device()
        self.device_label = self.device.type
        template = self.template[..., None] if self.grayscale else self.template
        self._template = torch.from_numpy(np.ascontiguousarray(template.transpose(2, 0, 1))).to(
            device=self.device, dtype=torch.float32).unsqueeze(0) / 255.0
        self._template_energy = self._template.square().sum()


    def _fit_template(self, height, width):
        h, w = self.template.shape[:2]
        scale = min(1.0, height / h, width / w)
        size = (max(1, min(height, round(h * scale))), max(1, min(width, round(w * scale))))
        if size == (h, w):
            return self._template, self._template_energy
        # The ROI size is normally constant for a video; resize once and reuse.
        if getattr(self, '_fitted_size', None) != size:
            self._fitted_size = size
            self._fitted_template = F.interpolate(self._template, size=size, mode='bilinear', align_corners=False)
            self._fitted_energy = self._fitted_template.square().sum()
        return self._fitted_template, self._fitted_energy

    def predict(self, rgb_crop):
        return self.predict_batch([rgb_crop])[0]

    @torch.inference_mode()
    def predict_batch(self, rgb_crops):
        """Score same-sized video crops, transferring only final scores back."""
        if not rgb_crops:
            return []
        shape = rgb_crops[0].shape
        if any(crop.shape != shape for crop in rgb_crops):
            raise ValueError('Template matching batches must contain same-sized RGB crops')
        if len(shape) != 3 or shape[2] != 3 or shape[0] == 0 or shape[1] == 0:
            raise ValueError('Template matching requires nonempty RGB crops')
        template, template_energy = self._fit_template(shape[0], shape[1])
        h, w = template.shape[-2:]
        crops = [cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)[..., None]
                 if self.grayscale else crop for crop in rgb_crops]
        pixels = torch.from_numpy(np.stack(crops)).to(device=self.device, dtype=torch.float32)
        pixels = pixels.permute(0, 3, 1, 2).contiguous() / 255.0
        # Sum squared differences = patch energy + template energy - 2 * dot product.
        # Disable TF32 here so threshold decisions retain float32 precision.
        if shape[:2] == (h, w):
            # Aligned, equal-sized crops need one comparison, not a convolution search.
            dot = (pixels * template).sum(dim=(1, 2, 3))[:, None, None]
        else:
            if self.device.type == 'cuda':
                with torch.backends.cudnn.flags(allow_tf32=False):
                    dot = F.conv2d(pixels, template).squeeze(1)
            else:
                dot = F.conv2d(pixels, template).squeeze(1)
        energy = pixels.square().sum(dim=1)
        integral = F.pad(energy.cumsum(1).cumsum(2), (1, 0, 1, 0))
        patch_energy = (integral[:, h:, w:] - integral[:, :-h, w:]
                        - integral[:, h:, :-w] + integral[:, :-h, :-w]).clamp_min(0)
        denominator = (patch_energy * template_energy).sqrt()
        difference = (patch_energy + template_energy - 2 * dot).clamp_min(0)
        normalized = torch.where(denominator > 0, difference / denominator.clamp_min(1e-12), 1.0)
        confidence = 1.0 - normalized.clamp(0, 1).flatten(1).amin(1)
        return [(score >= self.threshold, score) for score in confidence.cpu().tolist()]
