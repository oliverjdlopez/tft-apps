from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest

from domain.tools.rolldown import (
    COPIES_PER_CHAMPION,
    SHOP_ODDS,
    RolldownRequest,
    RolldownRunParameters,
    RolldownTargetDefinition,
    _wilson_score_interval_95,
    calculate_rolldown,
    calculate_rolldown_for_roster,
)
from services import rolldown_service


ROSTER_COUNTS = {1: 13, 2: 13, 3: 13, 4: 12, 5: 8}


def test_shop_parameters_are_complete_probabilities() -> None:
    assert set(SHOP_ODDS) == set(range(1, 11))
    assert all(math.isclose(sum(odds), 1.0) for odds in SHOP_ODDS.values())
    assert COPIES_PER_CHAMPION == {1: 30, 2: 25, 3: 18, 4: 10, 5: 9}


def test_wilson_interval_uses_binomial_success_count() -> None:
    """Pointwise bounds should match a known 40-of-100 Wilson interval."""
    lower, upper = _wilson_score_interval_95(40, 100)

    assert lower == pytest.approx(0.3094, abs=0.0001)
    assert upper == pytest.approx(0.4980, abs=0.0001)


def test_impossible_cost_at_level_has_zero_hit_probability() -> None:
    result = calculate_rolldown(
        level=4,
        budget=10,
        budget_type="rolls",
        targets=[("Example Four Cost", 4, 1, 0)],
        roster_counts=ROSTER_COUNTS,
    )

    assert result["probability_find_all_targets"] == 0.0
    assert result["targets"][0]["copies_found_distribution"] == {"0": 1.0, "1": 0.0}


def test_single_slot_equivalent_matches_finite_pool_probability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("domain.tools.rolldown.SHOP_SIZE", 1)
    result = calculate_rolldown(
        level=3,
        budget=1,
        budget_type="rolls",
        targets=[("Example One Cost", 1, 1, 0)],
        roster_counts=ROSTER_COUNTS,
        simulations=100_000,
    )

    expected = 0.75 * 30 / (13 * 30)
    assert result["probability_find_all_targets"] == pytest.approx(expected, abs=0.0015)


def test_depleted_shared_pool_increases_target_odds() -> None:
    baseline = calculate_rolldown(
        level=6,
        budget=5,
        budget_type="rolls",
        targets=[("Example Three Cost", 3, 1, 0)],
        roster_counts=ROSTER_COUNTS,
    )
    depleted = calculate_rolldown(
        level=6,
        budget=5,
        budget_type="rolls",
        targets=[("Example Three Cost", 3, 1, 0)],
        roster_counts=ROSTER_COUNTS,
        other_removed_by_cost={3: 100},
    )

    assert depleted["probability_find_all_targets"] > baseline["probability_find_all_targets"]


def test_multiple_targets_return_joint_and_per_target_outcomes() -> None:
    result = calculate_rolldown(
        level=8,
        budget=4,
        budget_type="rolls",
        targets=[("Example Four Cost", 4, 2, 1), ("Example Five Cost", 5, 1, 0)],
        roster_counts=ROSTER_COUNTS,
    )

    assert 0 < result["probability_find_all_targets"] < 1
    assert [target["unit"] for target in result["targets"]] == [
        "Example Four Cost",
        "Example Five Cost",
    ]
    for target in result["targets"]:
        assert math.isclose(sum(target["copies_found_distribution"].values()), 1.0, abs_tol=1e-7)


def test_post_run_target_types_change_the_same_seeded_outcomes() -> None:
    """Any and threshold rules should be evaluable over identical trial seeds."""
    trial_seeds = tuple(range(800))
    arguments = {
        "level": 8,
        "budget": 4,
        "budget_type": "rolls",
        "targets": [
            ("Example Four Cost", 4, 1, 0),
            ("Example Five Cost", 5, 1, 0),
        ],
        "roster_counts": ROSTER_COUNTS,
        "simulations": 800,
        "trial_seeds": trial_seeds,
    }

    all_targets = calculate_rolldown(**arguments, target_mode="all")
    any_target = calculate_rolldown(**arguments, target_mode="any")

    assert any_target["probability_hit"] > all_targets["probability_hit"]
    assert any_target["target_mode"] == "any"
    assert all_targets["minimum_targets"] == 2


