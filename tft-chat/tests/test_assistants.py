from __future__ import annotations
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agents import Agent
from agents.extensions.models.litellm_model import LitellmModel

from core.config import load_config
from domain.assistants import Assistant
from domain.assistants.registry import current_registry
from domain.assistants.models import AssistantSpec
from domain.assistants.specs import load_assistant_spec
from devtools.assistants import diagnostics
from domain.assistants.utils import wrap_task_input
from domain.constants import OpenAIModels, ReasoningEfforts
from domain.tools.db_tools.cohort_tools import COHORT_TOOL_GROUP
from domain.tools.db_tools.deltas import DELTA_TOOL_GROUP
from domain.tools.db_tools.ranking_tools import RANKING_TOOL_GROUP
from domain.tools.context import CONTEXT_TOOL_GROUP
from domain.tools.rolldown import PROBABILITY_TOOL_GROUP


def test_assistant_spec_coerces_model_and_reasoning_enums() -> None:
    spec = AssistantSpec(
        name="enum_test",
        description="Enum test",
        handoff_description="Enum test",
        system_prompt="System",
        task_prompt="Task",
        path="test.md",
        model=OpenAIModels.LATEST.value,
        reasoning="high",
    )

    assert spec.model == OpenAIModels.LATEST
    assert spec.reasoning == ReasoningEfforts.HIGH
    assert spec.resolved_model() == OpenAIModels.LATEST.value
    assert spec.model_settings().reasoning.effort == "high"



@pytest.mark.parametrize("changes, field", [
    ({"name": " "}, "name"),
    ({"system_prompt": None}, "system_prompt"),
    ({"repository_context": "false"}, "repository_context"),
    ({"include_all_tools": 1}, "include_all_tools"),
    ({"tool_names": "read_resource"}, "tool_names"),
    ({"handoff_names": [None]}, "handoff_names"),
    ({"skill_names": [""]}, "skill_names"),
    ({"playbook_names": True}, "playbook_names"),
    ({"model": "unknown"}, "model"),
    ({"reasoning": "unknown"}, "reasoning"),
])
def test_spec_invariants_apply_to_direct_replacements(changes, field):
    """Changing a definition cannot bypass checks by skipping the file loader."""
    with pytest.raises(ValueError, match=field):
        replace(current_registry().get_spec("chat"), **changes)


def test_spec_normalizes_lists_without_sharing_mutable_inputs():
    """Repeated names are harmless; captured access cannot change with input lists."""
    names = [" read_resource ", "read_resource"]
    spec = replace(current_registry().get_spec("chat"), tool_names=names,
                   skill_names=None, playbook_names=[], description="", handoff_description="")
    names.append("present_evidence")
    assert spec.tool_names == ("read_resource",)
    assert spec.skill_names is None
    assert spec.playbook_names == ()
    assert spec.description == spec.handoff_description == ""

def test_loaded_assistant_specs_include_model_and_reasoning() -> None:
    spec = current_registry().get_spec("chat")

    assert spec.model is None
    assert spec.resolved_model() == load_config().models.openai_model
    assert spec.reasoning == ReasoningEfforts.MEDIUM


def test_skill_allowlist_defaults_to_all_and_loads_named_entries(tmp_path: Path) -> None:
    """Omitted skills stay unrestricted while a JSON list becomes an allowlist."""
    unrestricted_dir = tmp_path / "unrestricted"
    unrestricted_dir.mkdir()
    (unrestricted_dir / "system.md").write_text("# Unrestricted\n", encoding="utf-8")
    base = {
        "description": "Fixture",
        "handoff_description": "Fixture handoff",
        "tools": [],
        "context": {"repository": False},
        "handoffs": [],
    }
    (unrestricted_dir / "agent.json").write_text(
        json.dumps({**base, "name": "unrestricted"}), encoding="utf-8"
    )
    restricted_dir = tmp_path / "restricted"
    restricted_dir.mkdir()
    (restricted_dir / "system.md").write_text("# Restricted\n", encoding="utf-8")
    (restricted_dir / "agent.json").write_text(
        json.dumps({**base, "name": "restricted", "skills": ["comparison"]}),
        encoding="utf-8",
    )

    assert load_assistant_spec(unrestricted_dir, root_dir=tmp_path).skill_names is None
    assert load_assistant_spec(restricted_dir, root_dir=tmp_path).skill_names == (
        "comparison",
    )




def test_assistant_specs_declare_prompt_context_policy() -> None:
    assert current_registry().get_spec("chat").repository_context is True
    assert current_registry().get_spec("data_analyst").repository_context is True
    for name in (
        "comp_expert",
        "item_expert",
        "meta_expert",
        "theorizer",
        "unit_expert",
    ):
        assert current_registry().get_spec(name).repository_context is True
    assert current_registry().get_spec("distill-transcript").repository_context is False


def test_constructor_builds_sdk_agent_with_spec_model_settings() -> None:
    agent = Assistant("chat").agent

    assert isinstance(agent, Agent)
    assert agent.model == load_config().models.openai_model
    assert agent.model_settings.reasoning.effort == ReasoningEfforts.MEDIUM.value
    assert callable(agent.instructions)


