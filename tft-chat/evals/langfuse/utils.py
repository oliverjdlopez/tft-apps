"""Content serialization and validation helpers for Langfuse integration."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import quote
from domain.assistants.constants import AssistantName

# ===========================================================================
# Content migration, snapshots, and remote resolution
# Keep shared content helpers here so purpose modules expose public operations.
# These helpers do not make model calls or change assistant specifications.
# ===========================================================================

SELECTORS = {
    "offline_selection_policy", "shortlist_required_recall", "final_required_recall",
    "required_skill_recall", "forbidden_context_excluded", "forbidden_skills_excluded",
    "payload_reduction", "selection_policy",
}


def canonical_json(value: Any) -> bytes:
    """Encode snapshot content deterministically, rejecting nonfinite numbers.

    Args:
        value: JSON-compatible evaluation content.

    Returns:
        Stable UTF-8 bytes suitable for review and content hashing.
    """
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def content_hash(value: bytes) -> str:
    """Hash exact content used by snapshots and catalog conflict checks."""
    return hashlib.sha256(value).hexdigest()


def catalog_revision(root: Path) -> str:
    """Return the exact catalog revision, including the initial absent state."""
    path = root / "catalog.json"
    return content_hash(path.read_bytes() if path.exists() else b"")


def atomic_write(path: Path, data: bytes) -> None:
    """Replace one file atomically after flushing its complete new contents.

    Args:
        path: Destination in a caller-authorized source or runtime directory.
        data: Complete replacement contents.
    """
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def default_config() -> dict[str, Any]:
    """Return isolated native webhook defaults shared by seeded datasets."""
    return {"action": "run", "cases": [], "variants": [{"name": "baseline", "model": None, "prompts": {}}],
            "dataset_version": None, "concurrency": 4, "repetitions": 1,
            "selection_live": False, "data_snapshot_label": None, "snapshot": None}


def check_assertion(assertion: dict[str, Any]) -> None:
    """Reject malformed grading definitions before submission can spend tokens."""
    from evals.models import EvalTrace
    from evals.trace import evaluate_trace_check
    name = assertion.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Assertion names must be nonempty")
    if name in {"weighted_score", "attempt_pass", "execution_success", "contract_pass"}:
        raise ValueError(f"Assertion name {name} is reserved for experiment summaries")
    for key, default in (("weight", 1), ("threshold", 1)):
        value = assertion.get(key, default)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"Assertion {name}: {key} must be finite")
        if (key == "weight" and value <= 0) or (key == "threshold" and not 0 <= value <= 1):
            raise ValueError(f"Assertion {name}: invalid {key}")
    kind = assertion.get("kind")
    if kind == "trace":
        evaluate_trace_check(assertion["check"], EvalTrace())
    elif kind == "selector":
        if assertion.get("selector") not in SELECTORS:
            raise ValueError(f"Unknown selector check: {assertion.get('selector')}")
    elif kind == "rubric":
        if not isinstance(assertion.get("rubric"), str) or not assertion["rubric"].strip():
            raise ValueError("Rubric text must be nonempty")
    else:
        raise ValueError(f"Unsupported check kind: {kind}")


def is_not_found(error: Exception) -> bool:
    """Recognize only explicit remote absence, never authentication or outages."""
    return getattr(error, "status_code", None) == 404


def utc_version(value: str | None) -> datetime:
    """Freeze a dataset read at a UTC instant before pagination begins."""
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("dataset_version must contain a UTC offset")
    return parsed.astimezone(timezone.utc)


def resolved_prompt(client: Any, reference: dict[str, Any]) -> dict[str, Any]:
    """Fetch a concrete text prompt, with server-resolved composition captured.

    Args:
        client: Langfuse SDK client.
        reference: Prompt name plus explicit version or label.

    Returns:
        Exact prompt name, version, and composed text for frozen execution.
    """
    if reference.get("version") is not None and reference.get("label") is not None:
        raise ValueError("Choose a prompt version or label, not both")
    options = {"version": reference["version"]} if reference.get("version") is not None else {"label": reference.get("label", "latest")}
    prompt = client.api.prompts.get(quote(reference["name"], safe=""), resolve=True, **options)
    if not isinstance(prompt.prompt, str) or not prompt.prompt.strip():
        raise ValueError(f"Prompt {reference['name']} must contain text")
    # The server expands composition. Unexpanded directives must never reach agents.
    if re.search(r"@@@langfusePrompt:|<langfuse_prompt", prompt.prompt):
        raise ValueError(f"Unresolved composed prompt: {reference['name']}")
    result = {"name": prompt.name, "version": prompt.version, "text": prompt.prompt}
    if getattr(prompt, "resolution_graph", None):
        result["resolution_graph"] = prompt.resolution_graph
    return result


def validate_frozen_config(config: dict[str, Any], suite: dict[str, Any]) -> None:
    """Validate frozen run controls and candidate targets without remote requests."""
    from .models import RunConfig
    inbound = deepcopy(config)
    for variant in inbound.get("variants", []):
        for target, reference in variant.get("prompts", {}).items():
            if not isinstance(reference.get("text"), str) or not reference["text"].strip():
                raise ValueError(f"Candidate {target} must be resolved before execution")
            if type(reference.get("version")) is not int or reference["version"] < 1:
                raise ValueError(f"Candidate {target} must have a concrete version")
            reference.pop("text")
            reference.pop("resolution_graph", None)
    RunConfig.model_validate(inbound)
    if config.get("dataset_version"):
        utc_version(config["dataset_version"])
    assistant = config.get("assistant") or suite.get("assistant")
    if config.get("assistant") is not None:
        if suite["family"] != "assistant" or suite["execution"] != "live":
            raise ValueError("Assistant selection requires a live assistant suite")
        from .prompts import repository_prompts
        if config["assistant"] not in repository_prompts():
            raise ValueError(f"Unknown assistant: {config['assistant']}")
    candidates = {target for variant in config.get("variants", []) for target in variant.get("prompts", {})}
    if not candidates:
        return
    if suite["family"] != "assistant" or suite["execution"] != "live":
        raise ValueError("Prompt candidates require a live assistant suite")
    from domain.assistants.registry import assistant_registry
    reachable = set()
    pending = [assistant]
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        pending.extend(assistant_registry.get_handoff_names(current))
    if candidates - reachable:
        raise ValueError(f"Prompt candidates target unreachable assistants: {sorted(candidates - reachable)}")


def validate_case_semantics(suite: dict[str, Any], items: list[dict[str, Any]]) -> None:
    """Retain registry and selector corpus preflight against the migrated content."""
    from .contracts import legacy_execution_item
    import domain.assistants
    items = [legacy_execution_item(item) for item in items if item.get("status", "ACTIVE") == "ACTIVE"]
    if suite["family"] == "assistant" and suite["execution"] == "live":
        from evals.utils import validate_registry_references
        validate_registry_references(suite["assistant"], items)
    elif suite["family"] in {"context_selection", "skill_selection"}:
        cases = [{**item["input"]["expected"], "name": item["metadata"]["case"], "query": item["input"]["input"]} for item in items]
        if suite["family"] == "context_selection":
            from evals.context_selection.utils import validate_cases
            from domain.providers.context import _all_context_candidates, discover_context_files
            validate_cases(cases, _all_context_candidates(discover_context_files(), set_number=None))
        else:
            from evals.skill_selection.utils import validate_cases, ignore_unknown_skill_references
            from domain.providers.skills import _discover_skills
            skills = _discover_skills()
            validate_cases(ignore_unknown_skill_references(cases, skills), skills)

# ===========================================================================
# Native grading resource identity and version comparison
#
# Names bootstrap stable identities once; subsequent startup follows IDs.
# Definition fingerprints deliberately exclude unrelated UI timestamps.
# ===========================================================================


def ensure_resource(workspace, existing: list[dict], path: str, name: str,
                    identity: str | None, definition: dict) -> dict:
    """Create only missing resources, recovering lost creation responses by name."""
    if identity:
        matches = [resource for resource in existing if resource['id'] == identity]
        if not matches:
            raise ValueError(f'Registered native resource is missing: {name}')
        return matches[0]
    matches = [resource for resource in existing if resource['name'] == name]
    if len(matches) > 1:
        raise ValueError(f'Ambiguous native resource name: {name}')
    if matches:
        return matches[0]
    created = workspace.request('POST', path, json=definition)
    existing.append(created)
    return created


def evaluator_signature(evaluator: dict) -> str:
    """Identify the scoring definition and effective state for drift detection."""
    return content_hash(canonical_json({key: evaluator.get(key) for key in (
        'id', 'version', 'versionId', 'type', 'prompt', 'modelConfig', 'variableMapping',
        'outputDefinition', 'status', 'pausedReason')}))


def semantic_grading_rule(rule: dict, grading: dict) -> dict:
    """Compare restored rule behavior using names instead of project-local IDs."""
    filters = deepcopy(rule['filter'])
    for condition in filters:
        if condition['column'] == 'datasetId':
            identities = grading.get('datasets', {})
            if any(identity not in identities for identity in condition['value']):
                raise ValueError('Portable replay requires exported dataset-name mappings for grading rules')
            condition['value'] = sorted(identities[identity] for identity in condition['value'])
    names = {value['id']: name for name, value in grading['evaluators'].items()}
    assignments = [{**assignment, 'evaluatorId': names[assignment['evaluatorId']]}
                   for assignment in rule['evaluatorAssignments']]
    return {'enabled': rule['enabled'], 'sampling': rule['sampling'],
            'filter': sorted(filters, key=canonical_json),
            'evaluatorAssignments': sorted(assignments, key=canonical_json)}


def configured_workspace():
    """Resolve maintenance credentials without copying them into frozen content."""
    from dotenv import dotenv_values
    from .workspace import Workspace
    local = dotenv_values(Path(__file__).parent / '.env')
    return Workspace(os.environ.get('LANGFUSE_BASE_URL', 'http://localhost:15500'),
                     os.environ.get('LANGFUSE_PUBLIC_KEY') or local['LANGFUSE_PUBLIC_KEY'],
                     os.environ.get('LANGFUSE_SECRET_KEY') or local['LANGFUSE_SECRET_KEY'])


def load_grading_registry() -> dict:
    """Read stable native resource IDs seeded for this deployment."""
    root = Path(os.environ.get('LANGFUSE_RUNTIME_DIR', str(Path(__file__).parent / '.runtime')))
    return json.loads((root / 'grading-resources.json').read_text())


def configured_native_workspace():
    """Resolve the local owner session for operations without public equivalents."""
    from dotenv import dotenv_values
    from .native import NativeWorkspace
    values = {**dotenv_values(Path(__file__).parent / '.env'), **os.environ}
    return NativeWorkspace(values.get('LANGFUSE_BASE_URL', 'http://localhost:15500'),
                           values['LANGFUSE_INIT_USER_EMAIL'], values['LANGFUSE_INIT_USER_PASSWORD'],
                           values.get('LANGFUSE_PROJECT_ID', 'chattft-evals'))


def native_score_name(name: str) -> str:
    """Fit native score-config names without losing the original diagnostic identity."""
    return name if len(name) <= 35 else name[:26] + '_' + content_hash(name.encode())[:8]


def deterministic_score_type(check: dict) -> str:
    """Use native Boolean types for predicates and numeric types for selector ratios."""
    predicates = {'offline_selection_policy', 'forbidden_context_excluded',
                  'forbidden_skills_excluded', 'selection_policy'}
    return 'BOOLEAN' if check['kind'] == 'trace' or check.get('selector') in predicates else 'NUMERIC'


# ===========================================================================
# Host runner lifecycle
# The launcher owns a detached process; Docker forwards over its Unix socket.
# Keep credentials in the environment and verify PID ownership before signals.
# ===========================================================================

def host_runner_environment(root: Path) -> dict[str, str]:
    """Build the host runner environment using local application and platform settings."""
    from dotenv import dotenv_values
    checkout = root.parent.parent
    environment = {**{k: v for k, v in dotenv_values(checkout / '.env').items() if v is not None},
                   **os.environ}
    environment.update({k: v for k, v in dotenv_values(root / '.env').items()
                        if v is not None and k.startswith('LANGFUSE_')})
    environment.update(LANGFUSE_BASE_URL='http://localhost:15500',
                       LANGFUSE_PUBLIC_URL='http://localhost:15500',
                       LANGFUSE_RUNTIME_DIR=str(root / '.runtime'),
                       LANGFUSE_SNAPSHOT_DIR=str(root / 'snapshots'),
                       PYTHONDONTWRITEBYTECODE='1')
    environment['PYTHONPATH'] = os.pathsep.join([str(checkout), str(checkout / 'app/backend'),
        str(checkout / 'app/backend/src'), environment.get('PYTHONPATH', '')])
    return environment


def host_runner_python(root: Path) -> str:
    """Select an eval-capable interpreter without modifying the application's venv."""
    import importlib.util
    import sys
    if importlib.util.find_spec('langfuse') is not None:
        return sys.executable
    dedicated = root / '.runtime/host-venv/bin/python'
    if dedicated.is_file():
        return str(dedicated)
    raise ValueError('Host evaluations require uv sync --locked --extra evals before startup')


