"""Browser-facing rolldown simulation service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from itertools import product
import random
import time
from typing import Any, Literal
from uuid import uuid4

from core.cdragon import CDragon
from core.models import CDragonChampion
from domain.tools.rolldown import (
    COPIES_PER_CHAMPION,
    RolldownRequest,
    RolldownRunParameters,
    RolldownTargetDefinition,
    SHOP_ODDS,
    calculate_rolldown_for_roster,
    calculate_rolldown_request,
    load_rolldown_champions,
)
from utils.tft import TFTNameResolver

RolldownScenario = tuple[str, str, str, RolldownRequest]
RolldownSweepDimension = Literal["budget", "level", "out", "pressure"]
PreparedSweepDimension = Literal["budget", "level", "pressure"]

_PREPARED_RUN_TTL_SECONDS = 30 * 60
_MAX_PREPARED_RUN_SETS = 32


@dataclass(frozen=True)
class PreparedRun:
    """One immutable run configuration in a prepared comparison set."""

    id: str
    label: str
    group: str
    parameters: RolldownRunParameters
    coordinates: tuple[tuple[PreparedSweepDimension, float], ...] = ()


@dataclass(frozen=True)
class PreparedRunSet:
    """Reusable roster and random samples for post-run target analysis."""

    id: str
    created_at: float
    runs: tuple[PreparedRun, ...]
    champions: tuple[CDragonChampion, ...]
    trial_seeds: tuple[int, ...]


_PREPARED_RUNS: dict[str, PreparedRunSet] = {}


def _prune_prepared_runs(now: float | None = None) -> None:
    """Remove expired and oldest prepared run sets from the process cache.

    Args:
        now: Optional monotonic clock value for deterministic tests.
    """
    current = time.monotonic() if now is None else now
    expired = [
        run_set_id
        for run_set_id, run_set in _PREPARED_RUNS.items()
        if current - run_set.created_at > _PREPARED_RUN_TTL_SECONDS
    ]
    for run_set_id in expired:
        _PREPARED_RUNS.pop(run_set_id, None)
    overflow = len(_PREPARED_RUNS) - _MAX_PREPARED_RUN_SETS
    if overflow > 0:
        oldest = sorted(
            _PREPARED_RUNS.values(), key=lambda run_set: run_set.created_at
        )[:overflow]
        for run_set in oldest:
            _PREPARED_RUNS.pop(run_set.id, None)


def _run_label(parameters: RolldownRunParameters) -> str:
    """Return a compact human-readable label for one prepared run.

    Args:
        parameters: Target-independent run configuration.

    Returns:
        Level, budget, and contest summary.
    """
    budget = (
        f"{parameters.budget}g"
        if parameters.budget_type == "gold"
        else f"{parameters.budget} rolls"
    )
    return f"L{parameters.level} · {budget} · {parameters.pool_pressure:.0%} contested"


def _sweep_parameters(
    base: RolldownRunParameters,
    sweeps: list[tuple[PreparedSweepDimension, list[float]]],
) -> list[PreparedRun]:
    """Expand fixed parameters across up to two comparison dimensions.

    Args:
        base: Fixed values used for dimensions outside the sweep.
        sweeps: Ordered dimensions and user-facing values to vary.

    Returns:
        One unique run for every point in the sweep Cartesian product, or one
        baseline when no sweep is requested.
    """
    if not sweeps:
        combinations = iter([()])
        group = "Run comparison"
    else:
        combinations = product(*(values for _, values in sweeps))
        names = [dimension.title() for dimension, _ in sweeps]
        group = " × ".join(names) + (" grid" if len(sweeps) == 2 else " sweep")
    prepared_runs = []
    seen_payloads: set[tuple[object, ...]] = set()
    for combination in combinations:
        payload = base.model_dump()
        coordinates = []
        for (dimension, _), value in zip(sweeps, combination, strict=True):
            if dimension == "budget":
                payload["budget"] = int(value)
            elif dimension == "level":
                payload["level"] = int(value)
            elif dimension == "pressure":
                payload["pool_pressure"] = value / 100
            coordinates.append((dimension, value))
        payload_key = tuple(payload.values())
        if payload_key in seen_payloads:
            continue
        seen_payloads.add(payload_key)
        parameters = RolldownRunParameters.model_validate(payload)
        prepared_runs.append(
            PreparedRun(
                id=f"run-{len(prepared_runs) + 1}",
                label="Baseline" if not sweeps else _run_label(parameters),
                group=group,
                parameters=parameters,
                coordinates=tuple(coordinates),
            )
        )
    return prepared_runs


def _prepared_run_payload(run: PreparedRun) -> dict[str, object]:
    """Serialize safe target-independent metadata for the browser.

    Args:
        run: Prepared run to serialize.

    Returns:
        Public run identity, inputs, and target-independent sample summary.
    """
    parameters = run.parameters
    max_shops = (
        parameters.budget
        if parameters.budget_type == "rolls"
        else parameters.budget // 2
    )
    return {
        "id": run.id,
        "label": run.label,
        "group": run.group,
        "coordinates": dict(run.coordinates),
        "parameters": parameters.model_dump(mode="json"),
        "prepared_samples": parameters.simulations,
        "max_shops": max_shops,
        "expected_slots_by_cost": {
            str(cost): round(max_shops * 5 * probability, 4)
            for cost, probability in enumerate(SHOP_ODDS[parameters.level], start=1)
        },
    }


async def prepare_runs(
    *,
    base: RolldownRunParameters,
    sweeps: list[tuple[PreparedSweepDimension, list[float]]] | None = None,
    sweep_dimension: PreparedSweepDimension | None = None,
    sweep_values: list[float] | None = None,
) -> dict[str, object]:
    """Prepare reusable random samples before the user defines a target.

    Args:
        base: Fixed target-independent values outside the sweep dimension.
        sweeps: Up to two ordered comparison dimensions and their values.
        sweep_dimension: Deprecated singular comparison dimension.
        sweep_values: Deprecated values for the singular dimension.

    Returns:
        Run-set identifier and safe metadata for every prepared run.
    """
    client = CDragon()
    try:
        champions = await load_rolldown_champions(client)
    finally:
        await client.aclose()
    effective_sweeps = list(sweeps or [])
    if not effective_sweeps and sweep_dimension is not None:
        effective_sweeps = [(sweep_dimension, list(sweep_values or []))]
    runs = _sweep_parameters(base, effective_sweeps)
    seed_rng = random.Random(base.seed)
    trial_seeds = tuple(
        seed_rng.randrange(0, 2**63) for _ in range(base.simulations)
    )
    run_set_id = uuid4().hex
    run_set = PreparedRunSet(
        id=run_set_id,
        created_at=time.monotonic(),
        runs=tuple(runs),
        champions=tuple(champions),
        trial_seeds=trial_seeds,
    )
    _PREPARED_RUNS[run_set_id] = run_set
    _prune_prepared_runs(run_set.created_at)
    return {
        "run_set_id": run_set_id,
        "sweeps": [
            {"dimension": dimension, "values": values}
            for dimension, values in effective_sweeps
        ],
        "runs": [_prepared_run_payload(run) for run in runs],
        "expires_in_seconds": _PREPARED_RUN_TTL_SECONDS,
    }


def _analyze_prepared_runs(
    run_set: PreparedRunSet,
    run_ids: list[str],
    definition: RolldownTargetDefinition,
) -> list[dict[str, object]]:
    """Evaluate one target definition across selected prepared runs.

    Args:
        run_set: Cached roster and random trial samples.
        run_ids: Run identities to compare, in browser order.
        definition: Post-run target rule and purchase policy.

    Returns:
        Selected run metadata paired with target-aware simulation results.
    """
    by_id = {run.id: run for run in run_set.runs}
    results = []
    for run_id in run_ids:
        run = by_id[run_id]
        if definition.purchases:
            maximum_thresholds = {
                TFTNameResolver.normalize_name(purchase.unit): max(
                    (
                        condition.copies_at_least
                        for group in definition.groups
                        for condition in group.conditions
                        if TFTNameResolver.normalize_name(condition.unit)
                        == TFTNameResolver.normalize_name(purchase.unit)
                    ),
                    default=0,
                )
                for purchase in definition.purchases
            }
            request = RolldownRequest.model_validate(
                {
                    **run.parameters.model_dump(),
                    "targets": [
                        {
                            "unit": purchase.unit,
                            "copies_needed": maximum_thresholds[
                                TFTNameResolver.normalize_name(purchase.unit)
                            ],
                            "copies_out": purchase.copies_out,
                        }
                        for purchase in definition.purchases
                    ],
                    "other_copies_out": [],
                    "stop_at_hit": False,
                    "buy_extras": True,
                    "include_trials": definition.include_trials,
                    "trials_sample_cap": definition.trials_sample_cap,
                }
            )
            outcome_query = definition
        else:
            request = RolldownRequest.model_validate(
                {
                    **run.parameters.model_dump(),
                    **definition.model_dump(
                        exclude={"purchases", "groups", "outcome_operator"}
                    ),
                    "other_copies_out": [],
                }
            )
            outcome_query = None
        calculation_options: dict[str, object] = {
            "trial_seeds": run_set.trial_seeds,
        }
        if outcome_query is not None:
            calculation_options["outcome_query"] = outcome_query
        result = calculate_rolldown_for_roster(
            request,
            list(run_set.champions),
            **calculation_options,
        )
        if definition.purchases:
            result["purchase_plan"] = [
                purchase.model_dump(mode="json") for purchase in definition.purchases
            ]
            result["outcome_query"] = {
                "operator": definition.outcome_operator,
                "groups": [group.model_dump(mode="json") for group in definition.groups],
            }
        results.append(
            {
                **_prepared_run_payload(run),
                "result": result,
            }
        )
    return results


async def analyze_prepared_runs(
    *,
    run_set_id: str,
    run_ids: list[str],
    definition: RolldownTargetDefinition,
) -> dict[str, object]:
    """Analyze new targets without regenerating the selected runs.

    Args:
        run_set_id: Identifier returned by prepare_runs.
        run_ids: Prepared runs selected for comparison.
        definition: Target rule to evaluate on the shared samples.

    Returns:
        Target definition and one result per selected run.

    Raises:
        ValueError: If the run set expired or a run identity is unknown.
    """
    _prune_prepared_runs()
    run_set = _PREPARED_RUNS.get(run_set_id)
    if run_set is None:
        raise ValueError("This run set expired or does not exist. Run the simulation again.")
    available = {run.id for run in run_set.runs}
    unknown = [run_id for run_id in run_ids if run_id not in available]
    if unknown:
        raise ValueError(f"Unknown prepared run: {unknown[0]}")
    results = await asyncio.to_thread(
        _analyze_prepared_runs,
        run_set,
        run_ids,
        definition,
    )
    return {
        "run_set_id": run_set_id,
        "target": definition.model_dump(mode="json"),
        "runs": results,
    }


async def units() -> dict[str, Any]:
    """Return the current normal-shop champion catalog.

    Returns:
        Champion names, costs, and bag sizes sorted by cost and name.
    """
    client = CDragon()
    try:
        champions = await load_rolldown_champions(client)
    finally:
        await client.aclose()
    units_by_cost = [
        {
            "name": champion.name or champion.apiName,
            "cost": champion.cost,
            "bag_size": COPIES_PER_CHAMPION[champion.cost],
        }
        for champion in champions
        if champion.cost in COPIES_PER_CHAMPION
    ]
    return {
        "units": sorted(
            units_by_cost,
            key=lambda unit: (unit["cost"], unit["name"]),
        )
    }


async def calculate(request: RolldownRequest) -> dict[str, object]:
    """Calculate a validated rolldown scenario.

    Args:
        request: Validated browser rolldown request.

    Returns:
        Estimated joint and per-target hit distributions.
    """
    return await calculate_rolldown_request(request)


def _exploration_scenario(
    request: RolldownRequest,
    *,
    dimension: RolldownSweepDimension | None = None,
    value: float | None = None,
    level: int | None = None,
    budget: int | None = None,
) -> RolldownRequest:
    """Build one validated scenario from an exploration base request.

    Args:
        request: Base browser rolldown request.
        dimension: Optional sensitivity dimension to override.
        value: Value for the selected sensitivity dimension.
        level: Optional heatmap level override.
        budget: Optional heatmap budget override.

    Returns:
        A validated scenario retaining the base run's trial count.
    """
    payload = request.model_dump()
    payload["include_trials"] = False
    if level is not None:
        payload["level"] = level
    if budget is not None:
        payload["budget"] = budget
    if dimension == "level":
        payload["level"] = int(value)
    elif dimension == "budget":
        payload["budget"] = int(value)
    elif dimension == "pressure":
        payload["pool_pressure"] = float(value) / 100
    elif dimension == "out":
        targets = list(payload["targets"])
        targets[0] = {**targets[0], "copies_out": int(value)}
        payload["targets"] = targets
    return RolldownRequest.model_validate(payload)


def _calculate_exploration(
    request: RolldownRequest,
    levels: list[int],
    budgets: list[int],
    sweep_dimension: RolldownSweepDimension,
    sweep_values: list[float],
    simulations: int,
    champions: list[CDragonChampion],
) -> dict[str, object]:
    """Calculate a heatmap and sweep in one worker with result reuse.

    Args:
        request: Base browser rolldown request.
        levels: Heatmap player levels.
        budgets: Heatmap gold or roll budgets.
        sweep_dimension: Input varied by the one-dimensional sweep.
        sweep_values: Values used for the sweep.
        simulations: Monte Carlo trials per unique scenario.
        champions: Shared current roster snapshot.

    Returns:
        Heatmap probabilities and full sweep results.
    """
    cached_results: dict[str, dict[str, object]] = {}

    def calculate_scenario(scenario: RolldownRequest) -> dict[str, object]:
        """Calculate or reuse one normalized exploration scenario.

        Args:
            scenario: Validated scenario before the exploration trial override.

        Returns:
            Full calculator result for the normalized scenario.
        """
        payload = scenario.model_dump()
        payload.update(
            simulations=simulations,
            include_trials=False,
            trials_sample_cap=0,
        )
        calculation_request = RolldownRequest.model_validate(payload)
        cache_key = calculation_request.model_dump_json()
        if cache_key not in cached_results:
            cached_results[cache_key] = calculate_rolldown_for_roster(
                calculation_request,
                champions,
            )
        return cached_results[cache_key]

    grid = []
    for heatmap_level in levels:
        row = []
        for heatmap_budget in budgets:
            scenario = _exploration_scenario(
                request,
                level=heatmap_level,
                budget=heatmap_budget,
            )
            result = calculate_scenario(scenario)
            row.append(result["probability_find_all_targets"])
        grid.append(row)

    sweep = []
    for sweep_value in sweep_values:
        scenario = _exploration_scenario(
            request,
            dimension=sweep_dimension,
            value=sweep_value,
        )
        sweep.append(
            {
                "v": int(sweep_value) if sweep_value.is_integer() else sweep_value,
                "req": scenario.model_dump(mode="json"),
                "result": calculate_scenario(scenario),
            }
        )
    return {
        "heatmap": {"levels": levels, "budgets": budgets, "grid": grid},
        "sweep": sweep,
        "unique_scenarios": len(cached_results),
    }


async def explore(
    *,
    request: RolldownRequest,
    levels: list[int],
    budgets: list[int],
    sweep_dimension: RolldownSweepDimension,
    sweep_values: list[float],
    simulations: int,
) -> dict[str, object]:
    """Run a browser heatmap and sweep against one roster snapshot.

    Args:
        request: Base browser rolldown request.
        levels: Heatmap player levels.
        budgets: Heatmap gold or roll budgets.
        sweep_dimension: Input varied by the one-dimensional sweep.
        sweep_values: Values used for the sweep.
        simulations: Monte Carlo trials per unique scenario.

    Returns:
        Heatmap probabilities and full sweep results.
    """
    client = CDragon()
    try:
        champions = await load_rolldown_champions(client)
    finally:
        await client.aclose()
    return await asyncio.to_thread(
        _calculate_exploration,
        request,
        levels,
        budgets,
        sweep_dimension,
        sweep_values,
        simulations,
        champions,
    )


def _simulate_scenarios(
    scenarios: list[RolldownScenario],
    champions: list[CDragonChampion],
) -> list[dict[str, object]]:
    """Calculate related scenarios sequentially in one worker thread.

    Args:
        scenarios: Client IDs, labels, groups, and validated requests.
        champions: Current roster shared by every scenario.

    Returns:
        Labeled simulation results in request order.
    """
    return [
        {
            "id": scenario_id,
            "label": label,
            "group": group,
            "result": calculate_rolldown_for_roster(request, champions),
        }
        for scenario_id, label, group, request in scenarios
    ]


async def simulate(scenarios: list[RolldownScenario]) -> dict[str, object]:
    """Run a bounded experiment group against one roster snapshot.

    Args:
        scenarios: Client IDs, labels, groups, and validated requests.

    Returns:
        Labeled simulation results in request order.
    """
    client = CDragon()
    try:
        champions = await load_rolldown_champions(client)
    finally:
        await client.aclose()
    runs = await asyncio.to_thread(_simulate_scenarios, scenarios, champions)
    return {"runs": runs}
