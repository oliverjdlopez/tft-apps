"""Offline checks for timing boundaries and failure artifact preservation."""

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import benchmark


@dataclass
class Options:
    """Minimal serializable upstream options fixture."""

    beam_size: int = 5


class BenchmarkTests(unittest.TestCase):
    """Exercise the worker without model downloads or GPU inference."""

    def run_trial(self, batch, fail=False):
        """Execute a fake lazy recognizer and return its persisted artifacts."""
        calls = []
        clock = [0.0]

        class Model:
            """Simulate model loading separately from lazy recognition."""

            def __init__(self, *args, **kwargs):
                clock[0] += 2

            def transcribe(self, source, **kwargs):
                calls.append(kwargs)
                clock[0] += 3

                def segments():
                    clock[0] += 7
                    if fail:
                        raise RuntimeError('simulated out of memory')
                    yield SimpleNamespace(start=1.25, end=2.75, text=' hello')

                return segments(), SimpleNamespace(
                    duration=100, duration_after_vad=80, language='en',
                    transcription_options=Options(), vad_options=None)

        fake = SimpleNamespace(WhisperModel=Model, BatchedInferencePipeline=lambda model: model)
        with tempfile.TemporaryDirectory() as directory:
            config = dict(destination=directory, model='large-v3', device_index=0,
                          allow_download=False, batch_size=batch, language=None, audio='fixture.wav')
            with patch.dict('sys.modules', faster_whisper=fake), \
                    patch.object(benchmark.importlib.metadata, 'version', return_value='test'), \
                    patch.object(benchmark, 'sample_memory'), \
                    patch.object(benchmark.time, 'perf_counter', side_effect=lambda: clock[0]):
                status = benchmark.worker(config)
            result = json.loads((Path(directory) / 'result.json').read_text())
            transcript = Path(directory) / 'transcript.json'
            return status, result, json.loads(transcript.read_text()) if transcript.exists() else None, calls

    def test_baseline_times_lazy_work_and_preserves_offsets(self):
        """Recognition timing includes iteration and excludes model loading."""
        status, result, transcript, calls = self.run_trial(0)
        self.assertEqual(status, 0)
        self.assertEqual(result['model_load_seconds'], 2)
        self.assertEqual(result['transcription_seconds'], 10)
        self.assertEqual(result['segment_iteration_seconds'], 7)
        self.assertEqual(transcript['segments'][0]['start'], 1.25)
        self.assertEqual(calls, [dict(beam_size=5, vad_filter=True, without_timestamps=False)])

    def test_batch_retains_timestamps_and_beam(self):
        """Batched runs request timing tokens and the intended batch size."""
        status, _, _, calls = self.run_trial(8)
        self.assertEqual(status, 0)
        self.assertEqual(calls[0]['batch_size'], 8)
        self.assertFalse(calls[0]['without_timestamps'])
        self.assertEqual(calls[0]['beam_size'], 5)

    def test_iteration_failure_is_saved(self):
        """A lazy GPU failure leaves a failed result rather than a success."""
        status, result, transcript, _ = self.run_trial(4, fail=True)
        self.assertEqual(status, 1)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('simulated out of memory', result['error'])
        self.assertIsNone(transcript)


if __name__ == '__main__':
    unittest.main()
