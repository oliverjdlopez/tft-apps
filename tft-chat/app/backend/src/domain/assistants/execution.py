"""Execute a captured graph with the application's invocation dependencies."""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Any


async def execute_captured(prompt: str, config: dict[str, Any]) -> tuple[Any, dict]:
    """Run captured tools, instructions, wrappers, models, and access boundaries.

    Args:
        prompt: User question supplied to this invocation.
        config: Worker settings containing a versioned captured graph.

    Returns:
        SDK run result and actual instruction/resource provenance.
    """
    from agents import RunConfig, Runner
    from core.config import load_config
    from domain.assistants import create_assistant, prepare_resources, render_assistant_input
    from domain.assistants.capture import from_capture
    from domain.providers.context import RepositoryContextProvider
    from domain.providers.skills import RepositorySkillProvider
    from domain.runtime.models import AssistantRunContext, RuntimeSettings
    from domain.tools.evidence.models import EvidenceStore
    from domain.runtime.activity import ActivityRunHooks

    graph = config['captured_graph']
    registry = from_capture(graph)
    name = config['assistant']
    settings = load_config()
    context_provider = RepositoryContextProvider(registry=registry)
    skill_provider = RepositorySkillProvider(registry=registry)
    messages = config.get('messages') or [{'role': 'user', 'content': prompt}]
    resources = await prepare_resources(messages, context_provider=context_provider,
        skill_provider=skill_provider, set_number=settings.chat.set_number)
    context = AssistantRunContext(runtime=RuntimeSettings(request_id=uuid.uuid4().hex,
        set_number=settings.chat.set_number, root_assistant=name, surface='specs'),
        resources=resources, context_provider=context_provider,
        skill_provider=skill_provider, evidence=EvidenceStore())
    agent = create_assistant(name, registry=registry, model=config.get('model'),
        resolved_models={key: value['resolved_model'] for key, value in graph['specs'].items()})
    instructions: dict[str, str] = {}
    model_settings: dict[str, dict] = {}
    def record(current):
        """Wrap captured callbacks to record the actual model-facing instructions."""
        model_settings[current.name] = {'model': str(current.model), 'settings': current.model_settings.to_json_dict()}
        callback = current.instructions
        override = config.get('prompt_candidates', {}).get(current.name)
        if override is not None:
            # Historical explicit overrides replace only durable text; retain
            # captured context policy and task/configuration for the whole graph.
            from dataclasses import replace
            from domain.assistants.utils import instruction_callback
            callback = instruction_callback(replace(registry.get_spec(current.name), system_prompt=override['text']), root=current is agent)
        def render(wrapper, target):
            """Capture instructions at the SDK's invocation boundary."""
            text = callback(wrapper, target) if callable(callback) else callback
            instructions[target.name] = text
            return text
        current.instructions = render
        for child in current.handoffs:
            record(child)
    record(agent)
    input_value = render_assistant_input(name, prompt, registry=registry)
    if config.get('messages'):
        input_value = list(messages)
        # Task wrappers apply to the latest user message without dropping history.
        for index in range(len(input_value) - 1, -1, -1):
            if input_value[index]['role'] == 'user':
                input_value[index] = {**input_value[index], 'content': render_assistant_input(name, input_value[index]['content'], registry=registry)}
                break
    references = [{'path': reference.path, 'sha256': hashlib.sha256(reference.content.encode()).hexdigest()} for reference in resources.references]
    skills = [{'name': skill.name, 'path': skill.path, 'sha256': hashlib.sha256(skill.body.encode()).hexdigest()} for skill in resources.skills]
    metadata = {'assembled_instructions': instructions, 'captured_graph_hash': graph['hash'],
        'model_settings': model_settings, 'resources': {'references': references, 'skills': skills},
        'runtime': {'set_number': settings.chat.set_number, 'root_assistant': name, 'surface': 'specs'},
        'model': str(agent.model)}
    result = None
    try:
        result = await Runner.run(agent, input=input_value, context=context, hooks=ActivityRunHooks(),
            max_turns=config.get('max_turns') or 10, run_config=RunConfig(tracing_disabled=bool(config.get('workspace_trial'))))
    except Exception as exc:
        # A failed generation still has useful assembled policy and tool activity.
        # Return that evidence instead of losing it at the outer JSON boundary.
        metadata['execution_error'] = f'{type(exc).__name__}: {exc}'
    from dataclasses import asdict
    metadata['instruction_hashes'] = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in instructions.items()}
    metadata['activity'] = asdict(context.activity)
    return result, metadata


def run_captured(prompt: str, config: dict[str, Any]) -> tuple[Any, dict]:
    """Enter the asynchronous invocation pipeline from the isolated sync worker."""
    return asyncio.run(execute_captured(prompt, config))