def test_seeded_simulation_is_reproducible() -> None:
    """A fixed seed should make scenario comparisons repeatable."""
    arguments = {
        "level": 8,
        "budget": 10,
        "budget_type": "rolls",
        "targets": [("Example Four Cost", 4, 2, 0)],
        "roster_counts": ROSTER_COUNTS,
        "simulations": 1_000,
        "seed": 42,
    }

    assert calculate_rolldown(**arguments) == calculate_rolldown(**arguments)


def test_extended_result_tracks_cumulative_hits_spend_and_bounded_trials() -> None:
    """Explorer data should be aligned, cumulative, and safely sampled."""
    result = calculate_rolldown(
        level=8,
        budget=12,
        budget_type="rolls",
        targets=[("Example Four Cost", 4, 2, 0)],
        roster_counts=ROSTER_COUNTS,
        include_trials=True,
        trials_sample_cap=37,
        simulations=800,
        seed=42,
    )

    assert result["max_shops"] == 12
    assert len(result["hit_all_by_shop"]) == 13
    assert len(result["hit_all_by_shop_confidence_95"]) == 13
    assert len(result["spend_by_shop"]) == 13
    assert result["hit_all_by_shop"] == sorted(result["hit_all_by_shop"])
    assert result["spend_by_shop"] == sorted(result["spend_by_shop"])
    assert result["hit_all_by_shop"][-1] == result["probability_find_all_targets"]
    for probability, interval in zip(
        result["hit_all_by_shop"],
        result["hit_all_by_shop_confidence_95"],
        strict=True,
    ):
        assert 0 <= interval["lower"] <= probability <= interval["upper"] <= 1
    interval_widths = {
        round(interval["upper"] - interval["lower"], 8)
        for interval in result["hit_all_by_shop_confidence_95"]
    }
    assert len(interval_widths) > 1
    assert len(result["trials"]) == 37
    assert all(len(trial["copies"]) == 1 for trial in result["trials"])
    assert all("shops_seen" in trial for trial in result["trials"])

    without_trials = calculate_rolldown(
        level=8,
        budget=12,
        budget_type="rolls",
        targets=[("Example Four Cost", 4, 2, 0)],
        roster_counts=ROSTER_COUNTS,
        simulations=800,
        seed=42,
    )

    assert "trials" not in without_trials
    assert without_trials["probability_find_all_targets"] == result[
        "probability_find_all_targets"
    ]


def test_rollout_and_extra_purchase_options_extend_trials() -> None:
    """Rollout trials should consume every roll and retain extra target copies."""
    result = calculate_rolldown(
        level=8,
        budget=20,
        budget_type="rolls",
        targets=[("Example Four Cost", 4, 1, 0)],
        roster_counts=ROSTER_COUNTS,
        stop_at_hit=False,
        buy_extras=True,
        include_trials=True,
        simulations=800,
        seed=7,
    )

    assert result["expected_shops_seen"] == 20
    assert result["expected_gold_spent"] >= 40
    assert any(trial["copies"][0] > 1 for trial in result["trials"])
    assert max(map(int, result["targets"][0]["copies_found_distribution"])) > 1


def test_full_pool_pressure_remains_a_bounded_coarse_estimate() -> None:
    """Maximum coarse pressure should not exhaust a generated shop mid-trial."""
    result = calculate_rolldown(
        level=8,
        budget=2,
        budget_type="rolls",
        targets=[("Example Four Cost", 4, 1, 0)],
        roster_counts=ROSTER_COUNTS,
        pool_pressure=1.0,
        simulations=800,
    )

    assert 0.0 <= result["probability_find_all_targets"] <= 1.0


