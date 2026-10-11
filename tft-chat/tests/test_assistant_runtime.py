"""Verify consumer preparation, dynamic policy, and captured-run isolation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agents import RunContextWrapper

from domain.assistants import Assistant, AssistantRegistry
from domain.assistants.capture import capture
from domain.assistants.specs import AssistantSpec
from domain.providers.models import ContextSnippet, SkillDefinition
from domain.runtime.models import ToolActivity


class Providers:
    """Supply deterministic selections and retain their unwrapped queries."""

    def __init__(self):
        """Initialize selections independent of repository files and services."""
        self.queries = []
        self.reference = ContextSnippet(
            context_file="units", path="units.md", content="REFERENCE", line=1, score=1,
        )
        self.skill = SkillDefinition(
            name="allowed", description="A workflow", body="SKILL", path="skill.md",
        )

    async def aselect(self, query, **kwargs):
        """Return factual or workflow selections according to the provider call."""
        self.queries.append((query, kwargs))
        return [self.reference] if "set_number" in kwargs else [self.skill]

    def render(self, resources):
        """Render deterministic text for instruction-policy assertions."""
        return "\n".join(
            resource.content if isinstance(resource, ContextSnippet) else resource.body
            for resource in resources
        )


def registry(*, resources=True):
    """Build an isolated graph with a nested handoff and restricted skills."""
    root = AssistantSpec(
        name="root", description="Root", handoff_description="Root",
        system_prompt="ROOT", task_prompt="TASK", path="root/system.md",
        model="gpt-6-luna", repository_context=resources,
        handoff_names=("child",) if resources else (), skill_names=(),
    )
    child = replace(
        root, name="child", system_prompt="CHILD", task_prompt="",
        handoff_names=("leaf",), skill_names=("allowed",),
    )
    leaf = replace(child, name="leaf", system_prompt="LEAF", handoff_names=(), skill_names=())
    result = AssistantRegistry([root, child, leaf])
    result.configure_tools(get_tool=lambda name: None, get_tool_group=lambda name: None,
                           list_tools=lambda: [])
    return result


def assistant(source=None, **kwargs):
    """Create an instance with fake selectors and an explicit set scope."""
    providers = Providers()
    return Assistant(
        "root", registry=source or registry(), set_number=18,
        context_provider=providers, skill_provider=providers, **kwargs,
    ), providers


def instructions(agent, invocation):
    """Invoke the SDK instruction boundary without making a model call."""
    return agent.instructions(RunContextWrapper(invocation.context), agent)


def test_preparation_selects_once_and_renders_policy_at_every_depth():
    """A shared run retains resources while respecting root and skill boundaries."""
    instance, providers = assistant()
    messages = [{"role": "user", "content": "Tell me about Riven"},
                {"role": "assistant", "content": "A bruiser"},
                {"role": "user", "content": "What about her items?"}]
    invocation = asyncio.run(instance.prepare(messages, system="PREFIX", record=True))
    assert len(providers.queries) == 2
    assert all(query == "Tell me about Riven What about her items?" for query, _ in providers.queries)
    assert messages[-1]["content"] == "What about her items?"
    assert invocation.input[-1]["content"] == "TASK\n\n## Input\n\nWhat about her items?"
    root, child = invocation.agent, invocation.agent.handoffs[0]
    leaf = child.handoffs[0]
    assert instructions(root, invocation) == "PREFIX\n\nROOT\n\nREFERENCE"
    assert instructions(child, invocation) == "CHILD\n\nREFERENCE\n\nSKILL"
    assert instructions(leaf, invocation) == "LEAF\n\nREFERENCE"
    assert instructions(root, invocation) == invocation.instructions["root"]
    assert len(providers.queries) == 2
    assert invocation.model_settings["child"]["model"] == "gpt-6-luna"


def test_reused_instance_retains_definitions_but_never_run_state():
    """Registry refreshes and another run cannot modify a prepared invocation."""
    source = registry()
    instance, providers = assistant(source)
    source.install(AssistantRegistry([
        replace(source.get_spec(name), system_prompt="CHANGED")
        for name in source.list_assistants()
    ]))
    first = asyncio.run(instance.prepare("Question"))
    second = asyncio.run(instance.prepare("Another question"))
    assert instructions(first.agent, first).startswith("ROOT")
    assert instructions(second.agent, second).startswith("ROOT")
    assert first.agent is not second.agent
    assert first.agent.handoffs[0] is not second.agent.handoffs[0]
    assert first.context.evidence is not second.context.evidence
    assert first.context.activity is not second.context.activity
    assert first.hooks is not second.hooks
    assert first.context.runtime.request_id != second.context.runtime.request_id
    assert len(providers.queries) == 4


def test_captured_prompt_overrides_retain_policy_models_and_global_isolation():
    """Frozen candidates replace bases without replacing dynamic callbacks."""
    source = registry()
    graph = capture(source)
    providers = Providers()
    instance = Assistant.from_capture(
        graph, "root", base_instructions_by_name={"child": "CANDIDATE"},
        context_provider=providers, skill_provider=providers, set_number=18,
    )
    invocation = asyncio.run(instance.prepare("Question", record=True))
    child = invocation.agent.handoffs[0]
    assert instructions(child, invocation) == "CANDIDATE\n\nREFERENCE\n\nSKILL"
    assert child.model == graph["specs"]["child"]["resolved_model"]
    assert source.get_spec("child").system_prompt == "CHILD"
    assert graph["specs"]["child"]["system_prompt"] == "CHILD"
    assert invocation.input.startswith("TASK\n\n## Input")


def test_unused_resources_skip_selectors():
    """Transcript-like roots do not perform irrelevant resource model calls."""
    instance, providers = assistant(registry(resources=False))
    invocation = asyncio.run(instance.prepare("Transcript"))
    assert providers.queries == []
    assert instructions(invocation.agent, invocation) == "ROOT"


def test_default_models_are_frozen_for_graph_and_selector_dependencies(monkeypatch):
    """Operator configuration changes cannot split a captured invocation's models."""
    source = registry()
    source.install(AssistantRegistry([
        replace(source.get_spec(name), model=None) for name in source.list_assistants()
    ]))
    settings = SimpleNamespace(models=SimpleNamespace(openai_model="initial-model"))
    monkeypatch.setattr("core.config.load_config", lambda: settings)
    instance = Assistant("root", registry=source, set_number=18)
    settings.models.openai_model = "changed-model"
    assert instance.build_agent().model == "initial-model"
    assert instance.context_provider.registry.resolved_models["root"] == "initial-model"
    assert instance.skill_provider.registry is instance.context_provider.registry


