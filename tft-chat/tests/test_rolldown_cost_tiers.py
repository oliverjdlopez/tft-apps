"""Verify generic cost-tier targets through the real roster and simulator."""

import asyncio
import math

import pytest
from pydantic import ValidationError

from core.models import CDragonChampion
from domain.tools import call_tool, rolldown
from domain.tools.rolldown import (
    RolldownRequest,
    RolldownRunParameters,
    RolldownTargetDefinition,
    calculate_rolldown_for_roster,
)
from services import rolldown_service


@pytest.fixture
def roster() -> list[CDragonChampion]:
    """Provide two named champions per cost without contacting static-data APIs."""
    return [
        CDragonChampion(
            name=f"Unit {cost}{letter}", apiName=f"TFT_Unit{cost}{letter}", cost=cost,
        )
        for cost in range(1, 6)
        for letter in ("A", "B")
    ]


def test_three_cost_matches_unspecified_champion_shop_probability(roster) -> None:
    """An unspecified 3-cost has one champion's share of the 3-cost pool."""
    request = RolldownRequest(
        level=7, budget=1, budget_type="rolls",
        targets=[{"unit": "3-cost", "copies_needed": 3}],
        simulations=20_000,
    )
    result = calculate_rolldown_for_roster(request, roster)
    per_slot = 0.4 * 18 / (2 * 18)
    expected = sum(
        math.comb(5, hits) * per_slot ** hits * (1 - per_slot) ** (5 - hits)
        for hits in range(3, 6)
    )
    assert result["probability_hit"] == pytest.approx(expected, abs=0.015)
    assert result["targets"][0]["unit"] == "3-cost"
    assert result["targets"][0]["target_kind"] == "unspecified_cost_unit"


def test_generic_target_matches_a_named_champion_at_its_cost(roster) -> None:
    """Keep generic targets mathematically identical to a named unit target."""
    generic = RolldownRequest(
        level=1, budget=5,
        targets=[{"unit": "1-cost", "copies_needed": 3}], simulations=800,
    )
    named = RolldownRequest(
        level=1, budget=5,
        targets=[{"unit": "Unit 1A", "copies_needed": 3}], simulations=800,
    )
    generic_result = calculate_rolldown_for_roster(generic, roster)
    named_result = calculate_rolldown_for_roster(named, roster)
    for field in ("probability_hit", "expected_gold_spent", "expected_shops_seen"):
        assert generic_result[field] == named_result[field]
    assert generic_result["targets"][0]["copies_found_distribution"] == (
        named_result["targets"][0]["copies_found_distribution"]
    )


def test_generic_target_respects_one_champion_bag_size(roster) -> None:
    """Reject more requested copies than remain for the unnamed champion."""
    request = RolldownRequest(
        level=1, budget=2, budget_type="rolls",
        targets=[{"unit": "1-cost", "copies_needed": 2, "copies_out": 29}],
    )
    with pytest.raises(ValueError, match="Not enough 1-cost copies remain"):
        calculate_rolldown_for_roster(request, roster)


def test_generic_target_uses_named_target_pool_pressure_behavior(roster) -> None:
    """Keep generic-target pressure semantics consistent with named targets."""
    generic = RolldownRequest(
        level=1, budget=2, budget_type="rolls",
        targets=[{"unit": "1-cost", "copies_needed": 1}],
        pool_pressure=0.99, stop_at_hit=False, buy_extras=True, simulations=800,
    )
    named = RolldownRequest.model_validate({
        **generic.model_dump(),
        "targets": [{"unit": "Unit 1A", "copies_needed": 1}],
    })
    assert calculate_rolldown_for_roster(generic, roster)["probability_hit"] == (
        calculate_rolldown_for_roster(named, roster)["probability_hit"]
    )


@pytest.mark.parametrize("targets,match", [
    ([{"unit": "3-cost", "copies_needed": 1}, {"unit": "Unit 3A", "copies_needed": 1}], "overlap"),
    ([{"unit": "6-cost", "copies_needed": 1}], "not a normal"),
    ([{"unit": "3-cost", "copies_needed": 1, "copies_out": 19}], "bag size"),
    ([{"unit": "Unit 3A", "copies_needed": 1, "copies_out": 19}], "bag size"),
])
def test_invalid_or_overlapping_cost_tier_inputs(roster, targets, match) -> None:
    """Reject unsupported tiers, double-counted targets, and impossible removals."""
    request = RolldownRequest(level=7, budget=2, targets=targets, simulations=800)
    with pytest.raises(ValueError, match=match):
        calculate_rolldown_for_roster(request, roster)


def test_generic_aliases_cannot_duplicate_a_target() -> None:
    """Use the existing punctuation-insensitive identity check for tier names."""
    with pytest.raises(ValidationError, match="only once"):
        RolldownRequest(
            level=7, budget=2,
            targets=[
                {"unit": "3-cost", "copies_needed": 1},
                {"unit": "3 COST", "copies_needed": 1},
            ],
        )


def test_generic_and_named_targets_at_different_costs(roster) -> None:
    """Keep target rules and result ordering when generic and exact goals mix."""
    request = RolldownRequest(
        level=1, budget=1, budget_type="rolls",
        targets=[
            {"unit": "1-cost", "copies_needed": 1},
            {"unit": "Unit 3A", "copies_needed": 1},
        ],
        target_mode="any", simulations=800,
    )
    result = calculate_rolldown_for_roster(request, roster)
    assert 0.9 < result["probability_hit"] < 1
    assert [target["target_kind"] for target in result["targets"]] == ["unspecified_cost_unit", "unit"]
    assert result["targets"][1]["probability_find_all"] == 0


def test_registered_tool_accepts_generic_target(monkeypatch, roster) -> None:
    """Exercise SDK parsing and result serialization with a generic target."""
    async def calculate_with_roster(request: RolldownRequest) -> dict[str, object]:
        """Use the real calculator with a deterministic offline roster."""
        return calculate_rolldown_for_roster(request, roster)

    monkeypatch.setattr(rolldown, "calculate_rolldown_request", calculate_with_roster)
    result = asyncio.run(call_tool("rolldown_probabilities", {"request": {
        "level": 1, "budget": 5, "simulations": 800,
        "targets": [{"unit": "1-cost", "copies_needed": 3}],
    }}))
    assert result["targets"][0]["target_kind"] == "unspecified_cost_unit"


def test_prepared_run_analysis_accepts_generic_purchase_target(roster) -> None:
    """Carry generic purchases through the browser-facing reusable-run path."""
    parameters = RolldownRunParameters(
        level=7, budget=1, budget_type="rolls", simulations=800,
    )
    run = rolldown_service.PreparedRun(
        id="run-1", label="Baseline", group="Run comparison", parameters=parameters,
    )
    run_set = rolldown_service.PreparedRunSet(
        id="prepared", created_at=0, runs=(run,), champions=tuple(roster),
        trial_seeds=tuple(range(800)),
    )
    definition = RolldownTargetDefinition(
        purchases=[{"unit": "3-cost"}],
        groups=[{"conditions": [{"unit": "3-cost", "copies_at_least": 1}]}],
    )
    result = rolldown_service._analyze_prepared_runs(run_set, ["run-1"], definition)
    target = result[0]["result"]["targets"][0]
    assert target["target_kind"] == "unspecified_cost_unit"
    assert result[0]["result"]["purchase_plan"] == [{"unit": "3-cost", "copies_out": 0}]
