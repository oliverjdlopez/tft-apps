from __future__ import annotations
import json
from pathlib import Path

import pytest

from agents import Agent
from agents.extensions.models.litellm_model import LitellmModel

from core.config import load_config
from domain.assistants import Assistant
from domain.assistants.registry import assistant_registry
from domain.assistants.specs import AssistantSpec, load_assistant_spec
from domain.assistants import token_logging
from domain.assistants.utils import render_instruction_layers, wrap_task_input
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


def test_loaded_assistant_specs_include_model_and_reasoning() -> None:
    spec = Assistant("chat").spec

    assert spec.model is None
    assert spec.resolved_model() == load_config().models.openai_model
    assert spec.reasoning == ReasoningEfforts.MEDIUM


def test_skill_allowlist_defaults_to_all_and_loads_named_entries(tmp_path: Path) -> None:
    """Omitted skills stay unrestricted while a JSON list becomes an allowlist."""
    unrestricted_dir = tmp_path / "unrestricted"
    unrestricted_dir.mkdir()
    (unrestricted_dir / "system.md").write_text("# Unrestricted\n", encoding="utf-8")
    restricted_dir = tmp_path / "restricted"
    restricted_dir.mkdir()
    (restricted_dir / "system.md").write_text("# Restricted\n", encoding="utf-8")
    (restricted_dir / "agent.json").write_text(
        json.dumps({"skills": ["comparison"]}), encoding="utf-8"
    )

    assert load_assistant_spec(unrestricted_dir, root_dir=tmp_path).skill_names is None
    assert load_assistant_spec(restricted_dir, root_dir=tmp_path).skill_names == (
        "comparison",
    )




def test_assistant_specs_declare_prompt_context_policy() -> None:
    assert Assistant("chat").spec.repository_context is True
    assert Assistant("data_analyst").spec.repository_context is True
    for name in (
        "comp_expert",
        "item_expert",
        "meta_expert",
        "theorizer",
        "unit_expert",
    ):
        assert Assistant(name).spec.repository_context is True
    assert Assistant("distill-transcript").spec.repository_context is False


def test_factory_builds_sdk_agent_with_spec_model_settings() -> None:
    agent = Assistant("chat").build_agent()

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
    first = Assistant("chat").build_agent()
    second = Assistant("chat").build_agent()
    first_handoffs = {agent.name: agent for agent in first.handoffs}
    second_handoffs = {agent.name: agent for agent in second.handoffs}

    assert first is not second
    assert first_handoffs.keys() == second_handoffs.keys()
    assert all(first_handoffs[name] is not second_handoffs[name] for name in first_handoffs)


def test_durable_overrides_retain_dynamic_callbacks() -> None:
    """Replacing prompts preserves runtime instruction policy on every agent."""
    agent = Assistant('chat', base_instructions_by_name={
        'chat': 'ROOT INSTRUCTIONS', 'data_analyst': 'ANALYST INSTRUCTIONS',
    }).build_agent()
    from agents import RunContextWrapper
    assert callable(agent.instructions)
    assert agent.instructions(RunContextWrapper(None), agent) == 'ROOT INSTRUCTIONS'
    analyst = next(child for child in agent.handoffs if child.name == 'data_analyst')
    assert analyst.instructions(RunContextWrapper(None), analyst) == 'ANALYST INSTRUCTIONS'