def host_runner_pid(root: Path) -> int | None:
    """Return only a live PID whose command owns this checkout's runner socket."""
    try:
        pid = int((root / '.runtime/runner.pid').read_text())
        command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        if b'evals.langfuse.server:app' in command and os.fsencode(root / '.runtime/runner.sock') in command:
            return pid
    except (OSError, ValueError):
        pass
    return None


def host_runner_ready(root: Path) -> bool:
    """Check the actual queue consumer through its private local socket."""
    import httpx
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds=str(root / '.runtime/runner.sock')), timeout=2) as client:
            return client.get('http://runner/health').status_code == 200
    except httpx.HTTPError:
        return False

# ===========================================================================
# Playground request translation and completion streaming
# The native editor owns the draft; each request supplies an isolated override.
# Registered graph construction and database selection remain in evals.worker.
# ===========================================================================


def playground_assistants() -> list[str]:
    """List runnable Playground targets, excluding legacy-discovered router docs."""
    from domain.assistants import assistant_spec, list_assistants, reload_assistant_specs

    reload_assistant_specs()

    # The legacy markdown discoverer also sees AGENTS.md; it is repository
    # guidance, never an executable prompt or a useful default for the editor.
    names = [name for name in list_assistants() if Path(assistant_spec(name).path).name.lower() != "agents.md"]
    return sorted(names, key=lambda name: (name != AssistantName.CHAT, name))


