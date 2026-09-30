"""Stage-level profiling for PaddleOCR's ONNX Runtime recognizer."""

from __future__ import annotations

from types import MethodType
import time
from typing import Any

import numpy as np

from backend.tracing import detailed_profiling_enabled, trace_event


class _RunnerProxy:
    def __init__(self, owner: Any, runner: Any) -> None:
        self.owner = owner
        self.runner = runner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.runner, name)

    def _cuda_io_binding(self, inputs: list[np.ndarray]) -> list[Any]:
        import onnxruntime as ort
        from text_detection.profiling import _measure_device_call
        import torch

        session = self.runner.session
        input_names = [item.name for item in session.get_inputs()]
        output_names = [item.name for item in session.get_outputs()]
        if len(input_names) != len(inputs):
            raise ValueError("ONNX input count changed during profiled inference")
        binding = session.io_binding()
        transfer_started = time.perf_counter()
        ort_inputs = [
            ort.OrtValue.ortvalue_from_numpy(np.ascontiguousarray(value), "cuda", 0)
            for value in inputs
        ]
        for name, value in zip(input_names, ort_inputs, strict=True):
            binding.bind_ortvalue_input(name, value)
        for name in output_names:
            binding.bind_output(name, "cuda", 0)
        metrics = self.owner._vod_stage_metrics
        metrics["h2d_wall_ms"] = (time.perf_counter() - transfer_started) * 1000

        _, wall_ms, cuda_ms = _measure_device_call(
            torch.device("cuda:0"), lambda: session.run_with_iobinding(binding)
        )
        metrics["forward_wall_ms"] = wall_ms
        metrics["forward_cuda_ms"] = cuda_ms
        transfer_started = time.perf_counter()
        outputs = [value.numpy() for value in binding.get_outputs()]
        metrics["d2h_wall_ms"] = (time.perf_counter() - transfer_started) * 1000
        return outputs

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        inputs = kwargs.get("x", args[0] if args else None)
        session = getattr(self.runner, "session", None)
        providers = session.get_providers() if session is not None else []
        normalized_inputs = (
            [inputs]
            if isinstance(inputs, np.ndarray)
            else list(inputs)
            if isinstance(inputs, (list, tuple))
            and all(isinstance(value, np.ndarray) for value in inputs)
            else None
        )
        if (
            detailed_profiling_enabled()
            and providers
            and providers[0] == "CUDAExecutionProvider"
            and normalized_inputs is not None
        ):
            try:
                result = self._cuda_io_binding(normalized_inputs)
            except Exception as exc:  # noqa: BLE001 - preserve normal inference as fallback
                trace_event("profile_io_binding_fallback", component="ocr", error=type(exc).__name__)
                result = self.runner(*args, **kwargs)
        else:
            result = self.runner(*args, **kwargs)
        self.owner._vod_stage_metrics.setdefault(
            "combined_run_wall_ms", (time.perf_counter() - started) * 1000
        )
        return result


class _PostprocessProxy:
    def __init__(self, owner: Any, postprocess: Any) -> None:
        self.owner = owner
        self.postprocess = postprocess

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        result = self.postprocess(*args, **kwargs)
        self.owner._vod_stage_metrics["postprocess_wall_ms"] = (
            time.perf_counter() - started
        ) * 1000
        return result


def instrument_recognizer(recognizer: Any) -> bool:
    """Install reusable preprocessing, runner, and postprocessing timers."""
    predictor = getattr(recognizer, "paddlex_predictor", None)
    if predictor is None or getattr(predictor, "_vod_profiled", False):
        return predictor is not None
    if not hasattr(predictor, "runner") or not hasattr(predictor, "post_op"):
        return False
    original_process = predictor.process
    predictor._vod_stage_metrics = {}
    predictor.runner = _RunnerProxy(predictor, predictor.runner)
    predictor.post_op = _PostprocessProxy(predictor, predictor.post_op)

    def profiled_process(self, *args: Any, **kwargs: Any) -> Any:
        self._vod_stage_metrics = {}
        started = time.perf_counter()
        result = original_process(*args, **kwargs)
        total_ms = (time.perf_counter() - started) * 1000
        run_ms = self._vod_stage_metrics.get("combined_run_wall_ms", 0.0)
        post_ms = self._vod_stage_metrics.get("postprocess_wall_ms", 0.0)
        self._vod_stage_metrics["preprocess_wall_ms"] = max(0.0, total_ms - run_ms - post_ms)
        self._vod_stage_metrics["process_wall_ms"] = total_ms
        return result

    predictor.process = MethodType(profiled_process, predictor)
    predictor._vod_profiled = True
    return True


def recognizer_stage_metrics(recognizer: Any) -> dict[str, Any]:
    predictor = getattr(recognizer, "paddlex_predictor", None)
    metrics = getattr(predictor, "_vod_stage_metrics", {}) if predictor is not None else {}
    return {
        key: round(value, 4) if isinstance(value, float) else value
        for key, value in metrics.items()
    }
