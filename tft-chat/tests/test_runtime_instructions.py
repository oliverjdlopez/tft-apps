"""Offline coverage of agent defaults, invocation overrides, and SDK dispatch."""

import asyncio
import json
from dataclasses import replace

import pytest
from agents import Model, RunConfig, RunContextWrapper, Runner
from agents.items import ModelResponse
from agents.tool_context import ToolContext
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

from domain.assistants import AssistantAgent, create_assistant
from domain.providers.models import ContextSnippet, SkillDefinition
from domain.runtime import AssistantRunContext, RuntimeSettings
from domain.tools import get_tool
from domain.assistants.constants import AssistantName


class ReferenceProvider:
    """Track offline factual selections and identify their renderer."""

    def __init__(self, label):
        """Retain an identifying label and independent selection history."""
        self.label = label
        self.calls = []

    async def aselect(self, query, *, set_number):
        """Return one complete reference without invoking a model."""
        self.calls.append((query, set_number))
        return [ContextSnippet(
            context_file=self.label, path=f"{self.label}.md",
            content=f"{self.label} facts", line=1, score=1,
        )]

    def render(self, references):
        """Identify the renderer separately from the resource contents."""
        return f"{self.label} renderer: " + ", ".join(item.content for item in references)


class WorkflowProvider:
    """Track offline skill selections and identify their renderer."""

    def __init__(self, label):
        """Retain an identifying label and independent selection history."""
        self.label = label
        self.calls = []

    async def aselect(self, query):
        """Return allowed and disallowed workflows for policy checks."""
        self.calls.append(query)
        return [SkillDefinition(
            name=name, description=name, body=f"{self.label} {name} workflow",
            path=f"{name}/SKILL.md",
        ) for name in ("allowed", "blocked")]

    def render(self, skills):
        """Render only the workflows permitted by the requesting agent."""
        return f"{self.label} renderer: " + ", ".join(skill.body for skill in skills)


def invocation(**overrides):
    """Create independent request state with optional provider overrides."""
    return AssistantRunContext(
        runtime=RuntimeSettings("test", 18, AssistantName.CHAT, system="CALLER PREFIX"),
        **overrides,
    )


def graph_agents(agent):
    """Visit every constructed agent, including nested handoff occurrences."""
    yield agent
    for target in agent.handoffs:
        yield from graph_agents(target)


@pytest.mark.parametrize("override_context,override_skills", [
    (False, False), (True, False), (False, True), (True, True),
])
def test_provider_precedence_and_shared_selection(override_context, override_skills):
    """Selection and rendering use independent overrides across the full graph."""
    defaults = ReferenceProvider("default"), WorkflowProvider("default")
    overrides = ReferenceProvider("override"), WorkflowProvider("override")
    agent = create_assistant(
        AssistantName.CHAT, model="offline", context_provider=defaults[0], skill_provider=defaults[1],
    )
    context = invocation(
        context_provider=overrides[0] if override_context else None,
        skill_provider=overrides[1] if override_skills else None,
        timing={},
    )
    reference_provider = overrides[0] if override_context else defaults[0]
    skill_provider = overrides[1] if override_skills else defaults[1]

    async def run():
        """Prepare once, then render several turns throughout the graph."""
        resources = await agent.prepare_resources([{"role": "user", "content": "Riven"}], context)
        assert context.resources is resources
        for target in graph_agents(agent):
            assert isinstance(target, AssistantAgent)
            assert target.context_provider is defaults[0]
            assert target.skill_provider is defaults[1]
            assert target.is_root is (target is agent)
            for _ in range(2):
                text = await target.get_system_prompt(RunContextWrapper(context))
                assert ("CALLER PREFIX" in text) is target.is_root
                if target.spec.repository_context:
                    assert f"{reference_provider.label} facts" in text
                    assert f"{reference_provider.label} renderer" in text
                if target.is_root:
                    assert "workflow" not in text

    asyncio.run(run())
    assert reference_provider.calls == [("Riven", 18)]
    assert skill_provider.calls == ["Riven"]
    assert (defaults[0] if override_context else overrides[0]).calls == []
    assert (defaults[1] if override_skills else overrides[1]).calls == []
    assert set(context.timing) == {
        "context_selection_ms", "skill_selection_ms", "instruction_assembly_ms",
    }


def test_clone_dispatch_uses_clone_spec_providers_and_permissions():
    """An SDK clone renders its own policy instead of a callback's old owner."""
    original = create_assistant(
        AssistantName.CHAT, model="offline", context_provider=ReferenceProvider("original"),
        skill_provider=WorkflowProvider("original"),
    )
    clone = original.clone(
        name="custom", is_root=False, tools=[], handoffs=[],
        spec=replace(original.spec, system_prompt="CLONE POLICY", skill_names=("allowed",)),
        context_provider=ReferenceProvider("clone"), skill_provider=WorkflowProvider("clone"),
    )
    context = invocation()

    async def run():
        """Exercise both the clone and root through the SDK instruction hook."""
        await clone.prepare_resources([{"role": "user", "content": "Riven"}], context)
        text = await clone.get_system_prompt(RunContextWrapper(context))
        assert text.startswith("CLONE POLICY")
        assert "clone renderer: clone facts" in text
        assert "clone allowed workflow" in text
        assert "blocked workflow" not in text
        assert "CALLER PREFIX" not in text
        restricted = clone.clone(spec=replace(clone.spec, repository_context=False, skill_names=()))
        assert await restricted.get_system_prompt(RunContextWrapper(context)) == "CLONE POLICY"
        assert await clone.get_system_prompt(RunContextWrapper(None)) == "CLONE POLICY"
        root_text = await original.get_system_prompt(RunContextWrapper(context))
        assert root_text.startswith("CALLER PREFIX")
        assert "original renderer: clone facts" in root_text
        assert "workflow" not in root_text

    asyncio.run(run())
    assert isinstance(clone, AssistantAgent)
    assert clone.instructions is original.instructions
    assert original.context_provider.calls == []


