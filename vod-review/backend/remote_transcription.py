"""Submit mounted audio to our cache-backed faster-whisper Runpod endpoint."""

import logging
import os
from pathlib import Path
import uuid


def transcribe_remote(path: str) -> dict:
    """Upload to a Runpod volume, await recognition, and remove the upload.

    Runpod's S3-compatible API keeps media outside the JSON request size limit.
    Only a relative file key crosses the worker boundary; credentials stay local.
    This synchronous adapter is called from the existing transcription thread.
    """
    import boto3
    import runpod
    from botocore.config import Config

    endpoint_id = os.environ.get("VOD_RUNPOD_ENDPOINT_ID", "").strip()
    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()
    volume_id = os.environ.get("RUNPOD_TRANSCRIPTION_VOLUME_ID", "").strip()
    datacenter = os.environ.get("RUNPOD_TRANSCRIPTION_VOLUME_REGION", "").strip().upper()
    if not endpoint_id or not api_key or not volume_id or not datacenter:
        raise ValueError("Runpod transcription requires VOD_RUNPOD_ENDPOINT_ID, RUNPOD_API_KEY, RUNPOD_TRANSCRIPTION_VOLUME_ID, and RUNPOD_TRANSCRIPTION_VOLUME_REGION")

    access_key = os.environ.get("RUNPOD_TRANSCRIPTION_VOLUME_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("RUNPOD_TRANSCRIPTION_VOLUME_SECRET_KEY", "").strip()
    if not access_key or not secret_key:
        raise ValueError("Runpod uploads require RUNPOD_TRANSCRIPTION_VOLUME_ACCESS_KEY and RUNPOD_TRANSCRIPTION_VOLUME_SECRET_KEY")
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Transcription media does not exist: {source}")

    # Explicit Runpod credentials and endpoint avoid using any ambient AWS
    # account configuration. A Runpod volume ID serves as the API's bucket.
    client = boto3.client(
        "s3", endpoint_url=f"https://s3api-{datacenter.lower()}.runpod.io",
        region_name=datacenter, aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    key = f"vod-transcription/{uuid.uuid4().hex}"
    try:
        client.upload_file(str(source), volume_id, key)

        endpoint = runpod.Endpoint(endpoint_id, api_key=api_key)
        job = endpoint.run({
            "input": {
                "audio_path": key,
                "model": os.environ.get("VOD_WHISPER_MODEL", "large-v3"),
                "enable_vad": True, "beam_size": 5,
                "transcription": "plain_text", "word_timestamps": False,
            },
            "policy": {"executionTimeout": 21_600_000},
        })
        try:
            output = job.output(timeout=21_900)
        except TimeoutError:
            try:
                job.cancel()
            except Exception:
                logging.getLogger(__name__).warning("Could not cancel timed-out transcription job %s", job.job_id)
            raise
        status = job.status()
        if status != "COMPLETED":
            raise RuntimeError(f"Runpod transcription job {job.job_id} ended with status {status}")
        if not isinstance(output, dict) or output.get("error") or not isinstance(output.get("segments"), list):
            raise RuntimeError(f"Runpod transcription returned invalid output: {output.get('error') if isinstance(output, dict) else 'expected a transcript object'}")
        segments = [
            {"start": segment["start"], "end": segment["end"], "text": segment["text"]}
            for segment in output["segments"]
        ]
        return {
            "transcript": "".join(segment["text"] for segment in segments).strip(),
            "language": output.get("detected_language"), "segments": segments,
        }
    finally:
        try:
            client.delete_object(Bucket=volume_id, Key=key)
        except Exception:
            # Cleanup must not turn a successful recognition into a lost result.
            logging.getLogger(__name__).warning(
                "Could not remove Runpod transcription upload %s; remove it from the network volume",
                key,
            )
