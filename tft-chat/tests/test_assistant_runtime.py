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
        self.other_skill = SkillDefinition(
            name="other", description="Another workflow", body="OTHER", path="other.md",
        )

    async def aselect(self, query, **kwargs):
        """Return factual or workflow selections according to the provider call."""
        self.queries.append((query, kwargs))
        return [self.reference] if "set_number" in kwargs else [self.skill, self.other_skill]

    def render(self, resources):
        """Render deterministic text for instruction-policy assertions."""
        return "\n".join(
            resource.content if isinstance(resource, ContextSnippet) else resource.body
            for resource in resources
        )


def registry(*, resources=True, root_name="root", root_skill_names=()):
    """Build an isolated graph with a nested handoff and restricted skills."""
    root = AssistantSpec(
        name=root_name, description="Root", handoff_description="Root",
        system_prompt="ROOT", task_prompt="TASK", path="root/system.md",
        model="gpt-6-luna", repository_context=resources,
        handoff_names=("child",) if resources else (), skill_names=root_skill_names,
    )
    child = replace(
        root, name="child", system_prompt="CHILD", task_prompt="",
        handoff_names=("leaf",), skill_names=("allowed",),
    )
    leaf = replace(child, name="leaf", system_prompt="LEAF", handoff_names=(), skill_names=("other",))
    result = AssistantRegistry([root, child, leaf])
    result.configure_tools(get_tool=lambda name: None, get_tool_group=lambda name: None,
                           list_tools=lambda: [])
    return result