def test_task_input_uses_spec_task_prompt() -> None:
    spec = AssistantSpec(
        name="context_test",
        description="Context test",
        handoff_description="Context test",
        system_prompt="BASE INSTRUCTIONS",
        task_prompt="Complete this task.",
        path="test.md",
    )
    assert wrap_task_input("Tell me about Riven", spec.task_prompt) == (
        "Complete this task.\n\n## Input\n\nTell me about Riven"
    )


def test_create_agent_returns_fresh_instances_and_handoff_graphs() -> None:
    first = Assistant("chat").agent
    second = Assistant("chat").agent
    first_handoffs = {agent.name: agent for agent in first.handoffs}
    second_handoffs = {agent.name: agent for agent in second.handoffs}

    assert first is not second
    assert first_handoffs.keys() == second_handoffs.keys()
    assert all(first_handoffs[name] is not second_handoffs[name] for name in first_handoffs)


def test_durable_overrides_retain_dynamic_callbacks() -> None:
    """Replacing prompts preserves runtime instruction policy on every agent."""
    from devtools.assistants import assistant_from_registry

    source = current_registry()
    agent = assistant_from_registry(
        source,
        'chat',
        prompt_candidates={
            'chat': 'ROOT INSTRUCTIONS',
            'data_analyst': 'ANALYST INSTRUCTIONS',
        },
    ).agent
    from agents import RunContextWrapper
    from domain.runtime import AssistantRunContext, PreparedResources, RuntimeSettings
    context = AssistantRunContext(
        runtime=RuntimeSettings(
            request_id="test", set_number=18, root_assistant="chat",
        ),
        resources=PreparedResources(),
        evidence=None,
    )
    assert callable(agent.instructions)
    assert agent.instructions(RunContextWrapper(context), agent) == 'ROOT INSTRUCTIONS'
    analyst = next(child for child in agent.handoffs if child.name == 'data_analyst')
    assert analyst.instructions(RunContextWrapper(context), analyst) == 'ANALYST INSTRUCTIONS'


def test_agent_graph_token_log_includes_tool_definitions(monkeypatch) -> None:
    """Agent graph diagnostics include tool and handoff token totals."""
    records: list[str] = []
    monkeypatch.setattr(diagnostics.prompt_token_logger, "info", records.append)

    assistant = Assistant("chat")
    diagnostics.log_agent_graph(
        assistant.agent, task_prompt=assistant.spec.task_prompt,
    )

    payload = json.loads(records[0])
    root = payload["agents"][0]
    assert payload["event"] == "agent_graph"
    assert root["assistant"] == "chat"
    assert root["tool_count"] > 0
    assert root["handoff_count"] > 0
    assert root["tokens"]["tools"] > 0
    assert root["tokens"]["handoffs"] > 0
    assert root["instructions_kind"] == "dynamic"
    assert root["tokens"]["instructions"] is None






def test_data_analyst_owns_focused_ranking_cohort_and_context_tools() -> None:
    registry = current_registry()
    spec = registry.get_spec("data_analyst")
    ranking_names = [tool.name for tool in RANKING_TOOL_GROUP.tools]
    cohort_names = [tool.name for tool in COHORT_TOOL_GROUP.tools]
    delta_names = [tool.name for tool in DELTA_TOOL_GROUP.tools]
    context_names = [tool.name for tool in CONTEXT_TOOL_GROUP.tools]

    assert "data_analyst" in list(current_registry().assistant_names)
    assert spec.tool_group_keys == ("ranking", "query_cohorts", "deltas", "context")
    assert list(registry.tool_names[spec.name]) == (
        ranking_names + cohort_names + delta_names + context_names
    )
    assert list(registry.handoff_names[spec.name]) == ["final_responder"]
    assert spec.task_prompt == ""
    assert wrap_task_input("Which carry is better?", spec.task_prompt) == (
        "Which carry is better?"
    )
    assert "Choose the narrowest tool" in spec.system_prompt
    assert "Use a `group_by_*` switch only when" in spec.system_prompt
    for tool_name in (
        "rank_units",
        "rank_items",
        "rank_traits",
        "rank_unit_loadouts",
        "get_cohort_unit_deltas",
        "get_cohort_item_deltas",
        "get_cohort_trait_deltas",
    ):
        assert f"`{tool_name}`" in spec.system_prompt
    assert "Delta rows are ordered by frequency, not effect size" in spec.system_prompt
    assert "cohort investigations that need more than a direct lookup" in spec.handoff_description


def test_item_and_unit_experts_receive_an_unfiltered_data_view() -> None:
    for name in ("item_expert", "unit_expert"):
        prompt = current_registry().get_spec(name).system_prompt
        assert "aggregate" in prompt