def test_gold_is_default_budget_and_requires_affordable_purchases() -> None:
    gold_limited = calculate_rolldown(
        level=8,
        budget=10,
        targets=[("Example Five Cost", 5, 1, 0)],
        roster_counts=ROSTER_COUNTS,
    )
    roll_limited = calculate_rolldown(
        level=8,
        budget=5,
        budget_type="rolls",
        targets=[("Example Five Cost", 5, 1, 0)],
        roster_counts=ROSTER_COUNTS,
    )

    assert gold_limited["budget_type"] == "gold"
    assert gold_limited["expected_shops_seen"] < 5
    assert roll_limited["expected_shops_seen"] <= 5
    assert gold_limited["probability_find_all_targets"] < roll_limited[
        "probability_find_all_targets"
    ]


def test_unaffordable_hit_is_not_counted_as_purchased() -> None:
    gold_limited = calculate_rolldown(
        level=8,
        budget=2,
        targets=[("Example Five Cost", 5, 1, 0)],
        roster_counts=ROSTER_COUNTS,
    )
    one_roll = calculate_rolldown(
        level=8,
        budget=1,
        budget_type="rolls",
        targets=[("Example Five Cost", 5, 1, 0)],
        roster_counts=ROSTER_COUNTS,
    )

    assert gold_limited["probability_find_all_targets"] == 0.0
    assert one_roll["probability_find_all_targets"] > 0.0
    assert gold_limited["expected_shops_seen"] == 1


def test_rejects_request_for_more_copies_than_remain() -> None:
    with pytest.raises(ValueError, match="Not enough"):
        calculate_rolldown(
            level=8,
            budget=1,
            budget_type="rolls",
            targets=[("Example Five Cost", 5, 2, 8)],
            roster_counts=ROSTER_COUNTS,
        )


def test_zero_copy_target_is_satisfied_before_the_first_shop() -> None:
    """A zero-copy goal should be a real initial hit, not the miss sentinel."""
    result = calculate_rolldown(
        level=8,
        budget=5,
        budget_type="rolls",
        targets=[("Example Five Cost", 5, 0, 9)],
        roster_counts=ROSTER_COUNTS,
        include_trials=True,
        trials_sample_cap=5,
        simulations=800,
    )

    assert result["probability_hit"] == 1.0
    assert result["expected_shops_seen"] == 0.0
    assert result["hit_all_by_shop"] == [1.0] * 6
    assert all(trial["hit"] is True for trial in result["trials"])
    assert all(trial["hit_shop"] == 0 for trial in result["trials"])


def test_target_copies_out_cannot_exceed_selected_unit_bag() -> None:
    """Target depletion should use the resolved unit cost's exact bag size."""
    request = RolldownRequest(
        level=8,
        budget=5,
        targets=[{"unit": "Example", "copies_needed": 0, "copies_out": 10}],
    )

    with pytest.raises(ValueError, match="exceeds the bag size"):
        calculate_rolldown_for_roster(
            request,
            [SimpleNamespace(name="Example", apiName="TFT_Example", cost=5)],
        )


