"""Behavioral coverage for native density discovery and frozen HDBSCAN matching."""

import copy
import json

import pytest

from domain.compositions.adapter import deserialize_model, serialize_model
from domain.compositions.algorithms.hdbscan import Adapter
from domain.compositions.distance import board_distance
from domain.compositions.fixtures import fixture_boards
from domain.compositions.models import BoardObservation, EntityRef
from test_contract import exercise_adapter


def test_shared_contract_and_two_anchors():
    """Run the common adapter contract and separate itemized anchors sharing tanks."""
    adapter = Adapter()
    exercise_adapter(adapter)
    result = adapter.fit(fixture_boards(), adapter.Parameters(), 42)
    assert len(result.model.families) == 2
    labels = [assignment.family_id for assignment in result.discovery_assignments]
    assert len(set(labels[:12])) == len(set(labels[12:])) == 1
    assert labels[0] != labels[12]
    assert all(
        assignment.status == "assigned" for assignment in result.discovery_assignments
    )


def test_duplicates_and_harmless_substitution():
    """Retain repeated unit/item instances while accepting a low-investment substitute."""
    boards = fixture_boards()
    adapter = Adapter()
    result = adapter.fit(boards, adapter.Parameters(), 7)
    restored = deserialize_model(serialize_model(result.model))
    original = restored.state["clusters"][0]["references"][0]
    assert original["units"][0]["unit"] == original["units"][2]["unit"]
    assert (
        original["units"][0]["items"][0]["item"]
        == original["units"][0]["items"][1]["item"]
    )
    fewer_copies = boards[0].model_copy(update={"units": boards[0].units[:2]})
    fewer_items = boards[0].model_copy(
        update={
            "units": (
                boards[0]
                .units[0]
                .model_copy(update={"items": boards[0].units[0].items[:1]}),
            )
            + boards[0].units[1:]
        }
    )
    assert board_distance(boards[0], fewer_copies) > 0
    assert board_distance(boards[0], fewer_items) > 0
    substitute = boards[1].model_copy(
        update={
            "observation_id": "substitute",
            "units": boards[1].units[:2]
            + (
                boards[1]
                .units[2]
                .model_copy(update={"unit": EntityRef(key="Nami", name="Nami")}),
            ),
        }
    )
    assert (
        adapter.classify((substitute,), restored)[0].family_id
        == result.discovery_assignments[1].family_id
    )


def test_changed_itemized_anchor_changes_family():
    """Preserve a shared frontline while changing the carry and its bound items."""
    boards = fixture_boards()
    adapter = Adapter()
    result = adapter.fit(boards, adapter.Parameters(), 1)
    changed = boards[1].model_copy(
        update={
            "observation_id": "changed-anchor",
            "units": (boards[13].units[0],) + boards[1].units[1:],
        }
    )
    assert changed.units[1:] == boards[1].units[1:]
    classified = adapter.classify((boards[1], changed), result.model)
    assert classified[0].family_id != classified[1].family_id
    assert classified[1].family_id == result.discovery_assignments[13].family_id


def test_native_noise_remains_distinct_from_frozen_classification():
    """Show density noise can later match under an explicitly loose frozen threshold."""
    boards = fixture_boards()
    noise = boards[0].model_copy(
        update={"observation_id": "noise", "traits": (), "units": tuple(
            boards[0].units[2].model_copy(update={"occurrence_index": i}) for i in range(8)
        )}
    )
    adapter = Adapter()
    result = adapter.fit(boards + (noise,), adapter.Parameters(rejection_distance=10), 9)
    assert result.discovery_assignments[-1].status == "unclassified"
    assert "Native HDBSCAN noise" in result.discovery_assignments[-1].explanation
    assert adapter.classify((noise,), result.model)[0].status == "assigned"
    assert result.model.state["noise_observation_ids"] == ["noise"]
    panels = {panel.panel_id: panel for panel in result.diagnostics.panels}
    assert panels["noise"].data["noise_count"] == 1
    assert len(panels["persistence"].data["rows"]) == 2
    assert (
        "not HDBSCAN approximate_predict" in panels["classification-policy"].description
    )
    json.dumps(result.diagnostics.model_dump(mode="json"), allow_nan=False)


def test_ambiguity_and_rejection():
    """Retain two tied structural candidates and reject distant unknown structures."""
    boards = fixture_boards()
    midpoint = boards[1].model_copy(
        update={
            "observation_id": "midpoint",
            "units": boards[1].units
            + (boards[13].units[0].model_copy(update={"occurrence_index": 3}),),
        }
    )
    unknown = boards[1].model_copy(
        update={
            "observation_id": "unknown",
            "traits": (),
            "units": (
                boards[1]
                .units[1]
                .model_copy(update={"unit": EntityRef(key="Alien", name="Alien")}),
            ),
        }
    )
    adapter = Adapter()
    result = adapter.fit(boards, adapter.Parameters(rejection_distance=1.5), 0)
    ambiguous, rejected = adapter.classify((midpoint, unknown), result.model)
    assert ambiguous.status == "ambiguous" and ambiguous.family_id is None
    assert len(ambiguous.candidates) == 2
    assert ambiguous.candidates[0].score.value == ambiguous.candidates[1].score.value
    assert rejected.status == "unclassified"