def test_provider_override_does_not_leak_between_invocations():
    """Reusing an agent preserves separate resources and dependencies per run."""
    default = ReferenceProvider("default")
    override = ReferenceProvider("override")
    agent = create_assistant(AssistantName.CHAT, model="offline", context_provider=default, skill_provider=WorkflowProvider("default"))
    first = invocation(context_provider=override)
    second = invocation()

    async def run():
        """Prepare overlapping requests using distinct factual providers."""
        await asyncio.gather(
            agent.prepare_resources([{"role": "user", "content": "Riven"}], first),
            agent.prepare_resources([{"role": "user", "content": "Ashe"}], second),
        )
        assert "override facts" in await agent.get_system_prompt(RunContextWrapper(first))
        assert "default facts" in await agent.get_system_prompt(RunContextWrapper(second))

    asyncio.run(run())
    assert default.calls == [("Ashe", 18)]
    assert override.calls == [("Riven", 18)]
    assert second.context_provider is None
    assert first.resources is not second.resources
    assert first.activity is not second.activity


@pytest.mark.parametrize("instructions", ["FROZEN", ""])
def test_explicit_instructions_and_custom_callbacks_take_precedence(instructions):
    """Preserve evaluation strings, empty overrides, and caller callbacks."""
    async def custom(ctx, agent):
        """Provide an explicit asynchronous handoff instruction override."""
        return f"CUSTOM {agent.name}"

    agent = create_assistant(
        AssistantName.CHAT, instructions=instructions,
        instructions_by_name={AssistantName.CHAT: "LOSING OVERRIDE", AssistantName.DATA_ANALYST: custom},
    )

    async def run():
        """Ask the SDK to resolve both static and asynchronous overrides."""
        assert await agent.get_system_prompt(RunContextWrapper(invocation())) == instructions
        analyst = next(target for target in agent.handoffs if target.name == AssistantName.DATA_ANALYST)
        assert await analyst.get_system_prompt(RunContextWrapper(invocation())) == f"CUSTOM {AssistantName.DATA_ANALYST}"

    asyncio.run(run())


@pytest.mark.parametrize("with_agent", [False, True])
def test_additional_context_honors_invocation_override(with_agent):
    """Tools use request overrides even with an agent carrying other defaults."""
    override = ReferenceProvider("override")
    default = ReferenceProvider("default")
    context = invocation(context_provider=override)
    agent = create_assistant(AssistantName.CHAT, context_provider=default) if with_agent else None
    payload = json.dumps({"request": {"query": "Riven"}})
    tool_context = ToolContext(
        context=context, agent=agent, tool_name="request_additional_context",
        tool_call_id="lookup", tool_arguments=payload,
    )
    result = asyncio.run(get_tool("request_additional_context").on_invoke_tool(tool_context, payload))
    assert result["context"] == "override renderer: override facts"
    assert result["complete_selected_collections"] is True
    assert context.resources.references == ()
    assert override.calls == [("Riven", 18)]
    assert default.calls == []


class HandoffModel(Model):
    """Drive a real SDK handoff and tool call without contacting a model API."""

    def __init__(self):
        """Keep the exact prompts and inputs received at each model step."""
        self.prompts = []
        self.inputs = []

    async def get_response(self, system_instructions, input, **kwargs):
        """Handoff, retrieve additional context, and finish deterministically."""
        self.prompts.append(system_instructions)
        self.inputs.append(input)
        step = len(self.prompts)
        if step < 3:
            output = [ResponseFunctionToolCall(
                id=f"call-{step}", call_id=f"call-{step}", type="function_call",
                name=f"transfer_to_{AssistantName.DATA_ANALYST}" if step == 1 else "request_additional_context",
                arguments="{}" if step == 1 else json.dumps({"request": {"query": "Ashe"}}),
            )]
        else:
            output = [ResponseOutputMessage(
                id="done", type="message", role="assistant", status="completed",
                content=[ResponseOutputText(type="output_text", text="done", annotations=[])],
            )]
        return ModelResponse(output=output, usage=Usage(), response_id=None)

    def stream_response(self, *args, **kwargs):
        """Reject unexpected streaming in this synchronous-run regression."""
        raise AssertionError("This test uses Runner.run")


def test_sdk_handoff_tool_uses_executing_agent_defaults():
    """The real runner preserves subclass behavior and tool provider ownership."""
    model = HandoffModel()
    root_provider = ReferenceProvider("root")
    target_provider = ReferenceProvider("target")
    skill_provider = WorkflowProvider("shared")
    root = create_assistant(AssistantName.CHAT, model=model, context_provider=root_provider, skill_provider=skill_provider)
    analyst = next(agent for agent in root.handoffs if agent.name == AssistantName.DATA_ANALYST)
    analyst.context_provider = target_provider
    context = invocation()

    async def run():
        """Prepare only once, then execute model steps with tracing disabled."""
        await root.prepare_resources([{"role": "user", "content": "Riven"}], context)
        return await Runner.run(root, "Riven", context=context, run_config=RunConfig(tracing_disabled=True))

    result = asyncio.run(run())
    assert result.final_output == "done"
    assert result.last_agent is analyst
    assert "root renderer: root facts" in model.prompts[0]
    assert "target renderer: root facts" in model.prompts[1]
    assert "target renderer: target facts" in str(model.inputs[-1])
    assert root_provider.calls == [("Riven", 18)]
    assert target_provider.calls == [("Ashe", 18)]
    assert skill_provider.calls == ["Riven"]
    assert context.resources.references[0].content == "root facts"