def assistant(source=None, *, name="root", **kwargs):
    """Create an instance with fake selectors and an explicit set scope."""
    providers = Providers()
    return Assistant(
        name, registry=source or registry(), set_number=18,
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
    assert providers.queries[0][1] == {"set_number": 18}
    assert providers.queries[1][1] == {"allowed_names": ("allowed", "other")}
    assert messages[-1]["content"] == "What about her items?"
    assert invocation.input[-1]["content"] == "TASK\n\n## Input\n\nWhat about her items?"
    root, child = invocation.agent, invocation.agent.handoffs[0]
    leaf = child.handoffs[0]
    assert instructions(root, invocation) == "PREFIX\n\nROOT\n\nREFERENCE"
    assert instructions(child, invocation) == "CHILD\n\nREFERENCE\n\nSKILL"
    assert instructions(leaf, invocation) == "LEAF\n\nREFERENCE\n\nOTHER"
    assert "OTHER" not in instructions(child, invocation)
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


def test_captured_empty_prompt_candidate_keeps_dynamic_resources():
    """An explicit empty frozen prompt replaces the captured base, not policy."""
    graph = capture(registry())
    providers = Providers()
    instance = Assistant.from_capture(
        graph, "root", base_instructions_by_name={"child": ""},
        context_provider=providers, skill_provider=providers, set_number=18,
    )
    invocation = asyncio.run(instance.prepare("Question"))
    child = invocation.agent.handoffs[0]
    assert graph["specs"]["child"]["system_prompt"] == "CHILD"
    assert instructions(child, invocation) == "REFERENCE\n\nSKILL"


def test_unused_resources_skip_selectors():
    """Transcript-like roots do not perform irrelevant resource model calls."""
    instance, providers = assistant(registry(resources=False))
    invocation = asyncio.run(instance.prepare("Transcript"))
    assert providers.queries == []
    assert instructions(invocation.agent, invocation) == "ROOT"


def test_chat_never_receives_skills_even_when_its_spec_allows_them():
    """The chat root is excluded while eligible specialist handoffs still qualify."""
    instance, providers = assistant(
        registry(root_name="chat", root_skill_names=("allowed",)), name="chat",
    )
    invocation = asyncio.run(instance.prepare("Question"))
    assert providers.queries[1][1] == {"allowed_names": ("allowed", "other")}
    assert instructions(invocation.agent, invocation).endswith("REFERENCE")
    assert instructions(invocation.agent.handoffs[0], invocation).endswith("REFERENCE\n\nSKILL")


def test_contextualized_analytical_root_receives_its_allowed_skill():
    """A directly invoked analyst is a valid skill recipient and selector source."""
    source = AssistantRegistry([
        replace(
            registry(resources=False).get_spec("root"),
            name="data_analyst", repository_context=True,
            handoff_names=(), skill_names=("allowed",),
        ),
    ])
    source.configure_tools(get_tool=lambda name: None, get_tool_group=lambda name: None,
                           list_tools=lambda: [])
    instance, providers = assistant(source, name="data_analyst")
    invocation = asyncio.run(instance.prepare("Question"))
    assert providers.queries[1][1] == {"allowed_names": ("allowed",)}
    assert instructions(invocation.agent, invocation).endswith("REFERENCE\n\nSKILL")


def test_non_contextual_root_can_explicitly_opt_into_skills():
    """A named skill permission independently makes a no-facts root eligible."""
    source = AssistantRegistry([
        replace(
            registry(resources=False).get_spec("root"),
            name="custom_workflow", repository_context=False,
            handoff_names=(), skill_names=("allowed",),
        ),
    ])
    source.configure_tools(get_tool=lambda name: None, get_tool_group=lambda name: None,
                           list_tools=lambda: [])
    instance, providers = assistant(source, name="custom_workflow")
    invocation = asyncio.run(instance.prepare("Question"))
    assert providers.queries == [("Question", {"allowed_names": ("allowed",)})]
    assert instructions(invocation.agent, invocation) == "ROOT\n\nSKILL"


def test_unrestricted_recipient_opens_selector_pool_but_rendering_stays_scoped():
    """Unrestricted access selects from all skills, while explicit recipients filter."""
    source = registry()
    source.install(AssistantRegistry([
        replace(source.get_spec("root"), skill_names=()),
        replace(source.get_spec("child"), skill_names=None),
        replace(source.get_spec("leaf"), skill_names=("allowed",)),
    ]))
    instance, providers = assistant(source)
    invocation = asyncio.run(instance.prepare("Question"))
    assert providers.queries[1][1] == {}
    assert instructions(invocation.agent.handoffs[0], invocation).endswith("REFERENCE\n\nSKILL\nOTHER")
    assert instructions(invocation.agent.handoffs[0].handoffs[0], invocation).endswith("REFERENCE\n\nSKILL")


def test_non_contextual_handoff_is_not_a_skill_recipient():
    """A skill allowlist alone cannot make a non-contextual assistant eligible."""
    source = registry()
    source.install(AssistantRegistry([
        replace(source.get_spec("root"), name="chat", skill_names=None),
        replace(source.get_spec("child"), repository_context=False, skill_names=None),
        replace(source.get_spec("leaf"), skill_names=()),
    ]))
    instance, providers = assistant(source, name="chat")
    invocation = asyncio.run(instance.prepare("Question"))
    assert len(providers.queries) == 1
    assert providers.queries[0][1] == {"set_number": 18}
    assert "SKILL" not in instructions(invocation.agent.handoffs[0], invocation)


def test_shipped_graph_routes_three_skills_to_analyst_and_one_to_responder():
    """The production graph applies selection and allowlists at real recipients."""
    skill_names = (
        "tft-statistical-investigation",
        "tft-statistical-interpretation",
        "tft-unit-itemization",
    )

    class ShippedProviders(Providers):
        """Avoid live selectors while exercising shipped assistant specs."""

        async def aselect(self, query, **kwargs):
            """Return all three named skills for the runtime's candidate union."""
            self.queries.append((query, kwargs))
            if "set_number" in kwargs:
                return [self.reference]
            return [
                SkillDefinition(
                    name=name, description=name, body=f"MARKER:{name}",
                    path=f"{name}/SKILL.md",
                )
                for name in skill_names
            ]

        def render(self, resources):
            """Render unique markers so access boundaries are easy to inspect."""
            return "\n".join(
                resource.content if isinstance(resource, ContextSnippet)
                else resource.body
                for resource in resources
            )

    def find_agent(agent, name):
        """Find a named node in the freshly built production handoff graph."""
        if agent.name == name:
            return agent
        for child in agent.handoffs:
            found = find_agent(child, name)
            if found is not None:
                return found
        return None

    providers = ShippedProviders()
    invocation = asyncio.run(Assistant(
        "chat", set_number=18,
        context_provider=providers, skill_provider=providers,
    ).prepare("Compare item builds"))
    analyst = find_agent(invocation.agent, "data_analyst")
    responder = find_agent(invocation.agent, "final_responder")
    assert analyst is not None and responder is not None
    assert providers.queries[1][1] == {}
    chat_text = instructions(invocation.agent, invocation)
    analyst_text = instructions(analyst, invocation)
    responder_text = instructions(responder, invocation)
    assert all(f"MARKER:{name}" not in chat_text for name in skill_names)
    assert all(f"MARKER:{name}" in analyst_text for name in skill_names)
    assert "MARKER:tft-statistical-interpretation" in responder_text
    assert "MARKER:tft-statistical-investigation" not in responder_text
    assert "MARKER:tft-unit-itemization" not in responder_text


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