def test_sync_and_async_entry_points_supply_the_same_run_contract(monkeypatch):
    """Both execution APIs supply typed context, task wrappers, and fresh state."""
    instance, _ = assistant(registry(resources=False))
    contexts = []

    async def run(agent, *, input, context, hooks, **kwargs):
        """Inspect invocation dependencies without an external runner."""
        contexts.append(context)
        assert input == "TASK\n\n## Input\n\nQuestion"
        assert callable(agent.instructions)
        assert context.runtime.root_assistant == "root"
        return SimpleNamespace(final_output="Answer")

    monkeypatch.setattr("domain.assistants.assistant.Runner.run", run)
    assert instance.run_sync("Question").final_output == "Answer"
    assert asyncio.run(instance.run("Question")).final_output == "Answer"
    assert contexts[0] is not contexts[1]


def test_run_sync_inside_event_loop_fails_without_creating_coroutine():
    """An async consumer receives clear guidance without a leaked coroutine."""
    instance, _ = assistant(registry(resources=False))

    async def run():
        """Exercise a synchronous entry point in an already running loop."""
        with pytest.raises(RuntimeError, match="await run"):
            instance.run_sync("Question")

    asyncio.run(run())


def test_failed_execution_finalizes_pending_activity(monkeypatch):
    """A failed model run retains terminal states for unfinished tool calls."""
    instance, _ = assistant(registry(resources=False))
    contexts = []

    async def fail(agent, *, context, **kwargs):
        """Simulate failure after a tool has started."""
        contexts.append(context)
        context.activity.calls["pending"] = ToolActivity("pending", "lookup")
        raise ValueError("Mock failure")

    monkeypatch.setattr("domain.assistants.assistant.Runner.run", fail)
    with pytest.raises(ValueError, match="Mock failure"):
        instance.run_sync("Question")
    assert contexts[0].activity.calls["pending"].status == "failed"
