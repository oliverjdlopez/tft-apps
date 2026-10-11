"""Idempotent content and native experiment-button setup for a local project."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from domain.assistants.constants import AssistantName
from .native import NativeWorkspace


def configure_triggers(client: Any, snapshots: Path, *, base_url: str, email: str, password: str, token: str) -> int:
    """Configure missing native UI buttons through the pinned authenticated API.

    Args:
        client: Authenticated Langfuse SDK client for dataset identity discovery.
        snapshots: Repository snapshot directory.
        base_url: Internal Langfuse web URL reachable from the experiment service.
        email: Bootstrap project owner's email address.
        password: Bootstrap password, never logged or embedded in snapshots.
        token: Secret bearer credential stored encrypted by Langfuse.

    Returns:
        Number of newly configured dataset buttons.
    """
    from .content import load_catalog, load_snapshot

    configured = 0
    project = os.environ.get("LANGFUSE_PROJECT_ID", "tft-apps-evals")
    native = NativeWorkspace(base_url, email, password, project)
    try:
        from .contracts import ACTIVE_WORKFLOW_SUITES, DATASET_NAMES
        for entry in load_catalog(snapshots):
            if os.environ.get("LANGFUSE_TEST_DEPLOYMENT") != "1" and entry["name"] not in ACTIVE_WORKFLOW_SUITES and not entry.get("managed_workflow"):
                continue
            if entry['name'] == AssistantName.ANALYZE_TRANSCRIPT:
                continue
            if entry['execution'] == 'fixture' and os.environ.get('LANGFUSE_TEST_DEPLOYMENT') != '1':
                continue
            dataset_name = (load_snapshot(entry["snapshot"], snapshots)["dataset_name"]
                            if entry.get("managed_workflow") else DATASET_NAMES[entry['name']])
            dataset = client.get_dataset(dataset_name)
            identity = {"datasetId": dataset.id}
            existing = native.call('getRemoteExperiment', identity, read=True)
            if existing is not None:
                try:
                    previous_payload = json.loads(existing.get('defaultPayload', '{}'))
                except (ValueError, TypeError):
                    continue
                # Migrate only the exact owned legacy default. Authored settings
                # and other webhook endpoints remain operator-owned.
                if existing.get('url') != 'http://experiments/experiments' or previous_payload != {'variants': [{'name': 'baseline'}]}:
                    continue
            native.call('upsertRemoteExperiment', {
                **identity, "url": "http://experiments/experiments",
                "defaultPayload": json.dumps({"variants": [{"name": "Active"}]}, indent=2),
                "enabled": existing.get("enabled", True) if existing else True, "signingEnabled": existing.get("signingEnabled", False) if existing else False,
                "requestHeaders": existing.get("requestHeaders", {"Authorization": {"value": f"Bearer {token}", "secret": True}}) if existing else {"Authorization": {"value": f"Bearer {token}", "secret": True}},
            })
            configured += 1
    finally:
        native.close()
    return configured


def main() -> None:
    """Seed missing definitions, then enable native UI-triggered agent runs."""
    from langfuse import Langfuse
    from .content import seed_content

    root = Path(os.environ.get("LANGFUSE_SNAPSHOT_DIR", str(Path(__file__).parent / "snapshots")))
    client = Langfuse()
    try:
        seeded = seed_content(client, root, natural=True,
                              include_fixtures=os.environ.get('LANGFUSE_TEST_DEPLOYMENT') == '1')
        from .grading import seed_grading
        from .utils import configured_workspace
        from core.config import load_config
        workspace = configured_workspace()
        try:
            from .playground import configure_connection
            configure_connection(workspace, os.environ["LANGFUSE_EXPERIMENT_TOKEN"])
            settings = load_config()
            from .content import load_catalog, load_snapshot
            managed_names = {load_snapshot(entry['snapshot'], root)['dataset_name']
                             for entry in load_catalog(root) if entry.get('managed_workflow')}
            seed_grading(workspace, workspace.list('v2/datasets'),
                         Path(os.environ.get('LANGFUSE_RUNTIME_DIR', str(Path(__file__).parent / '.runtime'))) / 'grading-resources.json',
                         model=os.environ.get('EVAL_JUDGE_MODEL') or settings.models.openai_model,
                         api_key='mock-key' if os.environ.get('LANGFUSE_TEST_DEPLOYMENT') == '1' else settings.secrets.openai_api_key,
                         base_url='http://mock-model:8000/v1' if os.environ.get('LANGFUSE_TEST_DEPLOYMENT') == '1' else None,
                         managed_names=managed_names)
            from .grading import seed_diagnostic_configs
            seed_diagnostic_configs(workspace,
                Path(os.environ.get('LANGFUSE_RUNTIME_DIR', str(Path(__file__).parent / '.runtime'))) / 'grading-resources.json', root)
        finally:
            workspace.close()
        configured = configure_triggers(
            client, root, base_url=os.environ.get("LANGFUSE_BASE_URL", "http://localhost:15510"),
            email=os.environ.get("LANGFUSE_INIT_USER_EMAIL", "evals@chattft.local"),
            password=os.environ["LANGFUSE_INIT_USER_PASSWORD"], token=os.environ["LANGFUSE_EXPERIMENT_TOKEN"],
        )
        print(json.dumps({"content": seeded, "configured_triggers": configured}))
    finally:
        client.flush()


if __name__ == "__main__":
    main()
