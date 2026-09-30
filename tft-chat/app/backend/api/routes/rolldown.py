"""Rolldown explorer HTTP routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain.tools.rolldown import (
    RolldownRequest,
    RolldownRunParameters,
    RolldownTargetDefinition,
)
from services import rolldown_service

router = APIRouter(prefix="/api/rolldown", tags=["rolldown"])


class RolldownExperimentScenario(BaseModel):
    """One labeled scenario in a browser exploration batch."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    group: str = Field(min_length=1, max_length=80)
    request: RolldownRequest


class RolldownExperimentRequest(BaseModel):
    """A bounded group of related rolldown scenarios."""

    model_config = ConfigDict(extra="forbid")

    scenarios: list[RolldownExperimentScenario] = Field(min_length=1, max_length=12)


class RolldownExplorationRequest(BaseModel):
    """A bounded heatmap and one-dimensional sensitivity calculation."""

    model_config = ConfigDict(extra="forbid")

    request: RolldownRequest
    levels: list[int] = Field(default=[5, 6, 7, 8, 9, 10], min_length=1, max_length=10)
    budgets: list[int] = Field(min_length=1, max_length=10)
    sweep_dimension: Literal["budget", "level", "out", "pressure"]
    sweep_values: list[float] = Field(min_length=1, max_length=10)
    simulations: int = Field(default=800, ge=800, le=2_000)

    @model_validator(mode="after")
    def validate_exploration_grid(self) -> "RolldownExplorationRequest":
        """Validate dimension-specific values and total calculation count.

        Returns:
            The validated exploration request.
        """
        if len(set(self.levels)) != len(self.levels):
            raise ValueError("levels must be unique")
        if any(level < 1 or level > 10 for level in self.levels):
            raise ValueError("levels must be between 1 and 10")
        if len(set(self.budgets)) != len(self.budgets):
            raise ValueError("budgets must be unique")
        maximum_budget = 100 if self.request.budget_type == "rolls" else 200
        if any(budget < 1 or budget > maximum_budget for budget in self.budgets):
            raise ValueError(f"budgets must be between 1 and {maximum_budget}")
        if len(self.levels) * len(self.budgets) + len(self.sweep_values) > 48:
            raise ValueError("exploration requests cannot exceed 48 scenarios")

        integral_dimensions = {"budget", "level", "out"}
        if self.sweep_dimension in integral_dimensions and any(
            not value.is_integer() for value in self.sweep_values
        ):
            raise ValueError(f"{self.sweep_dimension} sweep values must be integers")
        bounds = {
            "budget": (1, maximum_budget),
            "level": (1, 10),
            "out": (0, 29),
            "pressure": (0, 100),
        }
        lower, upper = bounds[self.sweep_dimension]
        if any(value < lower or value > upper for value in self.sweep_values):
            raise ValueError(
                f"{self.sweep_dimension} sweep values must be between {lower} and {upper}"
            )
        return self


class RolldownRunSweep(BaseModel):
    """Optional target-independent comparison sweep prepared with a run set."""

    model_config = ConfigDict(extra="forbid")

    dimension: Literal["budget", "level", "pressure"]
    values: list[float] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> "RolldownRunSweep":
        """Validate unique, bounded values for the selected run dimension.

        Returns:
            The validated run sweep.
        """
        if len(set(self.values)) != len(self.values):
            raise ValueError("sweep values must be unique")
        if self.dimension in {"budget", "level"} and any(
            not value.is_integer() for value in self.values
        ):
            raise ValueError(f"{self.dimension} sweep values must be integers")
        bounds = {"budget": (1, 200), "level": (1, 10), "pressure": (0, 100)}
        lower, upper = bounds[self.dimension]
        if any(value < lower or value > upper for value in self.values):
            raise ValueError(
                f"{self.dimension} sweep values must be between {lower} and {upper}"
            )
        return self


class RolldownRunBatchRequest(BaseModel):
    """Target-free parameters used to prepare one reusable run set."""

    model_config = ConfigDict(extra="forbid")

    parameters: RolldownRunParameters
    sweep: RolldownRunSweep | None = None
    sweeps: list[RolldownRunSweep] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def validate_roll_sweep(self) -> "RolldownRunBatchRequest":
        """Validate one or two distinct sweeps and refresh-count bounds.

        Returns:
            The validated run batch.
        """
        if self.sweep is not None and self.sweeps:
            raise ValueError("use either sweep or sweeps, not both")
        effective_sweeps = self.sweeps or ([self.sweep] if self.sweep else [])
        dimensions = [sweep.dimension for sweep in effective_sweeps]
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("sweep dimensions must be distinct")
        if self.parameters.budget_type == "rolls":
            for sweep in effective_sweeps:
                if sweep.dimension == "budget" and any(
                    value > 100 for value in sweep.values
                ):
                    raise ValueError("roll budget sweep values cannot exceed 100")
        return self

    def effective_sweeps(self) -> list[RolldownRunSweep]:
        """Return the normalized sweep list, including the legacy singular field.

        Returns:
            Zero, one, or two validated sweep definitions.
        """
        return self.sweeps or ([self.sweep] if self.sweep else [])


class RolldownPreparedAnalysisRequest(BaseModel):
    """A post-run target query over selected prepared runs."""

    model_config = ConfigDict(extra="forbid")

    run_set_id: str = Field(min_length=1, max_length=80)
    run_ids: list[str] = Field(min_length=1)
    target: RolldownTargetDefinition

    @model_validator(mode="after")
    def validate_run_ids(self) -> "RolldownPreparedAnalysisRequest":
        """Reject repeated run identities in a comparison request.

        Returns:
            The validated analysis request.
        """
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("run_ids must be unique")
        return self


@router.get("/units")
async def rolldown_units() -> dict[str, object]:
    """Return current normal-shop champions for rolldown input controls."""
    return await rolldown_service.units()


@router.post("/runs")
async def rolldown_prepare_runs(body: RolldownRunBatchRequest) -> dict[str, object]:
    """Prepare target-independent runs and reusable random trial samples."""
    sweeps = [
        (sweep.dimension, sweep.values) for sweep in body.effective_sweeps()
    ]
    try:
        return await rolldown_service.prepare_runs(
            base=body.parameters,
            sweeps=sweeps,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.post("/runs/analyze")
async def rolldown_analyze_runs(
    body: RolldownPreparedAnalysisRequest,
) -> dict[str, object]:
    """Evaluate a new target rule across selected prepared runs."""
    try:
        return await rolldown_service.analyze_prepared_runs(
            run_set_id=body.run_set_id,
            run_ids=body.run_ids,
            definition=body.target,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.post("/calculate")
async def rolldown_calculate(body: RolldownRequest) -> dict[str, object]:
    """Calculate one browser rolldown scenario with actionable errors."""
    try:
        return await rolldown_service.calculate(body)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.post("/explore")
async def rolldown_explore(body: RolldownExplorationRequest) -> dict[str, object]:
    """Calculate one heatmap and sweep against a shared roster snapshot."""
    try:
        return await rolldown_service.explore(
            request=body.request,
            levels=body.levels,
            budgets=body.budgets,
            sweep_dimension=body.sweep_dimension,
            sweep_values=body.sweep_values,
            simulations=body.simulations,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.post("/simulate")
async def rolldown_simulate(body: RolldownExperimentRequest) -> dict[str, object]:
    """Run a labeled group of scenarios against one current roster."""
    scenarios = [
        (scenario.id, scenario.label, scenario.group, scenario.request)
        for scenario in body.scenarios
    ]
    try:
        return await rolldown_service.simulate(scenarios)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