def test_empty_small_and_incomplete_observations():
    """Handle no sample, inadequate density evidence, and missing-unit observations."""
    adapter = Adapter()
    empty = BoardObservation(observation_id="empty", level=None, units=(), traits=())
    for boards in ((), (empty,), fixture_boards()[:1]):
        result = adapter.fit(boards, adapter.Parameters(), 0)
        assert not result.model.families
        assert len(result.discovery_assignments) == len(boards)
        assert all(a.status == "unclassified" for a in result.discovery_assignments)
        assert adapter.classify((empty,), result.model)[0].status == "unclassified"
    boards = fixture_boards()
    incomplete = boards[1].model_copy(
        update={"observation_id": "incomplete", "level": None, "traits": ()}
    )
    result = adapter.fit(boards + (empty,), adapter.Parameters(), 0)
    assert result.discovery_assignments[-1].status == "unclassified"
    assert adapter.classify((incomplete,), result.model)[0].status == "assigned"
    assert adapter.classify((empty,), result.model)[0].status == "unclassified"


def test_seed_determinism_input_order_and_roundtrip():
    """Use stable tie ordering, preserve result order, and reconstruct from JSON alone."""
    adapter = Adapter()
    boards = fixture_boards()
    first = adapter.fit(boards, adapter.Parameters(), 12)
    second = adapter.fit(tuple(reversed(boards)), adapter.Parameters(), 12)
    assert serialize_model(first.model) == serialize_model(second.model)
    assert [a.observation_id for a in second.discovery_assignments] == [
        b.observation_id for b in reversed(boards)
    ]
    different_seed = adapter.fit(boards, adapter.Parameters(), 99)
    assert first.model.families == different_seed.model.families
    restored = deserialize_model(serialize_model(first.model))
    assert adapter.classify(boards, restored) == adapter.classify(boards, first.model)
    assert set(restored.effective_parameters) == set(adapter.Parameters.model_fields)


@pytest.mark.parametrize(
    "update",
    [
        {"algorithm_id": "other"},
        {"algorithm_version": "999"},
        {"feature_revision": "structure.v2"},
        {"schema_version": "adapter.v2"},
    ],
)
def test_incompatible_envelope_rejected(update):
    """Reject foreign envelopes even when a caller bypasses Pydantic construction."""
    adapter = Adapter()
    model = adapter.fit(fixture_boards(), adapter.Parameters(), 0).model.model_copy(
        update=update
    )
    with pytest.raises(ValueError, match="incompatible"):
        adapter.classify((), model)


@pytest.mark.parametrize(
    "corruption",
    [
        "extra",
        "version",
        "references",
        "family",
        "representative",
        "threshold",
        "persistence",
    ],
)
def test_corrupt_state_rejected(corruption):
    """Refuse unknown fields and damaged family/reference or threshold contracts."""
    adapter = Adapter()
    model = adapter.fit(fixture_boards(), adapter.Parameters(), 0).model
    state = copy.deepcopy(model.state)
    if corruption == "extra":
        state["unrecognized"] = True
    elif corruption == "version":
        state["state_version"] = "hdbscan.references.v2"
    elif corruption == "references":
        state["clusters"][0]["references"] = []
    elif corruption == "family":
        state["clusters"][0]["family_id"] = "missing"
    elif corruption == "persistence":
        state["clusters"][0]["persistence"] = float("nan")
    elif corruption == "representative":
        state["clusters"][0]["references"] = [
            b
            for b in state["clusters"][0]["references"]
            if b["observation_id"]
            not in model.families[0].representative_observation_ids
        ]
    elif corruption == "threshold":
        effective = dict(model.effective_parameters)
        del effective["ambiguity_margin"]
        model = model.model_copy(update={"effective_parameters": effective})
    with pytest.raises(ValueError):
        adapter.classify((), model.model_copy(update={"state": state}))


@pytest.mark.parametrize(
    "settings",
    [
        {"min_cluster_size": 1},
        {"min_samples": 0},
        {"min_samples": 2.5},
        {"rejection_distance": float("inf")},
        {"ambiguity_margin": -0.1},
        {"unexpected": True},
    ],
)
def test_parameters_reject_invalid_settings(settings):
    """Require valid explicit density controls and finite matching thresholds."""
    with pytest.raises(ValueError):
        Adapter.Parameters(**settings)


def test_explicit_density_requirements_and_identical_boards():
    """Honor minimum density controls and serialize zero-distance cluster diagnostics."""
    adapter = Adapter()
    boards = fixture_boards()
    result = adapter.fit(boards, adapter.Parameters(min_cluster_size=25), 0)
    assert not result.model.families
    assert all(a.status == "unclassified" for a in result.discovery_assignments)
    result = adapter.fit(boards, adapter.Parameters(min_samples=24), 0)
    assert not result.model.families
    identical = tuple(
        boards[0].model_copy(update={"observation_id": f"identical-{i}"})
        for i in range(8)
    )
    result = adapter.fit(identical, adapter.Parameters(allow_single_cluster=True), 0)
    assert len(result.model.families) == 1
    assert all(a.status == "assigned" for a in result.discovery_assignments)
    assert adapter.classify(
        identical, deserialize_model(serialize_model(result.model))
    ) == adapter.classify(identical, result.model)
    json.dumps(result.diagnostics.model_dump(mode="json"), allow_nan=False)


def test_duplicate_discovery_identity_rejected():
    """Refuse ambiguous snapshot identity before density discovery."""
    board = fixture_boards()[0]
    with pytest.raises(ValueError, match="unique observation IDs"):
        Adapter().fit((board, board), Adapter.Parameters(), 0)