def test_rolldown_units_returns_only_sorted_normal_shop_champions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The UI catalog should expose safe current-roster input metadata."""

    class FakeCDragon:
        """Small static-data client stub for the rolldown UI catalog."""

        async def all_sets(self) -> list[SimpleNamespace]:
            """Return a partial future roster after one complete live roster."""
            complete = [
                SimpleNamespace(name=name, apiName=f"TFT_{name}", cost=cost)
                for name, cost in [
                    ("Five", 5),
                    ("Two", 2),
                    ("Four", 4),
                    ("One", 1),
                    ("Three", 3),
                ]
            ]
            return [
                SimpleNamespace(number=16, champions=complete),
                SimpleNamespace(
                    number=17,
                    champions=[SimpleNamespace(name="Future", apiName="TFT_Future", cost=4)],
                ),
            ]

        async def aclose(self) -> None:
            """Match the production client cleanup contract."""

    monkeypatch.setattr(rolldown_service, "CDragon", FakeCDragon)

    result = asyncio.run(rolldown_service.units())

    assert result == {
        "units": [
            {"name": "One", "cost": 1, "bag_size": 30},
            {"name": "Two", "cost": 2, "bag_size": 25},
            {"name": "Three", "cost": 3, "bag_size": 18},
            {"name": "Four", "cost": 4, "bag_size": 10},
            {"name": "Five", "cost": 5, "bag_size": 9},
        ]
    }


def test_rolldown_simulate_reuses_one_roster_for_grouped_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A grouped experiment should load static roster data only once."""
    loaded_clients: list[object] = []

    class FakeCDragon:
        """Track cleanup for the grouped simulation service."""

        def __init__(self) -> None:
            """Create an open fake client."""
            self.closed = False

        async def aclose(self) -> None:
            """Record that the service closed the static-data client."""
            self.closed = True

    async def fake_load(client: object) -> list[SimpleNamespace]:
        """Return one shared roster snapshot for every requested run."""
        loaded_clients.append(client)
        return [SimpleNamespace(name="Example", apiName="TFT_Example", cost=4)]

    def fake_calculate(
        request: RolldownRequest,
        champions: list[SimpleNamespace],
    ) -> dict[str, object]:
        """Return enough data to show each request used the shared roster."""
        return {"budget": request.budget, "roster_size": len(champions)}

    monkeypatch.setattr(rolldown_service, "CDragon", FakeCDragon)
    monkeypatch.setattr(rolldown_service, "load_rolldown_champions", fake_load)
    monkeypatch.setattr(rolldown_service, "calculate_rolldown_for_roster", fake_calculate)
    scenarios = [
        (
            f"run-{budget}",
            f"{budget} gold",
            "Budget sweep",
            RolldownRequest(
                level=8,
                budget=budget,
                targets=[{"unit": "Example", "copies_needed": 1}],
            ),
        )
        for budget in (20, 40)
    ]

    result = asyncio.run(rolldown_service.simulate(scenarios))

    assert len(loaded_clients) == 1
    assert loaded_clients[0].closed is True
    assert result == {
        "runs": [
            {
                "id": "run-20",
                "label": "20 gold",
                "group": "Budget sweep",
                "result": {"budget": 20, "roster_size": 1},
            },
            {
                "id": "run-40",
                "label": "40 gold",
                "group": "Budget sweep",
                "result": {"budget": 40, "roster_size": 1},
            },
        ]
    }


