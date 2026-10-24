"""Verify the dependency-only image with simulated cache data, without a GPU."""

from pathlib import Path
import runpy
import sys


def main() -> None:
    """Check installed dependencies, offline cache loading, and mounted inputs."""
    import runpod
    import faster_whisper

    sys.path.insert(0, "/worker")
    cache = Path("/runpod-volume/huggingface-cache/hub")
    assert not list(cache.glob("**/model.bin")), "Whisper weights must not be baked into the image"
    namespace = runpy.run_path("/worker/handler.py", run_name="_offline_worker_validation")
    worker = namespace["handler"]
    loads = []

    class Whisper:
        """Replace GPU inference while retaining the real input/cache adapter."""

        def __init__(self, model, **kwargs):
            """Require a local staged snapshot and disable runtime downloads."""
            assert str(model).startswith(str(cache))
            assert kwargs == {"device": "cuda", "compute_type": "float16", "local_files_only": True}
            loads.append(model)

        def transcribe(self, path, **kwargs):
            """Check source visibility and the unchanged inference options."""
            assert Path(path).read_bytes() == b"fixture media"
            assert kwargs == {"beam_size": 5, "vad_filter": True}
            return iter([]), type("Info", (), {"language": "en"})()

    real_whisper = faster_whisper.WhisperModel
    faster_whisper.WhisperModel = Whisper
    try:
        namespace["get_model"]()
    except RuntimeError as exc:
        assert "Cached model" in str(exc)
    else:
        raise AssertionError("Missing host cache must fail without downloading")
    assert loads == []

    repo = cache / "models--Systran--faster-whisper-large-v3"
    snapshot = repo / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    for filename in ("model.bin", "config.json", "tokenizer.json"):
        (snapshot / filename).write_bytes(b"fixture only; not real model weights")
    # Verify the installed library's real optional-config behavior without GPU
    # initialization, network access, or downloading any model weights.
    unloaded = real_whisper.__new__(real_whisper)
    assert unloaded._get_feature_kwargs(str(snapshot)) == {}
    audio = Path("/runpod-volume/vod-transcription/offline-test")
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"fixture media")
    for _ in range(2):
        result = worker({"input": {"audio_path": "vod-transcription/offline-test", "model": "large-v3"}})
        assert result["segments"] == [] and result["detected_language"] == "en"
    assert len(loads) == 1
    assert audio.read_bytes() == b"fixture media"
    assert "relative" in worker({"input": {"audio_path": "../private"}})["error"]
    print("OFFLINE IMAGE CHECK PASSED: dependencies, no baked weights, cache-only loading, mounted input; inference stubbed")


if __name__ == "__main__":
    main()
