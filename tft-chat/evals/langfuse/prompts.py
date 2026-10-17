"""Manage repository-owned assistant prompts without rewriting authored versions."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from urllib.parse import quote

from .utils import atomic_write, canonical_json, repository_prompts
from .workspace import configured_workspace


def experiment_prompts(suite: dict) -> dict[str, dict]:
    """Limit a fresh assistant experiment to prompts in its current handoff graph.

    Args:
        suite: Execution metadata for the selected workflow.

    Returns:
        Current reachable prompt identities, without reading historical inventories.
    """
    from domain.assistants.registry import current_registry

    available = repository_prompts()
    if suite.get("execution") == "fixture":
        return {}
    registry = current_registry()
    selected = {}
    for name in registry.reachable_assistant_names[suite["assistant"]]:
        if name not in available:
            raise ValueError(f"Workflow targets missing assistant: {name}")
        selected[name] = available[name]
    return selected


def sync_prompts(*, remove: list[str], apply: bool = False,
                 backup_dir: Path | None = None, workspace=None) -> dict:
    """Preview or reconcile prompts, backing up every explicitly removed version.

    Args:
        remove: Retired assistant names whose owned Langfuse prompts may be deleted.
        apply: Whether to execute the freshly computed plan.
        backup_dir: Required backup parent when deleting hosted prompt versions.
        workspace: Optional transport supplied by focused tests.

    Returns:
        Planned identities and completed operations, including a recovery directory.
    """
    import httpx
    from domain.assistants.specs import ASSISTANT_SPECS_DIR, ROOT_DIR
    from scripts.assistant_specs.utils import removal_dependencies, spec_inventory, validate_name

    desired = repository_prompts()
    retired = sorted(set(validate_name(name) for name in remove))
    for name in retired:
        if name in desired:
            raise ValueError(f"Remove the repository spec before its Langfuse prompt: {name}")
        blockers = removal_dependencies(name, spec_inventory(ASSISTANT_SPECS_DIR), ROOT_DIR)
        if blockers:
            raise ValueError("Resolve removal dependencies first:\n" + "\n".join(blockers))
    owned_workspace = workspace is None
    try:
        workspace = configured_workspace() if owned_workspace else workspace
    except KeyError:
        raise ValueError("Configure Langfuse first with python -m evals up.") from None
    backup = None
    try:
        inventory = {row["name"]: row for row in workspace.list("v2/prompts")}
        create = [prompt for prompt in desired.values() if prompt["name"] not in inventory]
        delete = [f"chattft/assistants/{name}" for name in retired
                  if f"chattft/assistants/{name}" in inventory]
        result = {"create": [row["name"] for row in create], "remove": delete,
                  "already_absent": [name for name in retired if f"chattft/assistants/{name}" not in inventory],
                  "created": [], "deleted_versions": [], "applied": False}
        if not apply:
            return result
        if delete and backup_dir is None:
            raise ValueError("Deleting hosted prompts requires --backup-dir.")
        versions = []
        if delete:
            # Preserve all versions, labels, and config. Other prompts can compose
            # these prompts, so inspect those definitions before changing anything.
            for name, entry in inventory.items():
                for version in sorted(entry["versions"]):
                    definition = workspace.request("GET", "v2/prompts/" + quote(name, safe=""),
                                                   params={"version": version, "resolve": False})
                    if name in delete:
                        versions.append(definition)
                    elif any(target in json.dumps(definition.get("prompt")) for target in delete):
                        raise ValueError(f"Prompt {name} version {version} references a prompt being removed.")
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix="langfuse-prompts-", dir=backup_dir))
            atomic_write(backup / "prompts.json", canonical_json(versions))
            result["backup"] = str(backup)
        try:
            if repository_prompts() != desired:
                raise ValueError("Repository specs changed during synchronization; preview again.")
            for prompt in create:
                workspace.request("POST", "v2/prompts", json={"name": prompt["name"], "prompt": prompt["text"],
                                  "type": "text", "labels": ["baseline"]})
                result["created"].append(prompt["name"])
            for definition in versions:
                endpoint = "v2/prompts/" + quote(definition["name"], safe="")
                params = {"version": definition["version"]}
                current = workspace.request("GET", endpoint, params={**params, "resolve": False})
                # Ascending deletion avoids moving the platform's latest label
                # onto an older version that is still waiting to be removed.
                if current != definition:
                    raise ValueError(f"Prompt changed after backup: {definition['name']}; preview again.")
                # Delete only backed-up versions, never a concurrently created one.
                workspace.request("DELETE", endpoint, params=params)
                result["deleted_versions"].append({"name": definition["name"], **params})
            result["applied"] = True
        finally:
            if backup is not None:
                atomic_write(backup / "journal.json", canonical_json(result))
        return result
    except httpx.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        recovery = f" Review {backup / 'journal.json'} before retrying." if backup else ""
        raise ValueError(f"Langfuse request failed (status {status or 'unavailable'}).{recovery}") from None
    except ValueError as exc:
        if backup is not None:
            raise ValueError(f"{exc} Review {backup / 'journal.json'} before retrying.") from None
        raise
    finally:
        if owned_workspace:
            workspace.close()


def publish_graph_prompts(client, graph: dict) -> dict:
    """Publish captured instruction copies with configuration-bound identities.

    Args:
        client: Langfuse client used to resolve or create managed prompt copies.
        graph: Captured assistant definitions and their configured instructions.

    Returns:
        Prompt text and exact remote version for every captured assistant.
    """
    from devtools.assistants import digest
    from .utils import is_not_found, resolved_prompt

    result = {}
    for assistant, definition in graph['specs'].items():
        # Configuration is part of version identity even when instructions match.
        specification_hash = digest(definition)
        name = f'chattft/workspace/{assistant}/{specification_hash}'
        try:
            prompt = resolved_prompt(client, {'name': name, 'label': 'latest'})
            if prompt['text'] != definition['system_prompt']:
                raise ValueError('Managed prompt identity has different instruction bytes')
        except Exception as exc:
            if not is_not_found(exc):
                raise
            created = client.create_prompt(name=name, type='text', prompt=definition['system_prompt'],
                config={'assistant': assistant, 'specification_hash': specification_hash, 'specification': definition}, labels=[])
            prompt = ({'name': created.name, 'version': created.version, 'text': definition['system_prompt']}
                      if created is not None else resolved_prompt(client, {'name': name, 'label': 'latest'}))
        result[assistant] = prompt
    return result
