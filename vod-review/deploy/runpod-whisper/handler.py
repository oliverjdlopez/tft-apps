"""Transcribe mounted audio using a Runpod host-cached faster-whisper model."""

from functools import lru_cache
import os

# Set these before importing Hugging Face consumers, even during local tests.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from cached_model import resolve_snapshot_path
from mounted_audio import resolve_mounted_input

MODEL_NAME = os.environ.get("MODEL_NAME", "Systran/faster-whisper-large-v3")


@lru_cache(maxsize=1)
def get_model():
    """Load the staged model once per worker with CUDA and downloads disabled."""
    from faster_whisper import WhisperModel

    snapshot = resolve_snapshot_path(MODEL_NAME)
    print(f"Loading cached model {MODEL_NAME} from {snapshot}", flush=True)
    return WhisperModel(str(snapshot), device="cuda", compute_type="float16", local_files_only=True)


def handler(job: dict) -> dict:
    """Recognize one mounted audio file and preserve source-relative timings.

    Args:
        job: Runpod envelope containing a relative audio_path under vod-transcription/.

    Returns:
        Text, detected language, and segment timings, or an input error envelope.
    """
    inputs = job.get("input", {})
    if not isinstance(inputs, dict) or not isinstance(inputs.get("audio_path"), str):
        return {"error": "input.audio_path must be a relative mounted-file path"}
    alias = MODEL_NAME.split("/", 1)[-1].removeprefix("faster-whisper-")
    if inputs.get("model", alias) not in {alias, MODEL_NAME}:
        return {"error": f"This endpoint is configured for cached model {MODEL_NAME}; redeploy to change it"}
    try:
        audio = resolve_mounted_input(inputs)
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}

    segments, info = get_model().transcribe(audio, beam_size=5, vad_filter=True)
    timings = [{"start": segment.start, "end": segment.end, "text": segment.text} for segment in segments]
    return {
        "transcription": "".join(segment["text"] for segment in timings).strip(),
        "detected_language": getattr(info, "language", None),
        "segments": timings, "device": "cuda", "model": MODEL_NAME,
    }


if __name__ == "__main__":
    import runpod

    get_model()
    runpod.serverless.start({"handler": handler})
