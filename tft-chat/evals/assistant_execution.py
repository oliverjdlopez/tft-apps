"""Execute a captured graph with the application's invocation dependencies."""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from domain.assistants.registry import AssistantRegistry


async def execute_captured(prompt: str, config: dict[str, Any]) -> tuple[Any, dict]:
    """Run captured tools, instructions, wrappers, models, and access boundaries.

    Args:
        prompt: User question supplied to this invocation.
        config: Worker settings containing a versioned captured graph.

    Returns:
        SDK run result and actual instruction/resource provenance.
    """
    from agents import ModelSettings, RunConfig
    from domain.runtime.execution import create_context, run
    from devtools.assistants import assistant_from_capture, record_invocation

    require_capture(config)
    lineage = config.get('workspace_lineage') or {}
    workspace_run = config.get('workspace_trial') or 'draft_revision' in lineage
    surface = config.get('surface') or ('specs' if workspace_run else 'eval')
    graph = config['captured_graph']
    assistant = await asyncio.to_thread(
        assistant_from_capture, graph, config['assistant'], model=config.get('model'),
        prompt_candidates={
            name: candidate['text']
            for name, candidate in config.get('prompt_candidates', {}).items()
        },
    )
    agent = assistant
    recording = record_invocation(agent)
    context = await asyncio.to_thread(create_context, assistant, surface=surface)
    resources = context.resources
    instructions = recording.instructions
    model_settings = recording.model_settings
    metadata = {'assembled_instructions': instructions, 'captured_graph_hash': graph['hash'],
        'model_settings': model_settings, 'resources': {},
        'runtime': {'set_number': context.runtime.set_number, 'root_assistant': assistant.name, 'surface': surface},
        'model': str(agent.model), 'run_model_settings': config.get('model_settings', {})}
    result = None
    try:
        result = await run(agent, config.get('messages') or prompt, context=context,
            max_turns=config.get('max_turns') or 10, run_config=RunConfig(tracing_disabled=bool(config.get('workspace_trial')),
                model_settings=ModelSettings(**config['model_settings']) if config.get('model_settings') else None))
    except Exception as exc:
        # A failed generation still has useful assembled policy and tool activity.
        # Return that evidence instead of losing it at the outer JSON boundary.
        metadata['execution_error'] = f'{type(exc).__name__}: {exc}'
    from dataclasses import asdict
    metadata['resources'] = {
        'reads': [{'id': read.id, 'path': read.path, 'kind': read.kind, 'sha256': read.sha256,
                   'content_sha256': hashlib.sha256(read.content.encode()).hexdigest(),
                   'record_ids': list(read.record_ids)} for read in resources.reads.values()],
    }
    metadata['instruction_hashes'] = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in instructions.items()}
    metadata['activity'] = asdict(context.activity)
    return result, metadata


def run_captured(prompt: str, config: dict[str, Any]) -> tuple[Any, dict]:
    """Enter the asynchronous invocation pipeline from the isolated sync worker."""
    return asyncio.run(execute_captured(prompt, config))


def require_capture(config: dict[str, Any]) -> AssistantRegistry:
    """Validate worker graph and candidate targets before any model execution.

    Args:
        config: Worker configuration with root identity and captured definitions.

    Returns:
        Validated isolated registry for the captured graph.

    Raises:
        ValueError: If the graph is absent or candidate targets are invalid.
    """
    from devtools.assistants import registry_from_capture

    if not config.get('captured_graph'):
        raise ValueError('Live assistant execution requires a captured graph; export a fresh bundle before running it.')
    definitions = registry_from_capture(config['captured_graph'])
    names = set(
        definitions.registry.reachable_assistant_names[config['assistant']]
    )
    if set(config.get('prompt_candidates', {})) - names:
        raise ValueError('Prompt candidates target assistants outside the captured execution graph')
    return definitions.registry


def require_bundle_captures(bundle: dict[str, Any]) -> None:
    """Preflight live assistant variants without making historical files unreadable.

    Args:
        bundle: Frozen evaluation bundle being submitted or executed.

    Raises:
        ValueError: If any live assistant variant lacks a valid graph.
    """
    suite = bundle['suite']
    if suite['family'] != 'assistant' or suite['execution'] != 'live':
        return
    config = bundle['config']
    graphs = bundle.get('execution', {}).get('graphs', {})
    if set(graphs) != {variant['name'] for variant in config['variants']}:
        raise ValueError('Live assistant execution requires a captured graph for every variant; export a fresh bundle before running it.')
    for variant in config['variants']:
        require_capture({'assistant': config.get('assistant') or suite['assistant'],
                         'captured_graph': graphs[variant['name']],
                         'prompt_candidates': variant.get('prompts', {})})


def current_execution(suite: dict, variants: list[dict]) -> dict:
    """Freeze repository configuration for evaluation variants and Playground.

    Args:
        suite: Workflow metadata identifying the root assistant.
        variants: Named variants that each receive an independent graph copy.

    Returns:
        Versioned execution graphs and repository lineage metadata.
    """
    from copy import deepcopy
    from domain.assistants.constants import ASSISTANT_SPECS_DIR, ROOT_DIR
    from devtools.assistants import capture, registry_from_files
    from devtools.assistants.workspace.workspace import Workspace
    workspace = Workspace(ROOT_DIR, ASSISTANT_SPECS_DIR)
    definitions = registry_from_files(workspace.source_files())
    names = list(definitions.registry.reachable_assistant_names[suite['assistant']])
    graph = capture(definitions, names)
    return {'version': 1, 'graphs': {variant['name']: deepcopy(graph) for variant in variants},
            'lineage': {'origin': 'repository', 'active_graph_hash': graph['hash']}}
