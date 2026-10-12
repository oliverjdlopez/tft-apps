from __future__ import annotations
import json
from pathlib import Path

import pytest

from agents import Agent
from agents.extensions.models.litellm_model import LitellmModel

from core.config import load_config
from domain.assistants import (
    assistant_handoff_names,
    assistant_reachable_tool_names,
    assistant_spec,
    assistant_tool_names,
    Assistant,
    list_assistants,
)
from domain.assistants.registry import assistant_registry
from domain.assistants.specs import AssistantSpec, load_assistant_spec
from domain.assistants import token_logging
from domain.assistants.utils import render_instruction_layers, wrap_task_input
from domain.providers.context import (
    DEFAULT_CONTEXT_PROVIDER,
    ContextProvider,
    ContextSnippet,
)
from domain.providers.skills import (
    DEFAULT_SKILL_PROVIDER,
    SkillDefinition,
    SkillProvider,
)
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
    spec = assistant_spec("chat")

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


def test_instruction_rendering_enforces_skill_allowlist(monkeypatch) -> None:
    """Instruction assembly drops preselected skills not granted by the spec."""
    spec = AssistantSpec(
        name="limited",
        description="Limited",
        handoff_description="Limited",
        system_prompt="BASE",
        task_prompt="",
        path="limited/system.md",
        skill_names=("allowed",),
    )
    monkeypatch.setattr(
        "domain.assistants.assistant_registry.get_spec", lambda _name: spec
    )

    rendered = render_instruction_layers(
        spec,
        context_provider=DEFAULT_CONTEXT_PROVIDER,
        skill_provider=DEFAULT_SKILL_PROVIDER,
        skills=[
            SkillDefinition(
                name="allowed",
                description="Allowed",
                body="ALLOWED BODY",
                path="allowed/SKILL.md",
            ),
            SkillDefinition(
                name="denied",
                description="Denied",
                body="DENIED BODY",
                path="denied/SKILL.md",
            ),
        ],
    )

    assert "ALLOWED BODY" in rendered
    assert "DENIED BODY" not in rendered


def test_assistant_specs_declare_prompt_context_policy() -> None:
    assert assistant_spec("chat").repository_context is True
    assert assistant_spec("data_analyst").repository_context is True
    for name in (
        "comp_expert",
        "item_expert",
        "meta_expert",
        "theorizer",
        "unit_expert",
    ):
        assert assistant_spec(name).repository_context is True
    assert assistant_spec("distill-transcript").repository_context is False


def test_factory_builds_sdk_agent_with_spec_model_settings() -> None:
    agent = Assistant("chat").build_agent()

    assert isinstance(agent, Agent)
    assert agent.model == load_config().models.openai_model
    assert agent.model_settings.reasoning.effort == ReasoningEfforts.MEDIUM.value
    assert callable(agent.instructions)


