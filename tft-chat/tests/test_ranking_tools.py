from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from db.models import (
    ALL_STARS,
)
from domain.tools import list_tool_names
from domain.tools.db_tools import ranking_tools, utils
from domain.tools.db_tools.models import (
    AnalysisErrorResult,
    AnalysisResolutionResult,
    AnalysisTableResult,
)
from domain.tools.db_tools.ranking_tools import RANKING_TOOL_GROUP, ResultRange
from conftest import _call_tool


def test_analysis_table_result_emits_decimal_metrics_as_json_numbers() -> None:
    """Convert database-native aggregates before validating open result rows."""
    result = utils.analysis_table_result(
        {
            "results": [
                {
                    "unit_name": "Jinx",
                    "games": Decimal("31"),
                    "avg_placement": Decimal("3.42"),
                    "top4_rate": Decimal("0.625"),
                    "delta": None,
                }
            ],
            "offset": 0,
            "has_more": False,
        },
        population="artifact holders",
        population_boards=31,
        group_by=["unit_name"],
        sort_by="games",
        sort_direction="desc",
    )

    row = result["results"][0]
    assert isinstance(row["games"], float)
    assert row == {
        "unit_name": "Jinx",
        "games": 31.0,
        "avg_placement": 3.42,
        "top4_rate": 0.625,
        "delta": None,
    }


def test_ranking_tool_group_registers_only_rankings() -> None:
    """Expose each ranking tool once and no removed lookup tools."""
    assert RANKING_TOOL_GROUP.key == "ranking"
    assert [tool.name for tool in RANKING_TOOL_GROUP.tools] == [
        "resolve_tft_names",
        "rank_units",
        "rank_items",
        "rank_traits",
        "rank_unit_loadouts",
    ]
    assert not hasattr(ranking_tools, "rank_unit_groups")
    registered = list_tool_names()
    assert not any(name.startswith("get_") and name.endswith("_stats") for name in registered)
    for tool in RANKING_TOOL_GROUP.tools:
        assert registered.count(tool.name) == 1


def test_ranking_schemas_are_bounded_without_partial_name_fields() -> None:
    """Keep entity strings and lists bounded without exposing fuzzy filters."""
    unit_schema = ranking_tools.rank_units.params_json_schema["properties"]
    assert unit_schema["star_level"]["anyOf"][0]["minimum"] == 0
    assert unit_schema["star_level"]["anyOf"][0]["maximum"] == 4
    assert unit_schema["range"]["default"] == [0, 10]
    assert unit_schema["range"]["minItems"] == 2
    assert unit_schema["range"]["maxItems"] == 2
    assert unit_schema["range"]["items"]["maximum"] == 10_000
    assert unit_schema["min_sample"]["anyOf"][0]["minimum"] == 1
    assert unit_schema["max_sample"]["anyOf"][0]["minimum"] == 1
    for removed in ("offset", "limit", "facet_by", "order_by", "metrics"):
        assert removed not in unit_schema

    for tool in RANKING_TOOL_GROUP.tools[1:]:
        properties = tool.params_json_schema["properties"]
        assert properties["range"]["default"] == [0, 10]
        for removed in ("offset", "limit", "facet_by", "order_by", "metrics"):
            assert removed not in properties
        assert {"min_sample", "max_sample"}.issubset(properties)
        assert "name" not in properties
        assert "name_filter" not in properties
        assert not any(field.endswith("_filter") for field in properties)

    item_schema = ranking_tools.rank_items.params_json_schema
    item_type_ref = item_schema["properties"]["item_type"]["anyOf"][0]["$ref"]
    item_type_definition = item_schema["$defs"][item_type_ref.rsplit("/", 1)[-1]]
    assert "artifact" in item_type_definition["enum"]

    schemas = {
        tool.name: tool.params_json_schema["properties"]
        for tool in RANKING_TOOL_GROUP.tools
    }
    for properties in schemas.values():
        assert "within" not in properties
    for tool_name, fields in {
        "rank_units": ("item", "trait"),
        "rank_items": ("holder",),
        "rank_traits": ("unit",),
        "rank_unit_loadouts": ("item_1", "item_2", "trait"),
    }.items():
        for field in fields:
            assert schemas[tool_name][field]["anyOf"][0]["type"] == "string"
    assert "items" not in schemas["rank_unit_loadouts"]


