"""Deploy a cache-only Whisper worker or run a persisted audio acceptance test."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

from dotenv import load_dotenv, set_key
import requests

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
load_dotenv(APP_ROOT / ".env", override=False)


def deploy(image: str, registry_auth_id: str | None, model_repo: str = "Systran/faster-whisper-large-v3") -> None:
    """Create a zero-minimum-worker endpoint and save its app-local settings.

    Args:
        image: Published, preferably digest-pinned dependency-only worker image.
        registry_auth_id: Existing Runpod registry credential ID for private images.
        model_repo: CTranslate2 Hugging Face repository for Runpod's host cache.
    """
    if os.environ.get("VOD_RUNPOD_ENDPOINT_ID"):
        raise ValueError("VOD_RUNPOD_ENDPOINT_ID is already set; update that endpoint instead of creating a duplicate")
    api_key = os.environ["RUNPOD_API_KEY"]
    volume_id = os.environ["RUNPOD_TRANSCRIPTION_VOLUME_ID"]
    region = os.environ["RUNPOD_TRANSCRIPTION_VOLUME_REGION"].strip().upper()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {api_key}"})
    api = "https://rest.runpod.io/v1"
    template_input = {
        "name": "vod-review-mounted-whisper", "imageName": image,
        "isServerless": True, "isPublic": False, "containerDiskInGb": 20,
        "env": {"PYTHONUNBUFFERED": "1", "MODEL_NAME": model_repo,
                "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
    }
    if registry_auth_id:
        template_input["containerRegistryAuthId"] = registry_auth_id
    response = session.post(f"{api}/templates", json=template_input, timeout=60)
    response.raise_for_status()
    template_id = response.json()["id"]
    state = {"image": image, "model_repo": model_repo, "template_id": template_id, "endpoint_id": None}
    state_path = APP_ROOT / "data/runpod-whisper-deployment.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))
    try:
        # Cached-model references are not exposed by the resource REST API.
        # This is the same EndpointInput mutation used by Runpod's app SDK.
        response = session.post("https://api.runpod.io/graphql", json={
            "query": "mutation saveEndpoint($input: EndpointInput!) { saveEndpoint(input: $input) { id } }",
            "variables": {"input": {
            "name": "vod-review-mounted-whisper", "templateId": template_id,
            "gpuIds": "ADA_24",
            "gpuCount": 1, "workersMin": 0, "workersMax": 1,
            "locations": region, "networkVolumeIds": [{"networkVolumeId": volume_id}],
            "modelReferences": [model_repo],
            "executionTimeoutMs": 21_600_000, "idleTimeout": 5,
            "scalerType": "QUEUE_DELAY", "scalerValue": 4,
            "flashBootType": "FLASHBOOT",
            }},
        }, timeout=60)
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"Runpod endpoint creation failed: {payload['errors'][0]['message']}")
        endpoint_id = payload["data"]["saveEndpoint"]["id"]
    except Exception:
        cleanup = session.delete(f"{api}/templates/{template_id}", timeout=60)
        if cleanup.ok:
            state["template_id"] = None
            state_path.write_text(json.dumps(state, indent=2))
        else:
            print(f"Template cleanup failed; template ID: {template_id}", file=sys.stderr)
        raise

    state["endpoint_id"] = endpoint_id
    state_path.write_text(json.dumps(state, indent=2))
    set_key(APP_ROOT / ".env", "VOD_RUNPOD_ENDPOINT_ID", endpoint_id)
    set_key(APP_ROOT / ".env", "VOD_TRANSCRIPTION_BACKEND", "runpod")
    set_key(APP_ROOT / ".env", "VOD_WHISPER_MODEL", model_repo.split("/")[-1].removeprefix("faster-whisper-"))
    print(f"Endpoint deployed: {endpoint_id}; minimum workers: 0")
    print(f"Deployment metadata: {state_path}")


def test_audio(audio: Path, output: Path | None) -> None:
    """Run one paid transcription and retain exact output for human inspection.

    Args:
        audio: Existing audio-only test slice; the source is never modified.
        output: New ignored artifact directory, or a timestamped default.
    """
    from backend.models import AudioTranscription
    from backend.remote_transcription import transcribe_remote

    audio = audio.expanduser().resolve(strict=True)
    if output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = APP_ROOT / "data/runpod-transcription-test" / stamp
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    print(f"Submitting {audio.name} to the configured Runpod endpoint", flush=True)
    try:
        result = AudioTranscription.model_validate(transcribe_remote(str(audio)))
        payload = result.model_dump()
        (output / "transcript.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        (output / "transcript.txt").write_text(result.transcript + "\n")
        for previous, current in zip(result.segments, result.segments[1:]):
            if current.start < previous.start:
                raise ValueError("Returned segment timestamps are not ordered")
        if any(segment.start < 0 or segment.end < segment.start for segment in result.segments):
            raise ValueError("Returned segment timestamp range is invalid")
        summary = {"source": str(audio), "wall_seconds": time.monotonic() - started,
                   "language": result.language, "segments": len(result.segments),
                   "characters": len(result.transcript)}
        (output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)
        print(f"Saved transcript and timestamped JSON: {output}", flush=True)
    except Exception as exc:
        (output / "failure.json").write_text(json.dumps({"type": type(exc).__name__, "error": str(exc)}))
        raise


def main() -> None:
    """Dispatch explicit deployment or paid transcription acceptance commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    deployment = commands.add_parser("deploy")
    deployment.add_argument("--image", required=True)
    deployment.add_argument("--registry-auth-id")
    deployment.add_argument("--model-repo", default="Systran/faster-whisper-large-v3")
    test = commands.add_parser("test")
    test.add_argument("audio", type=Path)
    test.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "deploy":
        deploy(args.image, args.registry_auth_id, args.model_repo)
    else:
        test_audio(args.audio, args.output)


if __name__ == "__main__":
    main()