def test_prepared_runs_reuse_roster_and_samples_for_new_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Targets should be analyzed after run creation without loading new samples."""
    loaded_clients: list[object] = []
    calculations: list[tuple[int, str, tuple[int, ...]]] = []

    class FakeCDragon:
        """Track target-independent roster preparation."""

        async def aclose(self) -> None:
            """Match the production client cleanup contract."""

    async def fake_load(client: object) -> list[SimpleNamespace]:
        """Return a shared roster and record its single load."""
        loaded_clients.append(client)
        return [SimpleNamespace(name="Example", apiName="TFT_Example", cost=4)]

    def fake_calculate(
        request: RolldownRequest,
        champions: list[SimpleNamespace],
        *,
        trial_seeds: tuple[int, ...] | None = None,
    ) -> dict[str, object]:
        """Record the prepared samples used for each target query."""
        assert len(champions) == 1
        assert trial_seeds is not None
        calculations.append((request.budget, request.target_mode, trial_seeds))
        return {"probability_hit": request.budget / 100}

    rolldown_service._PREPARED_RUNS.clear()
    monkeypatch.setattr(rolldown_service, "CDragon", FakeCDragon)
    monkeypatch.setattr(rolldown_service, "load_rolldown_champions", fake_load)
    monkeypatch.setattr(rolldown_service, "calculate_rolldown_for_roster", fake_calculate)

    prepared = asyncio.run(
        rolldown_service.prepare_runs(
            base=RolldownRunParameters(
                level=8,
                budget=30,
                simulations=800,
                seed=42,
            ),
            sweep_dimension="budget",
            sweep_values=[20.0, 40.0],
        )
    )
    run_ids = [run["id"] for run in prepared["runs"]]
    first = asyncio.run(
        rolldown_service.analyze_prepared_runs(
            run_set_id=str(prepared["run_set_id"]),
            run_ids=run_ids,
            definition=RolldownTargetDefinition(
                target_mode="all",
                targets=[{"unit": "Example", "copies_needed": 2}],
            ),
        )
    )
    second = asyncio.run(
        rolldown_service.analyze_prepared_runs(
            run_set_id=str(prepared["run_set_id"]),
            run_ids=[run_ids[0]],
            definition=RolldownTargetDefinition(
                target_mode="any",
                targets=[{"unit": "Example", "copies_needed": 1}],
            ),
        )
    )

    assert len(loaded_clients) == 1
    assert prepared["sweeps"] == [
        {"dimension": "budget", "values": [20.0, 40.0]}
    ]
    assert [run["parameters"]["budget"] for run in prepared["runs"]] == [20, 40]
    assert [run["coordinates"] for run in prepared["runs"]] == [
        {"budget": 20.0},
        {"budget": 40.0},
    ]
    assert [run["result"]["probability_hit"] for run in first["runs"]] == [0.2, 0.4]
    assert second["runs"][0]["result"]["probability_hit"] == 0.2
    assert calculations[0][2] is calculations[-1][2]


def test_prepared_boolean_query_buys_all_listed_units_for_full_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boolean analysis should derive purchase caps without stopping at a hit."""
    captured: dict[str, object] = {}

    def fake_calculate(
        request: RolldownRequest,
        champions: list[SimpleNamespace],
        **options: object,
    ) -> dict[str, object]:
        """Capture the simulator request and the post-run outcome query."""
        captured["request"] = request
        captured["query"] = options["outcome_query"]
        return {"probability_hit": 0.5}

    run = rolldown_service.PreparedRun(
        id="run-1",
        label="Baseline",
        group="Run comparison",
        parameters=RolldownRunParameters(level=8, budget=30, simulations=800),
    )
    run_set = rolldown_service.PreparedRunSet(
        id="prepared",
        created_at=0,
        runs=(run,),
        champions=(
            SimpleNamespace(name="Unit A", apiName="TFT_A", cost=4),
            SimpleNamespace(name="Unit B", apiName="TFT_B", cost=4),
        ),
        trial_seeds=tuple(range(800)),
    )
    definition = RolldownTargetDefinition.model_validate(
        {
            "purchases": [{"unit": "Unit A"}, {"unit": "Unit B"}],
            "outcome_operator": "any",
            "groups": [
                {
                    "operator": "all",
                    "conditions": [
                        {"unit": "Unit A", "copies_at_least": 3},
                        {"unit": "Unit B", "copies_at_least": 9},
                    ],
                },
                {
                    "operator": "all",
                    "conditions": [
                        {"unit": "Unit A", "copies_at_least": 9},
                        {"unit": "Unit B", "copies_at_least": 3},
                    ],
                },
            ],
        }
    )
    monkeypatch.setattr(rolldown_service, "calculate_rolldown_for_roster", fake_calculate)

    results = rolldown_service._analyze_prepared_runs(run_set, ["run-1"], definition)

    request = captured["request"]
    assert isinstance(request, RolldownRequest)
    assert [target.copies_needed for target in request.targets] == [9, 9]
    assert request.buy_extras is True
    assert request.stop_at_hit is False
    assert captured["query"] is definition
    assert results[0]["result"]["purchase_plan"] == [
        {"unit": "Unit A", "copies_out": 0},
        {"unit": "Unit B", "copies_out": 0},
    ]


