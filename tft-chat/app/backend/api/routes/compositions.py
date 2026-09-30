"""Opt-in developer-only composition HTTP endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from core.config import load_config
from services.compositions.models import (
    CompositionListResponse,
    CompositionDetailResponse,
)
from typing import Literal
from services.compositions.models import (
    ExperimentRequest,
    ExperimentView,
    ExperimentHistory,
    AlgorithmList,
    AlgorithmView,
    ComparisonResponse,
    BoardExampleView,
)
from services.compositions.models import SourceSummary
from services.composition_service import (
    cancel_experiment,
    compare_experiments,
    composition_detail,
    composition_list,
    create_experiment as create_experiment_service,
    fixture_detail,
    fixture_list,
    get_adapter,
    get_experiment,
    history,
    inspect_board,
    rerun_experiment,
    source_summary,
)


def require_workbench():
    """Reject every private endpoint when the UI feature is disabled."""
    if not load_config().chat.composition_workbench:
        raise HTTPException(404, "Composition workbench is disabled")


router = APIRouter(
    prefix="/api/developer/compositions", dependencies=[Depends(require_workbench)]
)


@router.get("/fixtures", response_model=CompositionListResponse)
def list_fixtures():
    """Display fixture families without any database dependency."""
    return fixture_list()


@router.get("/fixtures/{family_id}", response_model=CompositionDetailResponse)
def detail_fixture(family_id: str):
    """Display a known illustrative fixture with occurrence-level equipment."""
    detail = fixture_detail()
    if detail.family.family_id != family_id:
        raise HTTPException(404, "Unknown fixture family")
    return detail


def service_call(operation, *args):
    """Convert private implementation failures into credential-safe HTTP errors."""
    try:
        return operation(*args)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, ImportError) as error:
        if isinstance(error, ImportError):
            raise HTTPException(
                503,
                "Install the compositions optional dependencies and restart the backend.",
            ) from error
        raise HTTPException(422, str(error)) from error
    except Exception as error:
        import logging

        logging.getLogger(__name__).exception("Composition service failed")
        raise HTTPException(
            503,
            "Composition storage or source facts are unavailable. Check the backend log.",
        ) from error


@router.get("/algorithms", response_model=AlgorithmList)
def algorithms():
    """Return the sole supported discovery algorithm's parameter form."""

    def describe():
        """Load HDBSCAN inside the shared safe error boundary."""
        return AlgorithmList(
            algorithms=tuple(
                AlgorithmView(
                    algorithm_id=a.algorithm_id,
                    algorithm_version=a.algorithm_version,
                    parameter_schema=a.Parameters.model_json_schema(),
                )
                for a in (get_adapter("hdbscan"),)
            )
        )

    return service_call(describe)


@router.get("/experiments", response_model=ExperimentHistory)
def experiments():
    """List persisted run summaries for reopening and comparison."""
    return service_call(history)


@router.post("/experiments", response_model=ExperimentView)
def create_experiment(request: ExperimentRequest):
    """Capture or reuse inputs and enqueue one immutable experiment."""
    return service_call(create_experiment_service, request)


@router.get("/experiments/{experiment_id}", response_model=ExperimentView)
def experiment(experiment_id: str):
    """Poll persistent stage, elapsed time, errors, and frozen results."""
    return service_call(get_experiment, experiment_id)


@router.post("/experiments/{experiment_id}/cancel", response_model=ExperimentView)
def cancel(experiment_id: str):
    """Cancel pending or active work without modifying completed results."""
    return service_call(cancel_experiment, experiment_id)


@router.post("/experiments/{experiment_id}/rerun", response_model=ExperimentView)
def rerun(experiment_id: str):
    """Append a run reusing the exact saved input snapshot and effective settings."""
    return service_call(rerun_experiment, experiment_id)


@router.get(
    "/experiments/{experiment_id}/families", response_model=CompositionListResponse
)
def families(
    experiment_id: str,
    population: Literal["discovery_sample", "full_population"] = "discovery_sample",
):
    """Browse prevalence with an explicit sample or population denominator."""
    return service_call(composition_list, experiment_id, population)


@router.get(
    "/experiments/{experiment_id}/families/{family_id}",
    response_model=CompositionDetailResponse,
)
def family(
    experiment_id: str,
    family_id: str,
    population: Literal["discovery_sample", "full_population"] = "discovery_sample",
):
    """Inspect verified joint structures, representative examples, and outcomes."""
    return service_call(
        composition_detail, experiment_id, population, family_id
    )


@router.get(
    "/experiments/{experiment_id}/boards/{observation_id}",
    response_model=BoardExampleView,
)
def board(
    experiment_id: str,
    observation_id: str,
    population: Literal["discovery_sample", "full_population"] = "discovery_sample",
):
    """Inspect evidence including rejection reasons for unclassified observations."""
    return service_call(
        inspect_board, experiment_id, population, observation_id
    )


@router.get("/compare", response_model=ComparisonResponse)
def compare(
    left: str,
    right: str,
    population: Literal["discovery_sample", "full_population"] = "discovery_sample",
):
    """Compare saved configuration and assignment overlap without refitting."""
    return service_call(compare_experiments, left, right, population)


@router.get("/source", response_model=SourceSummary)
def source_status(source: Literal["active", "fixture"] = "active"):
    """Inspect readiness and source context before creating an input snapshot."""
    return source_summary(source)
