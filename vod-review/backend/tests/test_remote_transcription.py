"""Exercise volume uploads and the derived endpoint without cloud calls."""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from backend import app


@pytest.fixture
def remote(monkeypatch, tmp_path):
    """Load the adapter with fake storage and a completed upstream-style job."""
    events = []
    configuration = {}
    output = {
        "transcription": "First. Café.", "detected_language": "en", "device": "cuda",
        "segments": [
            {"start": 1.5, "end": 2.0, "text": " First.", "id": 1},
            {"start": 12.0, "end": 14.0, "text": " Café.", "id": 2},
        ],
    }

    class Storage:
        """Record only the temporary files owned by this adapter."""

        def upload_file(self, path, bucket, key):
            """Record the source bytes and generated object key."""
            events.append(("upload", Path(path).read_bytes(), bucket, key))

        def delete_object(self, **kwargs):
            """Record cleanup after success or failure."""
            events.append(("delete", kwargs))

    class Job:
        """Expose the stable SDK's job interface with configurable outcomes."""

        job_id = "fixture-job"
        state = "COMPLETED"
        failure = None

        def output(self, timeout):
            """Return upstream output or simulate a failed remote operation."""
            assert timeout == 21_900
            if self.failure:
                raise self.failure
            return output

        def status(self):
            """Report the terminal job state."""
            return self.state

        def cancel(self):
            """Record cancellation when the local wait expires."""
            events.append(("cancel", self.job_id))

    job = Job()
    storage = Storage()

    class Endpoint:
        """Capture endpoint identity and queued inference settings."""

        def __init__(self, endpoint_id, api_key):
            """Require explicit Runpod authentication rather than cached state."""
            assert (endpoint_id, api_key) == ("fixture-endpoint", "fixture-api-key")

        def run(self, payload):
            """Submit a small mounted-file reference rather than media bytes."""
            events.append(("run", payload))
            return job

    def client(service, **kwargs):
        """Capture the Runpod storage endpoint and explicit storage credentials."""
        assert service == "s3"
        configuration.update(kwargs)
        return storage

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "botocore.config", SimpleNamespace(Config=lambda **kwargs: SimpleNamespace(**kwargs)))
    monkeypatch.setitem(sys.modules, "runpod", SimpleNamespace(Endpoint=Endpoint))
    for key, value in {
        "VOD_RUNPOD_ENDPOINT_ID": "fixture-endpoint", "RUNPOD_API_KEY": "fixture-api-key",
        "RUNPOD_TRANSCRIPTION_VOLUME_ID": "fixture-volume",
        "RUNPOD_TRANSCRIPTION_VOLUME_REGION": "US-IL-1",
        "RUNPOD_TRANSCRIPTION_VOLUME_ACCESS_KEY": "fixture-access",
        "RUNPOD_TRANSCRIPTION_VOLUME_SECRET_KEY": "fixture-secret",
        "VOD_WHISPER_MODEL": "large-v3",
    }.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location(
        "_test_remote_transcription", Path(app.__file__).with_name("remote_transcription.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    media = tmp_path / "audio.m4a"
    media.write_bytes(b"fixture-audio")
    return SimpleNamespace(module=module, events=events, configuration=configuration,
                           output=output, job=job, media=media, storage=storage)


def test_remote_result_preserves_timestamps_and_upload_lifecycle(remote):
    """Normalize upstream results and delete the exact uploaded file."""
    result = remote.module.transcribe_remote(str(remote.media))
    assert result == {
        "transcript": "First. Café.", "language": "en",
        "segments": [
            {"start": 1.5, "end": 2.0, "text": " First."},
            {"start": 12.0, "end": 14.0, "text": " Café."},
        ],
    }
    upload, run, delete = remote.events
    assert upload[:3] == ("upload", b"fixture-audio", "fixture-volume")
    assert run[1] == {
        "input": {"audio_path": upload[3], "model": "large-v3", "enable_vad": True,
                  "beam_size": 5, "transcription": "plain_text", "word_timestamps": False},
        "policy": {"executionTimeout": 21_600_000},
    }
    assert delete[1] == {"Bucket": "fixture-volume", "Key": upload[3]}
    assert remote.configuration["endpoint_url"] == "https://s3api-us-il-1.runpod.io"
    assert remote.configuration["region_name"] == "US-IL-1"
    assert remote.configuration["aws_access_key_id"] == "fixture-access"
    assert remote.configuration["aws_secret_access_key"] == "fixture-secret"


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED", "TIMED_OUT"])
def test_failed_job_preserves_failure_and_removes_upload(remote, state):
    """Never publish unsuccessful job output as a completed transcript."""
    remote.job.state = state
    with pytest.raises(RuntimeError, match=state):
        remote.module.transcribe_remote(str(remote.media))
    assert remote.events[-1][0] == "delete"


def test_timeout_cancels_job_before_removing_upload(remote):
    """Stop remote work before deleting its input when the wait expires."""
    remote.job.failure = TimeoutError("fixture timeout")
    with pytest.raises(TimeoutError):
        remote.module.transcribe_remote(str(remote.media))
    assert [event[0] for event in remote.events] == ["upload", "run", "cancel", "delete"]


def test_handler_error_is_not_a_successful_transcript(remote):
    """Surface handler validation failures even when the job reports completed."""
    remote.output["error"] = "Mounted audio file does not exist"
    with pytest.raises(RuntimeError, match="Mounted audio file"):
        remote.module.transcribe_remote(str(remote.media))
    assert remote.events[-1][0] == "delete"


def test_cleanup_failure_keeps_successful_result(remote, monkeypatch, caplog):
    """A cleanup outage must not discard completed recognition."""
    def fail(**kwargs):
        """Simulate a storage failure after the output has returned."""
        raise OSError("fixture cleanup failure")
    monkeypatch.setattr(remote.storage, "delete_object", fail)
    assert remote.module.transcribe_remote(str(remote.media))["transcript"] == "First. Café."
    assert "Could not remove" in caplog.text


@pytest.mark.parametrize("key", ["VOD_RUNPOD_ENDPOINT_ID", "RUNPOD_API_KEY", "RUNPOD_TRANSCRIPTION_VOLUME_ID",
                                 "RUNPOD_TRANSCRIPTION_VOLUME_REGION", "RUNPOD_TRANSCRIPTION_VOLUME_ACCESS_KEY",
                                 "RUNPOD_TRANSCRIPTION_VOLUME_SECRET_KEY"])
def test_missing_configuration_fails_before_upload(remote, monkeypatch, key):
    """Do not upload media or submit paid work with incomplete configuration."""
    monkeypatch.delenv(key)
    with pytest.raises(ValueError):
        remote.module.transcribe_remote(str(remote.media))
    assert remote.events == []


def test_remote_backend_validates_result_and_reports_completion(monkeypatch):
    """Keep the application result contract and completion notification."""
    monkeypatch.setenv("VOD_TRANSCRIPTION_BACKEND", "runpod")
    monkeypatch.setitem(sys.modules, "backend.remote_transcription", SimpleNamespace(
        transcribe_remote=lambda path: {
            "transcript": "Hello", "language": "en",
            "segments": [{"start": 1.5, "end": 3.0, "text": " Hello"}],
        },
    ))
    progress = []
    result = app._transcribe_audio_file("/local/audio.m4a", progress.append)
    assert result.transcript == "Hello"
    assert result.segments[0].start == 1.5
    assert progress == [99.0]


def test_invalid_backend_is_reported(monkeypatch):
    """Catch misspelled remote configuration before local GPU recognition."""
    monkeypatch.setenv("VOD_TRANSCRIPTION_BACKEND", "runpdo")
    with pytest.raises(ValueError, match="VOD_TRANSCRIPTION_BACKEND"):
        app._transcribe_audio_file("/local/audio.m4a")
