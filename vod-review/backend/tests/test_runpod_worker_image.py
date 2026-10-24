"""Check the derived image's input boundary without Docker or GPU inference."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def resolver():
    """Load the exact helper copied into the derived container image."""
    source = Path(__file__).parents[2] / 'deploy/runpod-whisper/mounted_audio.py'
    spec = importlib.util.spec_from_file_location('_mounted_audio_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.resolve_mounted_input


def test_existing_volume_input_is_read_without_copy_or_deletion(resolver, tmp_path):
    """Resolve an uploaded file while preserving the caller-owned source."""
    audio = tmp_path / 'vod-transcription/audio.m4a'
    audio.parent.mkdir()
    audio.write_bytes(b'fixture-media')
    assert resolver({'audio_path': 'vod-transcription/audio.m4a'}, str(tmp_path)) == str(audio)
    assert audio.read_bytes() == b'fixture-media'


@pytest.mark.parametrize('source', ['audio', 'audio_base64'])
def test_url_and_embedded_sources_are_rejected(resolver, source):
    """Keep the mounted-file contract explicit rather than downloading inputs."""
    with pytest.raises(ValueError, match='mounted audio only'):
        resolver({source: 'fixture-input'})


@pytest.mark.parametrize('inputs', [{}, {'audio': 'url', 'audio_path': 'vod-transcription/audio'},
                                   {'audio_base64': 'bytes', 'audio_path': 'vod-transcription/audio'},
                                   {'audio': 'url', 'audio_base64': 'bytes'}])
def test_conflicting_or_missing_sources_are_rejected(resolver, inputs):
    """An input must resolve through exactly one explicit source."""
    with pytest.raises(ValueError, match='exactly one'):
        resolver(inputs)


@pytest.mark.parametrize('path', ['/etc/passwd', '../secret', 'vod-transcription/../secret', 'models/model.bin'])
def test_worker_cannot_read_outside_uploads(resolver, tmp_path, path):
    """Reject absolute and escaping paths, including unrelated volume data."""
    with pytest.raises(ValueError):
        resolver({'audio_path': path}, str(tmp_path))


def test_symlink_escape_is_rejected(resolver, tmp_path):
    """Resolve symlinks before checking the workflow's permitted directory."""
    source = tmp_path / 'private.txt'
    source.write_text('private fixture')
    uploads = tmp_path / 'vod-transcription'
    uploads.mkdir()
    (uploads / 'link').symlink_to(source)
    with pytest.raises(ValueError, match='escapes'):
        resolver({'audio_path': 'vod-transcription/link'}, str(tmp_path))


def test_missing_mounted_file_is_reported(resolver, tmp_path):
    """Return a useful handler error when the upload is not visible."""
    with pytest.raises(FileNotFoundError):
        resolver({'audio_path': 'vod-transcription/missing'}, str(tmp_path))


