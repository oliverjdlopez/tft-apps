"""Low-overhead stage profiling for the cached Ultralytics predictor."""

from __future__ import annotations

from types import MethodType
import time
from typing import Any, Callable

import numpy as np


def _measure_device_call(device: Any, function: Callable[[], Any]) -> tuple[Any, float, float | None]:
    """Return a call result plus wall and CUDA-event durations."""
    import torch

    started = time.perf_counter()
    if getattr(device, "type", None) == "mps":
        torch.mps.synchronize()
        started = time.perf_counter()
        result = function()
        torch.mps.synchronize()
        return result, (time.perf_counter() - started) * 1000, None
    if getattr(device, "type", None) != "cuda" or not torch.cuda.is_available():
        result = function()
        return result, (time.perf_counter() - started) * 1000, None
    start_event = torch.cuda.Event(enable_timing=True)
    end_event = torch.cuda.Event(enable_timing=True)
    start_event.record()
    result = function()
    end_event.record()
    end_event.synchronize()
    return result, (time.perf_counter() - started) * 1000, start_event.elapsed_time(end_event)


def instrument_yolo_predictor(detector: Any) -> bool:
    """Install detailed timers after Ultralytics has created its predictor."""
    predictor = getattr(detector, "predictor", None)
    if predictor is None or getattr(predictor, "_vod_profiled", False):
        return predictor is not None
    import torch

    original_inference = predictor.inference
    original_postprocess = predictor.postprocess

    def profiled_preprocess(self, images):
        metrics: dict[str, Any] = {}
        cpu_started = time.perf_counter()
        not_tensor = not isinstance(images, torch.Tensor)
        if not_tensor:
            tensor = np.stack(self.pre_transform(images))
            if tensor.shape[-1] == 3:
                tensor = tensor[..., ::-1]
            tensor = tensor.transpose((0, 3, 1, 2))
            tensor = np.ascontiguousarray(tensor)
            tensor = torch.from_numpy(tensor)
        else:
            tensor = images
        metrics["cpu_preprocess_ms"] = (time.perf_counter() - cpu_started) * 1000

        tensor, wall_ms, cuda_ms = _measure_device_call(
            self.device, lambda: tensor.to(self.device)
        )
        metrics["h2d_wall_ms"] = wall_ms
        metrics["h2d_cuda_ms"] = cuda_ms

        def normalize():
            normalized = tensor.half() if self.model.fp16 else tensor.float()
            if not_tensor:
                normalized /= 255
            return normalized

        tensor, wall_ms, cuda_ms = _measure_device_call(self.device, normalize)
        metrics["device_preprocess_wall_ms"] = wall_ms
        metrics["device_preprocess_cuda_ms"] = cuda_ms
        self._vod_stage_metrics = metrics
        return tensor

    def profiled_inference(self, *args, **kwargs):
        result, wall_ms, cuda_ms = _measure_device_call(
            self.device, lambda: original_inference(*args, **kwargs)
        )
        self._vod_stage_metrics.update(
            forward_wall_ms=wall_ms,
            forward_cuda_ms=cuda_ms,
        )
        return result

    def profiled_postprocess(self, *args, **kwargs):
        result, wall_ms, cuda_ms = _measure_device_call(
            self.device, lambda: original_postprocess(*args, **kwargs)
        )
        self._vod_stage_metrics.update(
            postprocess_wall_ms=wall_ms,
            postprocess_cuda_ms=cuda_ms,
        )
        return result

    predictor.preprocess = MethodType(profiled_preprocess, predictor)
    predictor.inference = MethodType(profiled_inference, predictor)
    predictor.postprocess = MethodType(profiled_postprocess, predictor)
    predictor._vod_profiled = True
    predictor._vod_stage_metrics = {}
    return True


def yolo_stage_metrics(detector: Any, results: list[Any]) -> dict[str, Any]:
    """Collect Ultralytics aggregate timings plus any detailed instrumentation."""
    totals = {"preprocess": 0.0, "inference": 0.0, "postprocess": 0.0}
    for result in results:
        for name in totals:
            totals[name] += float(getattr(result, "speed", {}).get(name, 0.0))
    metrics: dict[str, Any] = {
        "preprocess_wall_ms": round(totals["preprocess"], 4),
        "forward_wall_ms": round(totals["inference"], 4),
        "postprocess_wall_ms": round(totals["postprocess"], 4),
    }
    predictor = getattr(detector, "predictor", None)
    detailed = getattr(predictor, "_vod_stage_metrics", {}) if predictor is not None else {}
    metrics.update(
        (key, round(value, 4) if isinstance(value, float) else value)
        for key, value in detailed.items()
    )
    return metrics