def playground_payload(body) -> dict:
    """Translate native text messages into a bounded real-assistant invocation."""
    name = body.model.removeprefix("chattft/")
    if body.model != f"chattft/{name}" or name not in playground_assistants():
        raise ValueError("Select a chattft/<assistant> model from the ChatTFT backend connection")
    messages = []
    system = []
    for message in body.messages:
        content = message.content
        if isinstance(content, list):
            if any(part.get("type") != "text" or not isinstance(part.get("text"), str) for part in content):
                raise ValueError("ChatTFT Playground supports text messages only")
            content = "\n".join(part["text"] for part in content)
        if message.role in {"system", "developer"}:
            system.append(content)
        else:
            messages.append({"role": message.role, "content": content})
    users = [message["content"] for message in messages if message["role"] == "user"]
    if not users or not users[-1].strip():
        raise ValueError("Add a user message with the question or task to run")
    if sum(len(message.model_dump_json()) for message in body.messages) > 200_000:
        raise ValueError("Playground input exceeds 200,000 characters")
    settings = {key: getattr(body, key) for key in (
        "temperature", "top_p", "frequency_penalty", "presence_penalty") if getattr(body, key) is not None}
    maximum = body.max_completion_tokens or body.max_tokens
    if maximum is not None:
        settings["max_tokens"] = maximum
    return {
        "operation": "evaluate", "identity": {"suite": "playground", "case": name},
        "config": {"family": "assistant", "execution": "live", "assistant": name, "max_turns": 10,
                   "model_settings": settings,
                   "prompt_candidates": {name: {"text": "\n\n".join(system), "native_reference": None}} if system else {}},
        "input": {"input": users[-1], "messages": messages},
        "playground_messages": [message.model_dump() for message in body.messages],
    }


async def playground_stream(task, body):
    """Keep native SSE connections alive, then emit the complete graph answer."""
    import asyncio

    while not task.done():
        done, _ = await asyncio.wait({task}, timeout=5)
        if not done:
            yield ": ChatTFT is running tools and assistants\n\n"
    try:
        result = task.result()
        base = {key: result[key] for key in ("id", "created", "model")}
        base["object"] = "chat.completion.chunk"
        yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": result["choices"][0]["message"],
                                                           "finish_reason": None}]}) + "\n\n"
        yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\n"
        if (body.stream_options or {}).get("include_usage"):
            yield "data: " + json.dumps({**base, "choices": [], "usage": result["usage"]}) + "\n\n"
    except Exception as exc:
        yield "data: " + json.dumps({"error": {"message": str(exc), "type": "backend_error"}}) + "\n\n"
    yield "data: [DONE]\n\n"


async def close_proxy_stream(response, client) -> None:
    """Release both socket response and transport after native streaming ends."""
    await response.aclose()
    await client.aclose()