@pytest.mark.parametrize(
    "name", ["comp_expert", "item_expert", "unit_expert", "data_analyst"]
)
def test_cohort_prompts_distinguish_presence_from_holder_binding(name: str) -> None:
    """Keep cohort guidance consistent with the registered item-condition schema.

    Args:
        name: Assistant whose cohort guidance must match item-filter capabilities.
    """
    from domain.tools.db_tools.models import ItemCondition

    prompt = current_registry().get_spec(name).system_prompt
    fields = ItemCondition.model_fields
    assert {"holder", "holder_star_level", "min_copies", "max_copies"} <= fields.keys()
    assert "name-only item" in prompt
    assert "`holder`" in prompt
    assert "`holder_star_level`" in prompt
    assert "separate unit and item conditions do not imply holder binding" in prompt.lower() or (
        "a separate unit condition does not bind the item" in prompt.lower()
    )
    assert "across multiple matching holders" in prompt
    assert "does not identify its holder" not in prompt
    assert "It does not bind an item to a unit" not in prompt


def test_prompt_evidence_guidance_matches_assistant_ownership() -> None:
    """Reserve display policy for the responder and histogram retrieval for the analyst."""
    chat = current_registry().get_spec("chat").system_prompt
    analyst = current_registry().get_spec("data_analyst").system_prompt
    responder = current_registry().get_spec("final_responder").system_prompt
    assert "## Evidence displays" not in chat
    assert "no direct match-data tools" not in chat
    assert "A direct lookup or ranking is sufficient when its result answers the actual question" in chat
    assert "Preserve these" not in analyst
    assert "`compare_cohorts`; a mean does not establish a distribution" in analyst
    assert "hand off to `final_responder`" in analyst
    assert "Use `present_evidence` once" in responder


def test_chat_has_direct_context_ranking_and_probability_tools() -> None:
    registry = current_registry()
    spec = registry.get_spec("chat")
    tool_names = list(registry.tool_names[spec.name])

    context_names = [tool.name for tool in CONTEXT_TOOL_GROUP.tools]
    ranking_names = [tool.name for tool in RANKING_TOOL_GROUP.tools]
    probability_names = [tool.name for tool in PROBABILITY_TOOL_GROUP.tools]
    cohort_names = [tool.name for tool in COHORT_TOOL_GROUP.tools]
    delta_names = [tool.name for tool in DELTA_TOOL_GROUP.tools]
    assert spec.tool_group_keys == ("context", "ranking", "probability")
    assert tool_names == context_names + ranking_names + probability_names
    assert list(registry.reachable_tool_names[spec.name]) == (
        context_names
        + ranking_names
        + probability_names
        + cohort_names
        + delta_names
    ) + ["present_evidence"]


def test_final_responder_owns_evidence_presentation() -> None:
    """Keep numerical presentation grounded in evidence references."""
    registry = current_registry()
    spec = registry.get_spec("final_responder")

    assert spec.repository_context is True
    assert "Markdown table" in spec.system_prompt
    assert spec.skill_names == ("tft-statistical-interpretation",)
    assert spec.tool_group_keys == ("evidence", "context")
    assert list(registry.tool_names[spec.name]) == ["present_evidence", "read_resource"]
    assert list(registry.handoff_names[spec.name]) == []
    assert list(registry.reachable_tool_names[spec.name]) == ["present_evidence", "read_resource"]


def test_chat_hands_off_to_data_analyst() -> None:
    assert list(current_registry().handoff_names["chat"]) == ["data_analyst", "final_responder"]

    agents = Assistant("chat").agent.handoffs
    assert [agent.name for agent in agents] == ["data_analyst", "final_responder"]


def test_chat_handoff_preserves_request_model_provider() -> None:
    request_model = LitellmModel(model="anthropic/test-model", api_key="test-key")

    analyst = Assistant("chat", model=request_model).agent.handoffs[0]

    assert analyst.model is request_model
    assert [handoff.name for handoff in analyst.handoffs] == ["final_responder"]
    assert analyst.handoffs[0].model is request_model
    assert [tool.name for tool in analyst.tools] == list(current_registry().tool_names["data_analyst"])
    assert Assistant("data_analyst").agent.model == load_config().models.openai_model


def test_specialists_hand_off_to_data_analyst() -> None:
    assert list(current_registry().handoff_names["meta_expert"]) == ["data_analyst"]
    assert list(current_registry().handoff_names["theorizer"]) == ["data_analyst"]
    # The analyst gathers evidence, then transfers to the terminal synthesizer.
    assert list(current_registry().handoff_names["data_analyst"]) == ["final_responder"]


def test_distillation_replaces_all_legacy_transcript_assistants() -> None:
    """Discovery exposes one source-only transcript assistant without legacy aliases."""
    names = set(list(current_registry().assistant_names))
    assert "distill-transcript" in names
    assert names.isdisjoint({"clean_transcript", "compact_transcript", "analyze_transcript"})
    registry = current_registry()
    spec = registry.get_spec("distill-transcript")
    assert spec.skill_names == ()
    assert list(registry.tool_names[spec.name]) == []
    assert list(registry.handoff_names[spec.name]) == []
