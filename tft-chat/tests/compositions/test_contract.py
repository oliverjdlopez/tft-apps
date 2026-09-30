"""Shared adapter and wire invariants required before dispatching algorithms."""

import json
import pytest
from domain.compositions.adapter import serialize_model, deserialize_model
from domain.compositions.fixtures import fixture_boards
from domain.compositions.reference import ReferenceAdapter
from domain.compositions.utils import validate_references
from services.compositions.fixtures import fixture_detail


def exercise_adapter(adapter):
    """Require deterministic JSON round trips, outcomes exclusion, and valid references."""
    boards = fixture_boards()
    parameters = adapter.Parameters()
    fit = adapter.fit(boards, parameters, 42)
    validate_references(boards, fit.model.families, fit.discovery_assignments)
    restored = deserialize_model(serialize_model(fit.model))
    assert adapter.classify(boards, restored) == adapter.classify(boards, fit.model)
    assert serialize_model(
        adapter.fit(boards, parameters, 42).model
    ) == serialize_model(fit.model)
    assert "placement" not in json.dumps([b.model_dump(mode="json") for b in boards])
    json.dumps(fit.diagnostics.model_dump(mode="json"), allow_nan=False)
    assert len(adapter.classify((), restored)) == 0


def test_reference_adapter_contract():
    """Freeze the minimal working contract before algorithm implementations begin."""
    exercise_adapter(ReferenceAdapter())


def test_display_roundtrip_and_duplicates():
    """Validate duplicate champions/items and unknown fields in HTTP models."""
    detail = fixture_detail()
    assert type(detail).model_validate_json(detail.model_dump_json()) == detail
    board = detail.examples[0].board
    assert board.units[0].unit == board.units[2].unit
    assert board.units[0].items[0].item == board.units[0].items[1].item
    assert board.traits[-1].tier_current is None
    with pytest.raises(ValueError):
        type(detail).model_validate({**detail.model_dump(), "scope_id": 1})


def test_hdbscan_adapter_contract():
    """Apply the frozen adapter contract to the sole production algorithm."""
    from domain.compositions.registry import get_adapter

    exercise_adapter(get_adapter("hdbscan"))
