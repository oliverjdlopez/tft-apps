"""Protect deployment cost settings and app-local configuration writes."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values
import pytest


@pytest.fixture
def deployment(monkeypatch, tmp_path):
    """Load the deployment CLI with a fake cloud management client."""
    source = Path(__file__).parents[2] / 'scripts/runpod_whisper.py'
    spec = importlib.util.spec_from_file_location('_runpod_deployment_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'APP_ROOT', tmp_path)
    monkeypatch.delenv('VOD_RUNPOD_ENDPOINT_ID', raising=False)
    monkeypatch.setenv('RUNPOD_API_KEY', 'fixture-api-key')
    monkeypatch.setenv('RUNPOD_TRANSCRIPTION_VOLUME_ID', 'fixture-volume')
    monkeypatch.setenv('RUNPOD_TRANSCRIPTION_VOLUME_REGION', 'eu-ro-1')
    (tmp_path / '.env').write_text('EXISTING=keep\n')
    posts = []
    deletes = []
    state = {'fail_endpoint': False}

    class Response:
        """Emulate management API responses without creating resources."""
        ok = True

        def __init__(self, path):
            """Remember which resource type is being created."""
            self.path = path

        def raise_for_status(self):
            """Fail endpoint creation when testing cleanup behavior."""
            if self.path.endswith('/graphql') and state['fail_endpoint']:
                raise RuntimeError('fixture endpoint creation failure')

        def json(self):
            """Return only synthetic resource IDs."""
            if self.path.endswith('/graphql'):
                return {'data': {'saveEndpoint': {'id': 'fixture-endpoint'}}}
            return {'id': 'fixture-template'}

    def post(url, json, timeout):
        """Record requested configuration so costly defaults cannot regress."""
        posts.append((url, json))
        return Response(url)

    def delete(url, timeout):
        """Record rollback of this attempt's template only."""
        deletes.append(url)
        return SimpleNamespace(ok=True)

    session = SimpleNamespace(headers={}, post=post, delete=delete)
    monkeypatch.setattr(module.requests, 'Session', lambda: session)
    return SimpleNamespace(module=module, root=tmp_path, posts=posts, deletes=deletes, state=state)


def test_deploy_scales_to_zero_and_saves_only_app_settings(deployment):
    """Use the existing volume and avoid persistent GPU billing by default."""
    deployment.module.deploy('registry.example/whisper@sha256:fixture', 'fixture-registry-auth')
    template, endpoint = deployment.posts
    assert template[1]['containerRegistryAuthId'] == 'fixture-registry-auth'
    assert template[1]['env'] == {'PYTHONUNBUFFERED': '1', 'MODEL_NAME': 'Systran/faster-whisper-large-v3',
                                  'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
    settings = endpoint[1]['variables']['input']
    assert settings['workersMin'] == 0 and settings['workersMax'] == 1
    assert settings['gpuIds'] == 'ADA_24'
    assert settings['locations'] == 'EU-RO-1'
    assert settings['networkVolumeIds'] == [{'networkVolumeId': 'fixture-volume'}]
    assert settings['modelReferences'] == ['Systran/faster-whisper-large-v3']
    assert settings['executionTimeoutMs'] == 21_600_000
    assert dotenv_values(deployment.root / '.env') == {
        'EXISTING': 'keep', 'VOD_RUNPOD_ENDPOINT_ID': 'fixture-endpoint',
        'VOD_TRANSCRIPTION_BACKEND': 'runpod', 'VOD_WHISPER_MODEL': 'large-v3',
    }


def test_failed_deployment_rolls_back_template_and_leaves_settings(deployment):
    """Do not enable the remote backend when endpoint creation fails."""
    deployment.state['fail_endpoint'] = True
    with pytest.raises(RuntimeError, match='creation failure'):
        deployment.module.deploy('registry.example/whisper:fixture', None)
    assert deployment.deletes == ['https://rest.runpod.io/v1/templates/fixture-template']
    assert dotenv_values(deployment.root / '.env') == {'EXISTING': 'keep'}


def test_existing_endpoint_prevents_accidental_duplicate(deployment, monkeypatch):
    """Keep existing deployment ownership explicit when rerunning the CLI."""
    monkeypatch.setenv('VOD_RUNPOD_ENDPOINT_ID', 'already-deployed')
    with pytest.raises(ValueError, match='duplicate'):
        deployment.module.deploy('registry.example/whisper:fixture', None)
    assert deployment.posts == []