def test_rank_units_uses_default_rollup_and_sample_bounds(
    monkeypatch, seeded_session
) -> None:
    """Rank unit rollups while applying direct sample-size bounds."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    included = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_units,
        min_sample=8,
        max_sample=8,
    )
    excluded = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_units,
        min_sample=9,
    )

    assert AnalysisTableResult.model_validate(included)
    assert included["page"]["count"] == 1
    assert included["results"][0]["unit_name"] == "TFT17_Jinx"
    assert included["results"][0]["star_level"] == ALL_STARS
    assert excluded["page"]["count"] == 0


def test_rank_items_uses_exact_holder_and_rank_traits_selects_tier(
    monkeypatch, seeded_session
) -> None:
    """Apply exact ranking filters to item holders and trait breakpoints."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    items = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_items,
        holder="TFT17_Jinx",
    )
    traits = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_traits,
        tier="Bronze",
    )

    assert items["page"]["count"] == 1
    assert items["results"][0]["unit_name"] == "TFT17_Jinx"
    assert items["results"][0]["delta"] == -4.0
    assert items["results"][0]["relative_delta"] is None
    dark_star = next(row for row in traits["results"] if row["trait_name"] == "TFT17_DarkStar")
    assert dark_star["tier"] == "Bronze"
    assert dark_star["delta"] == -4.0
    assert dark_star["relative_delta"] is None


def test_rank_unit_loadouts_filters_by_scalar_item(monkeypatch, seeded_session) -> None:
    """Filter canonical loadouts with one scalar exact-name item condition."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    result = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_unit_loadouts,
        unit="TFT17_Jinx",
        item_1="TFT_Item_GuinsoosRageblade",
    )

    assert result["page"]["count"] == 1
    assert result["results"][0]["unit_name"] == "TFT17_Jinx"
    assert result["results"][0]["item_1"] == "TFT_Item_GuinsoosRageblade"
    assert result["results"][0]["delta"] == -4.0
    assert result["results"][0]["relative_delta"] is None


def test_rank_items_filters_by_item_type(monkeypatch, seeded_session) -> None:
    """Restrict item rankings to the requested canonical item family."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    artifacts = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_items,
        item_type="artifact",
    )
    craftables = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_items,
        item_type="craftable",
    )

    assert artifacts["page"]["count"] == 1
    assert artifacts["results"][0]["item_name"] == "TFT_Item_GuinsoosRageblade"
    assert craftables["page"]["count"] == 0


def test_ranking_preserves_sorting_range_slicing_and_sample_suppression(
    monkeypatch, seeded_session
) -> None:
    """Preserve ordered slices and the public minimum-sample floor."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    page = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_traits,
        group_by_tier=True,
        sort_by="avg_placement",
        range=[0, 1],
    )
    assert page["page"] == {"offset": 0, "count": 1, "has_more": True}

    truncated = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_traits,
        group_by_tier=True,
        sort_by="avg_placement",
        range=[1, 10],
    )
    assert truncated["page"] == {"offset": 1, "count": 2, "has_more": False}

    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 9)
    suppressed = _call_tool(
        monkeypatch, seeded_session, ranking_tools.rank_units
    )
    assert suppressed["page"] == {"offset": 0, "count": 0, "has_more": False}
    assert any(warning["code"] == "no_results" for warning in suppressed["warnings"])


def test_resolve_tft_names_uses_resolution_contract(
    monkeypatch, seeded_session
) -> None:
    """Resolve all entity kinds without the removed SQL module or legacy key."""
    result = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.resolve_tft_names,
        names=["rageblade", "dark star", "jnix", "nosuchthing"],
    )

    assert AnalysisResolutionResult.model_validate(result)
    assert result["kind"] == "resolution"
    assert "resolutions" not in result
    assert "version" not in result
    by_query = {entry["query"]: entry for entry in result["results"]}
    assert by_query["rageblade"]["matches"][0]["kind"] == "item"
    assert by_query["dark star"]["matches"][0]["kind"] == "trait"
    assert by_query["jnix"]["matches"][0]["name"] == "TFT17_Jinx"
    assert by_query["nosuchthing"]["resolved"] is False


def test_result_range_rejects_reversed_and_overwide_slices() -> None:
    """Reject invalid slices before a ranking reaches the database."""
    adapter = TypeAdapter(ResultRange)

    with pytest.raises(ValidationError, match="range end"):
        adapter.validate_python([10, 5])
    with pytest.raises(ValidationError, match="at most 100 rows"):
        adapter.validate_python([0, 101])


def test_rank_units_rejects_inverted_sample_bounds(
    monkeypatch, seeded_session
) -> None:
    """Reject direct sample bounds whose minimum exceeds the maximum."""
    result = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_units,
        min_sample=10,
        max_sample=5,
    )

    assert AnalysisErrorResult.model_validate(result)
    assert result["error"]["code"] == "invalid_arguments"
    assert result["error"]["retryable"] is False