def test_task_input_uses_spec_task_prompt(monkeypatch) -> None:
    spec = AssistantSpec(
        name="context_test",
        description="Context test",
        handoff_description="Context test",
        system_prompt="BASE INSTRUCTIONS",
        task_prompt="Complete this task.",
        path="test.md",
    )
    monkeypatch.setattr(
        "domain.assistants.assistant_registry.get_spec",
        lambda _name: spec,
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


def test_instruction_token_log_records_counts_without_prompt_contents(monkeypatch) -> None:
    """Token diagnostics include section counts but exclude source text."""
    records: list[str] = []
    monkeypatch.setattr(token_logging.prompt_token_logger, "info", records.append)

    token_logging.log_instruction_parts(
        assistant_name="test_agent",
        model="gpt-5.5",
        base_instructions="PRIVATE BASE INSTRUCTIONS",
        task_prompt="PRIVATE TASK PROMPT",
        repository_context="PRIVATE CONTEXT",
        skills="PRIVATE SKILL",
        assembled_instructions="PRIVATE ASSEMBLED INSTRUCTIONS",
        context_names=["units"],
        skill_names=["comparison"],
    )

    payload = json.loads(records[0])
    assert payload["event"] == "instruction_parts"
    assert payload["tokens"]["base_instructions"] > 0
    assert payload["context_sources"] == ["units"]
    assert payload["skills"] == ["comparison"]
    assert "PRIVATE" not in records[0]


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


def test_instructions_render_references_and_skill_in_order(monkeypatch) -> None:
    class FakeContextProvider:
        def select(self, query, *, set_number=None, **_limits):
            return [
                ContextSnippet(
                    context_file="units",
                    path="units.md",
                    content="RIVEN REFERENCE",
                    line=1,
                    score=100,
                )
            ]

        def render(self, references):
            assert references[0].content == "RIVEN REFERENCE"
            return "CONTEXT: RIVEN REFERENCE"

    class FakeSkillProvider:
        def render(self, skills):
            assert skills[0].name == "comparison"
            return "SKILL: SKILL WORKFLOW"

    rendered = render_instruction_layers(
        assistant_spec("comp_expert"),
        references=FakeContextProvider().select("Analyze Riven"),
        context_provider=FakeContextProvider(),
        skill_provider=FakeSkillProvider(),
        base_instructions="BASE INSTRUCTIONS",
        skills=[
            SkillDefinition(
                name="comparison",
                description="Compare cohorts.",
                body="SKILL WORKFLOW",
                path="comparison/SKILL.md",
            )
        ],
    )

    assert rendered.index("BASE INSTRUCTIONS") < rendered.index("RIVEN REFERENCE")
    assert rendered.index("RIVEN REFERENCE") < rendered.index("SKILL WORKFLOW")


def test_transcript_rendering_denies_preselected_references() -> None:
    """Transcript instructions reject references even if another caller selected them."""
    reference = ContextSnippet(context_file='units', path='units.md', content='PRIVATE REFERENCE', line=1, score=1)
    text = render_instruction_layers(assistant_spec('distill-transcript'),
        context_provider=DEFAULT_CONTEXT_PROVIDER, skill_provider=DEFAULT_SKILL_PROVIDER,
        references=[reference])
    assert 'PRIVATE REFERENCE' not in text


def test_data_analyst_owns_focused_ranking_cohort_and_context_tools() -> None:
    spec = assistant_spec("data_analyst")
    ranking_names = [tool.name for tool in RANKING_TOOL_GROUP.tools]
    cohort_names = [tool.name for tool in COHORT_TOOL_GROUP.tools]
    delta_names = [tool.name for tool in DELTA_TOOL_GROUP.tools]
    context_names = [tool.name for tool in CONTEXT_TOOL_GROUP.tools]

    assert "data_analyst" in list_assistants()
    assert spec.tool_group_keys == ("ranking", "query_cohorts", "deltas", "context")
    assert assistant_tool_names("data_analyst") == (
        ranking_names + cohort_names + delta_names + context_names
    )
    assert assistant_handoff_names("data_analyst") == ["final_responder"]
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
        prompt = assistant_spec(name).system_prompt
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

    prompt = assistant_spec(name).system_prompt
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
    chat = assistant_spec("chat").system_prompt
    analyst = assistant_spec("data_analyst").system_prompt
    responder = assistant_spec("final_responder").system_prompt
    assert "## Evidence displays" not in chat
    assert "no direct match-data tools" not in chat
    assert "A direct lookup or ranking is sufficient when its result answers the actual question" in chat
    assert "Preserve these" not in analyst
    assert "`compare_cohorts`; a mean does not establish a distribution" in analyst
    assert "hand off to `final_responder`" in analyst
    assert "Use `present_evidence` once" in responder


def test_chat_has_direct_context_ranking_and_probability_tools() -> None:
    spec = assistant_spec("chat")
    tool_names = assistant_tool_names("chat")

    context_names = [tool.name for tool in CONTEXT_TOOL_GROUP.tools]
    ranking_names = [tool.name for tool in RANKING_TOOL_GROUP.tools]
    probability_names = [tool.name for tool in PROBABILITY_TOOL_GROUP.tools]
    cohort_names = [tool.name for tool in COHORT_TOOL_GROUP.tools]
    delta_names = [tool.name for tool in DELTA_TOOL_GROUP.tools]
    assert spec.tool_group_keys == ("context", "ranking", "probability")
    assert tool_names == context_names + ranking_names + probability_names
    assert assistant_reachable_tool_names("chat") == (
        context_names
        + ranking_names
        + probability_names
        + cohort_names
        + delta_names
    ) + ["present_evidence"]


def test_final_responder_owns_evidence_presentation() -> None:
    """Keep numerical presentation grounded in evidence references."""
    spec = assistant_spec("final_responder")

    assert spec.repository_context is True
    assert "Markdown table" in spec.system_prompt
    assert spec.skill_names == ("tft-statistical-interpretation",)
    assert spec.tool_group_keys == ("evidence",)
    assert assistant_tool_names("final_responder") == ["present_evidence"]
    assert assistant_handoff_names("final_responder") == []
    assert assistant_reachable_tool_names("final_responder") == ["present_evidence"]


def test_chat_hands_off_to_data_analyst() -> None:
    assert assistant_handoff_names("chat") == ["data_analyst", "final_responder"]

    agents = Assistant("chat").build_agent().handoffs
    assert [agent.name for agent in agents] == ["data_analyst", "final_responder"]


def test_chat_handoff_preserves_request_model_provider() -> None:
    request_model = LitellmModel(model="anthropic/test-model", api_key="test-key")

    analyst = Assistant("chat", model=request_model).build_agent().handoffs[0]

    assert analyst.model is request_model
    assert [handoff.name for handoff in analyst.handoffs] == ["final_responder"]
    assert analyst.handoffs[0].model is request_model
    assert [tool.name for tool in analyst.tools] == assistant_tool_names("data_analyst")
    assert Assistant("data_analyst").build_agent().model == load_config().models.openai_model


def test_specialists_hand_off_to_data_analyst() -> None:
    assert assistant_handoff_names("meta_expert") == ["data_analyst"]
    assert assistant_handoff_names("theorizer") == ["data_analyst"]
    # The analyst gathers evidence, then transfers to the terminal synthesizer.
    assert assistant_handoff_names("data_analyst") == ["final_responder"]


def test_distillation_replaces_all_legacy_transcript_assistants() -> None:
    """Discovery exposes one source-only transcript assistant without legacy aliases."""
    names = set(list_assistants())
    assert "distill-transcript" in names
    assert names.isdisjoint({"clean_transcript", "compact_transcript", "analyze_transcript"})
    spec = assistant_spec("distill-transcript")
    assert spec.skill_names == ()
    assert assistant_tool_names(spec.name) == []
    assert assistant_handoff_names(spec.name) == []