def test_boolean_outcome_groups_use_inner_and_outer_operators() -> None:
    """Core simulation should report group and combined Boolean probabilities."""
    result = calculate_rolldown(
        level=8,
        budget=1,
        targets=[("Unit A", 4, 9, 10), ("Unit B", 4, 9, 10)],
        roster_counts=ROSTER_COUNTS,
        outcome_groups=[("all", [(0, 0), (1, 0)]), ("all", [(0, 9), (1, 9)])],
        outcome_operator="any",
        stop_at_hit=False,
        buy_extras=True,
        simulations=20,
        seed=7,
    )

    assert result["probability_hit"] == 1.0
    assert [group["probability"] for group in result["outcome_groups"]] == [1.0, 0.0]
    assert result["parameters"]["outcome_operator"] == "any"


def test_prepared_runs_expand_two_sweeps_as_a_cartesian_grid() -> None:
    """Every pair of axis values should produce a coordinate-addressable run."""
    runs = rolldown_service._sweep_parameters(
        RolldownRunParameters(level=8, budget=30, simulations=800),
        [
            ("level", [7.0, 8.0]),
            ("pressure", [0.0, 25.0, 50.0]),
        ],
    )

    assert len(runs) == 6
    assert [run.coordinates for run in runs] == [
        (("level", 7.0), ("pressure", 0.0)),
        (("level", 7.0), ("pressure", 25.0)),
        (("level", 7.0), ("pressure", 50.0)),
        (("level", 8.0), ("pressure", 0.0)),
        (("level", 8.0), ("pressure", 25.0)),
        (("level", 8.0), ("pressure", 50.0)),
    ]
    assert [(run.parameters.level, run.parameters.pool_pressure) for run in runs] == [
        (7, 0.0),
        (7, 0.25),
        (7, 0.5),
        (8, 0.0),
        (8, 0.25),
        (8, 0.5),
    ]
    assert all(run.group == "Level × Pressure grid" for run in runs)


def test_rolldown_explore_reuses_roster_and_duplicate_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heatmaps and sweeps should share one roster and cached calculations."""
    loaded_clients: list[object] = []
    calculated: list[tuple[int, int, int]] = []

    class FakeCDragon:
        """Track cleanup for the specialized exploration service."""

        def __init__(self) -> None:
            """Create an open fake client."""
            self.closed = False

        async def aclose(self) -> None:
            """Record that the service closed the static-data client."""
            self.closed = True

    async def fake_load(client: object) -> list[SimpleNamespace]:
        """Return one shared roster snapshot for the exploration."""
        loaded_clients.append(client)
        return [SimpleNamespace(name="Example", apiName="TFT_Example", cost=4)]

    def fake_calculate(
        request: RolldownRequest,
        champions: list[SimpleNamespace],
    ) -> dict[str, object]:
        """Track unique calculation inputs and their shared roster."""
        assert len(champions) == 1
        calculated.append((request.level, request.budget, request.simulations))
        return {
            "probability_find_all_targets": request.budget / 100,
            "budget": request.budget,
        }

    monkeypatch.setattr(rolldown_service, "CDragon", FakeCDragon)
    monkeypatch.setattr(rolldown_service, "load_rolldown_champions", fake_load)
    monkeypatch.setattr(rolldown_service, "calculate_rolldown_for_roster", fake_calculate)

    result = asyncio.run(
        rolldown_service.explore(
            request=RolldownRequest(
                level=8,
                budget=30,
                targets=[{"unit": "Example", "copies_needed": 1}],
            ),
            levels=[8],
            budgets=[20, 30],
            sweep_dimension="budget",
            sweep_values=[20.0, 30.0],
            simulations=800,
        )
    )

    assert len(loaded_clients) == 1
    assert loaded_clients[0].closed is True
    assert calculated == [(8, 20, 800), (8, 30, 800)]
    assert result["heatmap"] == {
        "levels": [8],
        "budgets": [20, 30],
        "grid": [[0.2, 0.3]],
    }
    assert [item["v"] for item in result["sweep"]] == [20, 30]
    assert [item["req"]["simulations"] for item in result["sweep"]] == [20_000, 20_000]
    assert result["unique_scenarios"] == 2
