from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from agents import function_tool

from domain import tools as tool_registry
from db.session import run_db
from domain.tools import (
    call_tool,
    get_tool,
    get_tool_group,
    list_tool_group_metadata,
    list_tool_groups,
    list_tool_metadata,
    list_tools,
)
from domain.tools.db_tools.cohort_tools import COHORT_TOOL_GROUP
from domain.tools.db_tools.deltas import DELTA_TOOL_GROUP
from domain.tools.db_tools.ranking_tools import RANKING_TOOL_GROUP
from domain.tools.context import request_additional_context
from services.display_service import tool_catalog


async def _sample_tool(count: int, label: str | None = None) -> dict[str, object]:
    """Sample native tool used by registry tests."""
    return {"count": count, "label": label}


sample_tool = function_tool(_sample_tool, strict_mode=False, failure_error_function=None)


def test_sync_database_work_runs_off_the_event_loop_thread() -> None:
    caller_thread = threading.get_ident()

    worker_thread = asyncio.run(run_db(threading.get_ident))

    assert worker_thread != caller_thread


def test_native_tool_registry_describes_and_invokes_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_registry, "_TOOL_FUNCTIONS", {"sample_tool": sample_tool})

    tools = {tool["name"]: tool for tool in list_tool_metadata()}

    assert tools["sample_tool"]["description"] == "Sample native tool used by registry tests."
    assert tools["sample_tool"]["input_schema"]["properties"]["count"]["type"] == "integer"
    assert "count" in tools["sample_tool"]["input_schema"]["required"]

    result = asyncio.run(call_tool("sample_tool", {"count": 3}))

    assert result == {"count": 3, "label": None}


def test_registered_sdk_tool_rounds_nested_model_visible_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def numeric_tool() -> dict[str, object]:
        """Return numeric values for model-output normalization testing."""
        return {"rate": 0.98765, "nested": [{"delta": -1.2345}]}

    native_tool = function_tool(numeric_tool, strict_mode=True)
    monkeypatch.setattr(
        tool_registry,
        "_TOOL_FUNCTIONS",
        {"numeric_tool": tool_registry._ensure_sdk_tool(native_tool)},
    )

    result = asyncio.run(call_tool("numeric_tool"))

    assert result == {"rate": 0.99, "nested": [{"delta": -1.23}]}


def test_get_tool_rejects_unknown_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_registry, "_TOOL_FUNCTIONS", {})

    with pytest.raises(KeyError, match="Unknown TFT tool"):
        get_tool("does_not_exist")


def test_tool_groups_cover_each_tool_once() -> None:
    grouped_names = [tool.name for group in list_tool_groups() for tool in group.tools]
    flat_names = [tool.name for tool in list_tools()]

    assert sorted(grouped_names) == flat_names
    assert len(grouped_names) == len(set(grouped_names))
    assert [tool.name for tool in COHORT_TOOL_GROUP.tools] == [
        "query_cohort",
        "compare_cohorts",
    ]
    assert [tool.name for tool in DELTA_TOOL_GROUP.tools] == [
        "get_cohort_unit_deltas",
        "get_cohort_item_deltas",
        "get_cohort_trait_deltas",
    ]


def test_tool_group_lists_and_gets_tools_by_name() -> None:
    group = get_tool_group("ranking")
    tools = group.list_tools()

    assert tools == group.tools
    assert group.get_tool(tools[0].name) is tools[0]


def test_tool_group_rejects_unknown_tool() -> None:
    group = get_tool_group("ranking")

    with pytest.raises(KeyError, match=f"Unknown tool in group {group.key!r}"):
        group.get_tool("does_not_exist")


def test_list_tool_group_metadata_returns_tool_metadata() -> None:
    groups = list_tool_group_metadata()

    assert [group["key"] for group in groups] == [
        "query_cohorts",
        "deltas",
        "ranking",
        "probability",
        "context",
        "evidence",
    ]
    assert all(group["description"] for group in groups)
    assert all(tool["input_schema"] for group in groups for tool in group["tools"])


def test_explorer_tool_catalog_uses_backend_invocation_requirements() -> None:
    """Explorer forms should not treat backend defaults as required inputs."""
    tools = {tool["name"]: tool for tool in tool_catalog()["tools"]}

    rank_units = tools["rank_units"]
    assert "star_level" in rank_units["input_schema"]["required"]
    assert "star_level" not in rank_units["invocation_schema"].get("required", [])
    assert "sort_by" not in rank_units["invocation_schema"].get("required", [])

    compare_cohorts = tools["compare_cohorts"]
    assert compare_cohorts["invocation_schema"]["required"] == ["target"]
    target = compare_cohorts["invocation_schema"]["properties"]["target"]
    assert "required" not in target
    assert compare_cohorts["invocation_schema"]["$defs"]["UnitCondition"][
        "required"
    ] == ["name"]


def test_model_facing_tools_use_strict_bounded_schemas() -> None:
    tools = {tool.name: tool for tool in list_tools()}

    assert all(tool.strict_json_schema for tool in tools.values())
    native_tools = [
        tools[tool.name]
        for group in (RANKING_TOOL_GROUP, COHORT_TOOL_GROUP, DELTA_TOOL_GROUP)
        for tool in group.tools
    ]
    assert all(tool.timeout_seconds == 30.0 for tool in native_tools)
    assert tools["resolve_tft_names"].params_json_schema["properties"]["names"][
        "maxItems"
    ] == 24
    assert "run_sql" not in tools


def test_request_additional_context_reports_complete_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from domain.tools import context as context_tools

    class FakeContextProvider:
        async def aselect(self, query: str, *, set_number: int | None):
            assert (query, set_number) == ("Anima Tech rewards", 17)
            return [
                SimpleNamespace(
                    context_file="anima-mechanic",
                    path="mechanics/anima.md",
                    heading="Anima",
                    content="- 3 Anima: gain Tech",
                )
            ]

        def render(self, snippets: list[object]) -> str:
            assert len(snippets) == 1
            return "## Selected context excerpts for this task\n\n- 3 Anima: gain Tech"

    monkeypatch.setattr(context_tools, "_context_provider", lambda: FakeContextProvider())
    monkeypatch.setattr(
        context_tools,
        "load_config",
        lambda: SimpleNamespace(chat=SimpleNamespace(set_number=17)),
    )

    result = asyncio.run(
        call_tool("request_additional_context", {"request": {"query": "Anima Tech rewards"}})
    )

    assert result == {
        "query": "Anima Tech rewards",
        "sources": [
            {
                "name": "anima-mechanic",
                "path": "mechanics/anima.md",
                "heading": "Anima",
            }
        ],
        "context": "## Selected context excerpts for this task\n\n- 3 Anima: gain Tech",
        "found": True,
        "complete_selected_collections": True,
        "collection_count": 1,
    }
