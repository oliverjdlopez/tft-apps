from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import rolldown


def _client() -> TestClient:
    """Create an isolated client for the rolldown router.

    Returns:
        A test client with only rolldown endpoints mounted.
    """
    app = FastAPI()
    app.include_router(rolldown.router)
    return TestClient(app)


def test_rolldown_units_delegates_to_dedicated_service(monkeypatch) -> None:
    """The unit catalog endpoint should use the rolldown service."""

    async def fake_units() -> dict[str, object]:
        """Return a stable unit catalog response for the route test."""
        return {"units": [{"name": "Example", "cost": 4, "bag_size": 10}]}

    monkeypatch.setattr(rolldown.rolldown_service, "units", fake_units)

    response = _client().get("/api/rolldown/units")

    assert response.status_code == 200
    assert response.json() == {
        "units": [{"name": "Example", "cost": 4, "bag_size": 10}]
    }


def test_rolldown_runs_prepare_without_targets(monkeypatch) -> None:
    """Run creation should accept two target-independent sweep dimensions."""

    async def fake_prepare_runs(**options) -> dict[str, object]:
        """Expose validated target-independent inputs for the assertion."""
        return {
            "run_set_id": "prepared",
            "level": options["base"].level,
            "sweeps": options["sweeps"],
        }

    monkeypatch.setattr(rolldown.rolldown_service, "prepare_runs", fake_prepare_runs)
    response = _client().post(
        "/api/rolldown/runs",
        json={
            "parameters": {
                "level": 8,
                "budget": 30,
                "budget_type": "gold",
                "pool_pressure": 0.2,
                "simulations": 2_000,
                "seed": 7,
            },
            "sweeps": [
                {"dimension": "budget", "values": [20, 40, 60]},
                {"dimension": "pressure", "values": [0, 25, 50]},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_set_id": "prepared",
        "level": 8,
        "sweeps": [
            ["budget", [20.0, 40.0, 60.0]],
            ["pressure", [0.0, 25.0, 50.0]],
        ],
    }


def test_rolldown_runs_reject_duplicate_sweep_dimensions() -> None:
    """A two-dimensional grid must use two distinct axes."""
    response = _client().post(
        "/api/rolldown/runs",
        json={
            "parameters": {"level": 8, "budget": 30},
            "sweeps": [
                {"dimension": "budget", "values": [20, 30]},
                {"dimension": "budget", "values": [40, 50]},
            ],
        },
    )

    assert response.status_code == 422


def test_rolldown_runs_accept_legacy_singular_sweep(monkeypatch) -> None:
    """Existing one-sweep clients should normalize into the new list contract."""

    async def fake_prepare_runs(**options) -> dict[str, object]:
        """Expose the normalized service argument."""
        return {"sweeps": options["sweeps"]}

    monkeypatch.setattr(rolldown.rolldown_service, "prepare_runs", fake_prepare_runs)
    response = _client().post(
        "/api/rolldown/runs",
        json={
            "parameters": {"level": 8, "budget": 30},
            "sweep": {"dimension": "level", "values": [7, 8, 9]},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"sweeps": [["level", [7.0, 8.0, 9.0]]]}


def test_rolldown_runs_do_not_cap_two_sweep_combinations(monkeypatch) -> None:
    """Validation should not impose a Cartesian-product combination limit."""

    async def fake_prepare_runs(**options) -> dict[str, object]:
        """Return the number of combinations accepted by request validation."""
        first, second = options["sweeps"]
        return {"combinations": len(first[1]) * len(second[1])}

    monkeypatch.setattr(rolldown.rolldown_service, "prepare_runs", fake_prepare_runs)
    response = _client().post(
        "/api/rolldown/runs",
        json={
            "parameters": {"level": 8, "budget": 30},
            "sweeps": [
                {"dimension": "budget", "values": list(range(1, 15))},
                {"dimension": "pressure", "values": list(range(0, 70, 5))},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"combinations": 196}


def test_rolldown_runs_reject_targets_during_preparation() -> None:
    """Targets must not leak back into the run-creation phase."""
    response = _client().post(
        "/api/rolldown/runs",
        json={
            "parameters": {
                "level": 8,
                "budget": 30,
                "targets": [{"unit": "Example", "copies_needed": 1}],
            }
        },
    )

    assert response.status_code == 422


def test_rolldown_prepared_analysis_delegates_target_rule(monkeypatch) -> None:
    """Post-run analysis should preserve run selection and target type."""

    async def fake_analyze_prepared_runs(**options) -> dict[str, object]:
        """Expose the typed target definition received by the service."""
        return {
            "run_set_id": options["run_set_id"],
            "run_ids": options["run_ids"],
            "mode": options["definition"].target_mode,
            "minimum": options["definition"].minimum_targets,
        }

    monkeypatch.setattr(
        rolldown.rolldown_service,
        "analyze_prepared_runs",
        fake_analyze_prepared_runs,
    )
    response = _client().post(
        "/api/rolldown/runs/analyze",
        json={
            "run_set_id": "prepared",
            "run_ids": ["run-1", "run-2"],
            "target": {
                "target_mode": "at_least",
                "minimum_targets": 2,
                "targets": [
                    {"unit": "Example", "copies_needed": 2},
                    {"unit": "Other", "copies_needed": 1},
                ],
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_set_id": "prepared",
        "run_ids": ["run-1", "run-2"],
        "mode": "at_least",
        "minimum": 2,
    }


def test_rolldown_prepared_analysis_accepts_boolean_purchase_query(monkeypatch) -> None:
    """Purchase plans and nested Boolean groups should cross the API boundary."""

    async def fake_analyze_prepared_runs(**options) -> dict[str, object]:
        """Echo the new typed purchase and outcome-query fields."""
        definition = options["definition"]
        return {
            "purchases": [purchase.unit for purchase in definition.purchases],
            "outer": definition.outcome_operator,
            "groups": [group.operator for group in definition.groups],
        }

    monkeypatch.setattr(
        rolldown.rolldown_service,
        "analyze_prepared_runs",
        fake_analyze_prepared_runs,
    )
    response = _client().post(
        "/api/rolldown/runs/analyze",
        json={
            "run_set_id": "prepared",
            "run_ids": ["run-1"],
            "target": {
                "purchases": [
                    {"unit": "Unit A", "copies_out": 0},
                    {"unit": "Unit B", "copies_out": 2},
                ],
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
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "purchases": ["Unit A", "Unit B"],
        "outer": "any",
        "groups": ["all", "all"],
    }


def test_rolldown_prepared_analysis_accepts_full_uncapped_grid(monkeypatch) -> None:
    """Analysis selection must not restore the former twelve-run ceiling."""

    async def fake_analyze_prepared_runs(**options) -> dict[str, object]:
        """Return the accepted grid selection size."""
        return {"selected": len(options["run_ids"])}

    monkeypatch.setattr(
        rolldown.rolldown_service,
        "analyze_prepared_runs",
        fake_analyze_prepared_runs,
    )
    response = _client().post(
        "/api/rolldown/runs/analyze",
        json={
            "run_set_id": "prepared",
            "run_ids": [f"run-{index}" for index in range(1, 21)],
            "target": {
                "targets": [{"unit": "Example", "copies_needed": 1}],
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {"selected": 20}


def test_rolldown_calculate_delegates_validated_request(monkeypatch) -> None:
    """The calculate endpoint should pass typed inputs to the service."""

    async def fake_calculate(request) -> dict[str, object]:
        """Echo the validated request fields used by the browser contract."""
        return {
            "level": request.level,
            "budget": request.budget,
            "target": request.targets[0].unit,
            "pool_pressure": request.pool_pressure,
            "stop_at_hit": request.stop_at_hit,
            "buy_extras": request.buy_extras,
            "include_trials": request.include_trials,
            "trials_sample_cap": request.trials_sample_cap,
        }

    monkeypatch.setattr(rolldown.rolldown_service, "calculate", fake_calculate)

    response = _client().post(
        "/api/rolldown/calculate",
        json={
            "level": 8,
            "budget": 30,
            "targets": [
                {"unit": "Example", "copies_needed": 2, "copies_out": 1}
            ],
            "pool_pressure": 0.25,
            "stop_at_hit": False,
            "buy_extras": True,
            "include_trials": True,
            "trials_sample_cap": 25,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "level": 8,
        "budget": 30,
        "target": "Example",
        "pool_pressure": 0.25,
        "stop_at_hit": False,
        "buy_extras": True,
        "include_trials": True,
        "trials_sample_cap": 25,
    }


def test_rolldown_calculate_bounds_explorer_fields() -> None:
    """Explorer-only request additions should remain strictly bounded."""
    body = {
        "level": 8,
        "budget": 30,
        "targets": [{"unit": "Example", "copies_needed": 1}],
        "simulations": 800,
    }

    assert _client().post(
        "/api/rolldown/calculate",
        json={**body, "pool_pressure": 1.01},
    ).status_code == 422
    assert _client().post(
        "/api/rolldown/calculate",
        json={**body, "trials_sample_cap": 5_001},
    ).status_code == 422


def test_rolldown_calculate_returns_actionable_service_errors(monkeypatch) -> None:
    """Invalid current-roster scenarios should produce an HTTP 400 response."""

    async def fake_calculate(_request) -> dict[str, object]:
        """Raise the domain validation error exposed by the route."""
        raise ValueError("Example is not in the current roster")

    monkeypatch.setattr(rolldown.rolldown_service, "calculate", fake_calculate)

    response = _client().post(
        "/api/rolldown/calculate",
        json={
            "level": 8,
            "budget": 30,
            "targets": [
                {"unit": "Example", "copies_needed": 2, "copies_out": 1}
            ],
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Example is not in the current roster"}


def test_rolldown_explore_delegates_bounded_sensitivity_request(monkeypatch) -> None:
    """The exploration endpoint should pass one typed heatmap and sweep request."""

    async def fake_explore(**options) -> dict[str, object]:
        """Expose validated exploration inputs for the route assertion."""
        return {
            "level": options["request"].level,
            "levels": options["levels"],
            "budgets": options["budgets"],
            "dimension": options["sweep_dimension"],
            "values": options["sweep_values"],
            "simulations": options["simulations"],
        }

    monkeypatch.setattr(rolldown.rolldown_service, "explore", fake_explore)
    response = _client().post(
        "/api/rolldown/explore",
        json={
            "request": {
                "level": 8,
                "budget": 30,
                "targets": [{"unit": "Example", "copies_needed": 2}],
            },
            "levels": [7, 8],
            "budgets": [20, 30],
            "sweep_dimension": "pressure",
            "sweep_values": [0, 20, 40],
            "simulations": 800,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "level": 8,
        "levels": [7, 8],
        "budgets": [20, 30],
        "dimension": "pressure",
        "values": [0.0, 20.0, 40.0],
        "simulations": 800,
    }


def test_rolldown_explore_bounds_total_scenarios() -> None:
    """Exploration requests should reject oversized heatmap and sweep work."""
    response = _client().post(
        "/api/rolldown/explore",
        json={
            "request": {
                "level": 8,
                "budget": 30,
                "targets": [{"unit": "Example", "copies_needed": 2}],
            },
            "levels": [1, 2, 3, 4, 5, 6, 7],
            "budgets": [10, 20, 30, 40, 50, 60, 70],
            "sweep_dimension": "budget",
            "sweep_values": [10],
        },
    )

    assert response.status_code == 422


def test_rolldown_simulate_delegates_labeled_scenarios(monkeypatch) -> None:
    """The experiment endpoint should preserve run identity and grouping."""

    async def fake_simulate(scenarios) -> dict[str, object]:
        """Expose the route-to-service mapping for the assertion."""
        scenario_id, label, group, request = scenarios[0]
        return {
            "runs": [
                {
                    "id": scenario_id,
                    "label": label,
                    "group": group,
                    "result": {"level": request.level},
                }
            ]
        }

    monkeypatch.setattr(rolldown.rolldown_service, "simulate", fake_simulate)

    response = _client().post(
        "/api/rolldown/simulate",
        json={
            "scenarios": [
                {
                    "id": "budget-20",
                    "label": "20 gold",
                    "group": "Budget sweep",
                    "request": {
                        "level": 8,
                        "budget": 20,
                        "targets": [
                            {"unit": "Example", "copies_needed": 1, "copies_out": 0}
                        ],
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "runs": [
            {
                "id": "budget-20",
                "label": "20 gold",
                "group": "Budget sweep",
                "result": {"level": 8},
            }
        ]
    }


def test_rolldown_simulate_bounds_experiment_size() -> None:
    """Experiment requests should reject more than twelve scenarios."""
    scenario = {
        "id": "run",
        "label": "Scenario",
        "group": "Experiment",
        "request": {
            "level": 8,
            "budget": 20,
            "targets": [
                {"unit": "Example", "copies_needed": 1, "copies_out": 0}
            ],
        },
    }

    response = _client().post(
        "/api/rolldown/simulate",
        json={"scenarios": [{**scenario, "id": f"run-{index}"} for index in range(13)]},
    )

    assert response.status_code == 422