def test_agent_graph_token_log_includes_tool_definitions(monkeypatch) -> None:
    """Agent graph diagnostics include tool and handoff token totals."""
    records: list[str] = []
    monkeypatch.setattr(token_logging.prompt_token_logger, "info", records.append)

    Assistant("chat").build_agent()

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
    assistant = Assistant("data_analyst")
    spec = assistant.spec
    ranking_names = [tool.name for tool in RANKING_TOOL_GROUP.tools]
    cohort_names = [tool.name for tool in COHORT_TOOL_GROUP.tools]
    delta_names = [tool.name for tool in DELTA_TOOL_GROUP.tools]
    context_names = [tool.name for tool in CONTEXT_TOOL_GROUP.tools]

    assert "data_analyst" in Assistant.names()
    assert spec.tool_group_keys == ("ranking", "query_cohorts", "deltas", "context")
    assert assistant.tool_names == (
        ranking_names + cohort_names + delta_names + context_names
    )
    assert assistant.handoff_names == ["final_responder"]
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
        prompt = Assistant(name).spec.system_prompt
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

    prompt = Assistant(name).spec.system_prompt
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
    chat = Assistant("chat").spec.system_prompt
    analyst = Assistant("data_analyst").spec.system_prompt
    responder = Assistant("final_responder").spec.system_prompt
    assert "## Evidence displays" not in chat
    assert "no direct match-data tools" not in chat
    assert "A direct lookup or ranking is sufficient when its result answers the actual question" in chat
    assert "Preserve these" not in analyst
    assert "`compare_cohorts`; a mean does not establish a distribution" in analyst
    assert "hand off to `final_responder`" in analyst
    assert "Use `present_evidence` once" in responder


def test_chat_has_direct_context_ranking_and_probability_tools() -> None:
    assistant = Assistant("chat")
    spec = assistant.spec
    tool_names = assistant.tool_names

    context_names = [tool.name for tool in CONTEXT_TOOL_GROUP.tools]
    ranking_names = [tool.name for tool in RANKING_TOOL_GROUP.tools]
    probability_names = [tool.name for tool in PROBABILITY_TOOL_GROUP.tools]
    cohort_names = [tool.name for tool in COHORT_TOOL_GROUP.tools]
    delta_names = [tool.name for tool in DELTA_TOOL_GROUP.tools]
    assert spec.tool_group_keys == ("context", "ranking", "probability")
    assert tool_names == context_names + ranking_names + probability_names
    assert assistant.reachable_tool_names == (
        context_names
        + ranking_names
        + probability_names
        + cohort_names
        + delta_names
    ) + ["present_evidence"]


def test_final_responder_owns_evidence_presentation() -> None:
    """Keep numerical presentation grounded in evidence references."""
    assistant = Assistant("final_responder")
    spec = assistant.spec

    assert spec.repository_context is True
    assert "Markdown table" in spec.system_prompt
    assert spec.skill_names == ("tft-statistical-interpretation",)
    assert spec.tool_group_keys == ("evidence", "context")
    assert assistant.tool_names == ["present_evidence", "read_resource"]
    assert assistant.handoff_names == []
    assert assistant.reachable_tool_names == ["present_evidence", "read_resource"]


def test_chat_hands_off_to_data_analyst() -> None:
    assert Assistant("chat").handoff_names == ["data_analyst", "final_responder"]

    agents = Assistant("chat").build_agent().handoffs
    assert [agent.name for agent in agents] == ["data_analyst", "final_responder"]


def test_chat_handoff_preserves_request_model_provider() -> None:
    request_model = LitellmModel(model="anthropic/test-model", api_key="test-key")

    analyst = Assistant("chat", model=request_model).build_agent().handoffs[0]

    assert analyst.model is request_model
    assert [handoff.name for handoff in analyst.handoffs] == ["final_responder"]
    assert analyst.handoffs[0].model is request_model
    assert [tool.name for tool in analyst.tools] == Assistant("data_analyst").tool_names
    assert Assistant("data_analyst").build_agent().model == load_config().models.openai_model


def test_specialists_hand_off_to_data_analyst() -> None:
    assert Assistant("meta_expert").handoff_names == ["data_analyst"]
    assert Assistant("theorizer").handoff_names == ["data_analyst"]
    # The analyst gathers evidence, then transfers to the terminal synthesizer.
    assert Assistant("data_analyst").handoff_names == ["final_responder"]


def test_distillation_replaces_all_legacy_transcript_assistants() -> None:
    """Discovery exposes one source-only transcript assistant without legacy aliases."""
    names = set(Assistant.names())
    assert "distill-transcript" in names
    assert names.isdisjoint({"clean_transcript", "compact_transcript", "analyze_transcript"})
    assistant = Assistant("distill-transcript")
    spec = assistant.spec
    assert spec.skill_names == ()
    assert assistant.tool_names == []
    assert assistant.handoff_names == []
