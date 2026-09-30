from types import SimpleNamespace

import numpy as np
import torch

from text_detection.profiling import instrument_yolo_predictor, yolo_stage_metrics


class FakePredictor:
    device = torch.device("cpu")
    model = SimpleNamespace(fp16=False)

    def pre_transform(self, images):
        return images

    def preprocess(self, images):
        return torch.from_numpy(np.stack(images).transpose(0, 3, 1, 2)).float() / 255

    def inference(self, tensor):
        return tensor + 1

    def postprocess(self, prediction):
        return prediction.mean()


def test_yolo_instrumentation_records_split_stage_timings():
    predictor = FakePredictor()
    detector = SimpleNamespace(predictor=predictor)

    assert instrument_yolo_predictor(detector)
    tensor = predictor.preprocess([np.zeros((4, 5, 3), dtype=np.uint8)])
    prediction = predictor.inference(tensor)
    predictor.postprocess(prediction)
    metrics = yolo_stage_metrics(detector, [])

    assert tensor.shape == (1, 3, 4, 5)
    assert metrics["cpu_preprocess_ms"] >= 0
    assert metrics["h2d_wall_ms"] >= 0
    assert metrics["device_preprocess_wall_ms"] >= 0
    assert metrics["forward_wall_ms"] >= 0
    assert metrics["postprocess_wall_ms"] >= 0
    assert instrument_yolo_predictor(detector)