@pytest.fixture
def cached_worker(monkeypatch, tmp_path):
    """Import the actual worker with isolated cache data and fake CUDA inference."""
    import sys
    from types import SimpleNamespace

    directory = Path(__file__).parents[2] / 'deploy/runpod-whisper'
    modules = {}
    for name in ['cached_model', 'mounted_audio', 'handler']:
        spec = importlib.util.spec_from_file_location(name, directory / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        if name == 'handler':
            monkeypatch.setenv('MODEL_NAME', 'Systran/faster-whisper-large-v3')
            monkeypatch.setenv('HF_HUB_OFFLINE', '0')
            monkeypatch.setenv('TRANSFORMERS_OFFLINE', '0')
        spec.loader.exec_module(module)
        modules[name] = module
    repo = tmp_path / 'cache/models--Systran--faster-whisper-large-v3'
    snapshot = repo / 'snapshots' / ('a' * 40)
    snapshot.mkdir(parents=True)
    for name in ['model.bin', 'config.json', 'tokenizer.json', 'preprocessor_config.json']:
        (snapshot / name).write_text('fixture-cache-data')
    (repo / 'refs').mkdir()
    (repo / 'refs/main').write_text('a' * 40)
    audio = tmp_path / 'volume/vod-transcription/audio.m4a'
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b'fixture-audio')
    loads = []

    class Whisper:
        """Capture offline model initialization and emit source-relative timings."""

        def __init__(self, model, **kwargs):
            """Require a local snapshot, CUDA, and explicit offline mode."""
            loads.append((model, kwargs))
            assert model == str(snapshot)
            assert kwargs == {'device': 'cuda', 'compute_type': 'float16', 'local_files_only': True}

        def transcribe(self, path, **kwargs):
            """Keep inference options and lazy segment iteration testable."""
            assert path == str(audio)
            assert kwargs == {'beam_size': 5, 'vad_filter': True}
            return iter([SimpleNamespace(start=2.5, end=4.0, text=' Hello.')]), SimpleNamespace(language='en')

    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Whisper))
    monkeypatch.setattr(modules['handler'], 'resolve_snapshot_path',
                        lambda model: modules['cached_model'].resolve_snapshot_path(model, str(tmp_path / 'cache')))
    monkeypatch.setattr(modules['handler'], 'resolve_mounted_input',
                        lambda inputs: modules['mounted_audio'].resolve_mounted_input(inputs, str(tmp_path / 'volume')))
    return SimpleNamespace(worker=modules['handler'], cache=modules['cached_model'],
                           snapshot=snapshot, repo=repo, cache_root=tmp_path / 'cache', loads=loads)


def test_cached_worker_loads_local_model_once_and_keeps_timings(cached_worker, monkeypatch):
    """Reuse the GPU model and never pass a download-capable repository name."""
    import os

    job = {'input': {'audio_path': 'vod-transcription/audio.m4a', 'model': 'large-v3'}}
    for _ in range(2):
        result = cached_worker.worker.handler(job)
        assert result['segments'] == [{'start': 2.5, 'end': 4.0, 'text': ' Hello.'}]
        assert result['detected_language'] == 'en'
        assert result['device'] == 'cuda'
    assert len(cached_worker.loads) == 1
    assert os.environ['HF_HUB_OFFLINE'] == os.environ['TRANSFORMERS_OFFLINE'] == '1'


@pytest.mark.parametrize('filename', ['model.bin', 'config.json', 'tokenizer.json'])
def test_missing_cached_weights_fail_without_model_download(cached_worker, filename):
    """Missing required files must fail before any download-capable fallback."""
    (cached_worker.snapshot / filename).unlink()
    with pytest.raises(RuntimeError, match='no runtime download'):
        cached_worker.worker.get_model()
    assert cached_worker.loads == []


def test_missing_optional_preprocessor_keeps_cached_model_usable(cached_worker):
    """Official medium snapshots omit the optional feature-extractor config."""
    (cached_worker.snapshot / 'preprocessor_config.json').unlink()
    cached_worker.worker.get_model()
    assert len(cached_worker.loads) == 1


def test_ambiguous_cache_does_not_select_an_arbitrary_revision(cached_worker):
    """Require an explicit reference when more than one snapshot is present."""
    (cached_worker.repo / 'refs/main').unlink()
    (cached_worker.repo / 'snapshots' / ('b' * 40)).mkdir()
    with pytest.raises(RuntimeError, match='ambiguous'):
        cached_worker.cache.resolve_snapshot_path('Systran/faster-whisper-large-v3', str(cached_worker.cache_root))


def test_cached_worker_rejects_a_different_requested_model(cached_worker):
    """One endpoint model reference cannot be overridden to fetch another model."""
    result = cached_worker.worker.handler({'input': {'audio_path': 'vod-transcription/audio.m4a', 'model': 'small'}})
    assert 'configured for cached model' in result['error']
    assert cached_worker.loads == []
