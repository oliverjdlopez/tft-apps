from types import SimpleNamespace

import numpy as np

from round_classifier.profiling import _RunnerProxy, instrument_recognizer, recognizer_stage_metrics


class FakeSession:
    def get_providers(self):
        return ["CPUExecutionProvider"]


class FakeRunner:
    session = FakeSession()

    def __call__(self, *, x):
        return [value + 1 for value in x]


class FakePostprocess:
    def __call__(self, values):
        return [value.mean() for value in values]


class FakePredictor:
    def __init__(self):
        self.runner = FakeRunner()
        self.post_op = FakePostprocess()

    def process(self, values):
        prepared = [value.astype(np.float32) / 255 for value in values]
        return self.post_op(self.runner(x=np.stack(prepared)))


def test_recognizer_instrumentation_records_split_stage_timings():
    predictor = FakePredictor()
    recognizer = SimpleNamespace(paddlex_predictor=predictor)

    assert instrument_recognizer(recognizer)
    result = predictor.process([np.zeros((3, 4), dtype=np.uint8)])
    metrics = recognizer_stage_metrics(recognizer)

    assert result == [1.0]
    assert metrics["preprocess_wall_ms"] >= 0
    assert metrics["combined_run_wall_ms"] >= 0
    assert metrics["postprocess_wall_ms"] >= 0
    assert metrics["process_wall_ms"] >= 0
    assert instrument_recognizer(recognizer)


def test_cuda_runner_accepts_paddlex_single_numpy_input(monkeypatch):
    owner = SimpleNamespace(_vod_stage_metrics={})
    runner = FakeRunner()
    runner.session = SimpleNamespace(get_providers=lambda: ["CUDAExecutionProvider"])
    proxy = _RunnerProxy(owner, runner)
    received = []
    monkeypatch.setenv("VOD_DETAILED_PROFILING", "1")
    monkeypatch.setattr(
        proxy,
        "_cuda_io_binding",
        lambda inputs: received.extend(inputs) or [np.ones((1,), dtype=np.float32)],
    )

    result = proxy(x=np.zeros((1, 3, 4, 5), dtype=np.float32))

    assert len(received) == 1
    assert received[0].shape == (1, 3, 4, 5)
    assert result[0].tolist() == [1.0]
