"""Regression coverage for medal-based database-tool filtering and grouping."""

import pytest
from sqlalchemy import literal, select

from conftest import _call_tool
from db.models import AnalysisBoardTrait
from domain.tools.db_tools import cohort_tools, deltas, ranking_tools, utils


@pytest.mark.parametrize("style,label", [
    (None, "Inactive"),
    (0, "Inactive"),
    (1, "Bronze"),
    (2, "Silver"),
    (3, "Unique"),
    (4, "Gold"),
    (5, "Prismatic"),
    (99, "Unknown"),
])
def test_trait_medal_style_mapping(dev_session, style, label) -> None:
    """Map activation styles without treating breakpoint indices as medals."""
    assert dev_session.scalar(select(utils.trait_tier_expression(literal(style)))) == label


def test_medal_groups_merge_breakpoints_and_align_deltas(monkeypatch, seeded_session) -> None:
    """Use the same medal grain for rankings, cohort groups, and deltas."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    monkeypatch.setattr(deltas, "MIN_PUBLIC_BOARDS", 1)
    monkeypatch.setattr(cohort_tools, "MIN_PUBLIC_BOARDS", 1)
    traits = seeded_session.scalars(
        select(AnalysisBoardTrait).where(
            AnalysisBoardTrait.trait_name == "TFT17_DarkStar"
        )
    ).all()
    for index, trait in enumerate(traits):
        trait.style = 2
        trait.tier_current = 2 + index % 2
    seeded_session.flush()
    ranking = _call_tool(monkeypatch, seeded_session, ranking_tools.rank_traits, tier="Silver")
    assert len(ranking["results"]) == 1
    row = ranking["results"][0]
    assert (row["tier"], row["games"], row["delta"]) == ("Silver", 4, -4.0)
    delta = _call_tool(
        monkeypatch, seeded_session, deltas.get_cohort_trait_deltas,
        cohort={"trait_conditions": [{"name": "TFT17_Sniper"}]},
    )
    delta_row = next(row for row in delta["results"] if row["trait_name"] == "TFT17_DarkStar")
    assert (delta_row["tier"], delta_row["games"], delta_row["delta"]) == ("Silver", 4, -4.0)
    grouped = _call_tool(
        monkeypatch, seeded_session, cohort_tools.query_cohort,
        cohort={"trait_conditions": [{"name": "TFT17_DarkStar", "tier": "Silver"}]},
        group_by=["trait_name", "trait_tier"],
    )
    assert any(row["trait_tier"] == "Silver" for row in grouped["results"])


def test_default_trait_rollup_uses_all_label(monkeypatch, seeded_session) -> None:
    """Keep rollup behavior while replacing its internal numeric sentinel."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    result = _call_tool(monkeypatch, seeded_session, ranking_tools.rank_traits)
    assert result["results"]
    assert all(row["tier"] == "All" for row in result["results"])


def test_named_trait_tiers_are_advertised_in_tool_schema() -> None:
    """Expose a bounded medal enumeration to assistants and the Tools form."""
    tier = ranking_tools.rank_traits.params_json_schema["properties"]["tier"]
    assert tier["anyOf"][0]["enum"] == [
        "Bronze", "Silver", "Unique", "Gold", "Prismatic",
    ]
