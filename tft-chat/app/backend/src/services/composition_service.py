"""Application-facing entry points for the private compositions workspace.

This module gives routes and the FastAPI lifecycle one stable service boundary
while keeping implementation details grouped under ``services.compositions``.
"""

from services.compositions.display import (
    compare_experiments,
    composition_detail,
    composition_list,
    inspect_board,
)
from services.compositions.execution import execute_snapshot
from services.compositions.fixtures import fixture_detail, fixture_list
from services.compositions.persistence import (
    cancel_experiment,
    create_experiment,
    get_experiment,
    history,
    rerun_experiment,
)
from services.compositions.source import source_summary
from services.compositions.worker import CompositionWorker
from domain.compositions.registry import ALGORITHM_IDS, get_adapter


__all__ = [
    "ALGORITHM_IDS",
    "CompositionWorker",
    "cancel_experiment",
    "compare_experiments",
    "composition_detail",
    "composition_list",
    "create_experiment",
    "execute_snapshot",
    "fixture_detail",
    "fixture_list",
    "get_adapter",
    "get_experiment",
    "history",
    "inspect_board",
    "rerun_experiment",
    "source_summary",
]
