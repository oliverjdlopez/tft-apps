"""Contract tests for backend-owned evidence and reference-only presentation."""

import asyncio
import base64
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from agents.tool_context import ToolContext

from domain.tools import get_tool, _ensure_sdk_tool
from domain.tools.evidence.models import DisplaySpec, EvidenceStore
from domain.tools.evidence.utils import capture_evidence, resolve_presentation
from services.streaming import (
    stream_agent_events,
    STREAM_EVENT_PREFIX,
    STREAM_EVENT_SUFFIX,
)


@pytest.fixture
def ranking():
    """Supply a partial public ranking containing precision and an excluded ID."""
    return {
        "kind": "table",
        "context": {
            "population": "All eligible boards",
            "population_boards": 1000,
            "group_by": ["unit_name"],
            "sort": [{"metric": "games", "direction": "desc"}],
            "minimum_reportable_boards": 10,
        },
        "results": [
            {
                "unit_name": "Jinx",
                "games": 125,
                "avg_placement": Decimal("3.4567"),
                "top4_rate": Decimal("0.6251"),
                "scope_id": "private",
                "delta": None,
            }
        ],
        "page": {"offset": 5, "count": 1, "has_more": True},
        "warnings": [{"code": "sample", "message": "An observational ranking."}],
    }


def specification(ref, **changes):
    """Construct an editorial selection without including numerical values."""
    return DisplaySpec(
        evidence_ref=ref,
        dataset_ref="rows",
        kind="interactive_table",
        title="Unit outcomes",
        columns=["unit_name", "games", "top4_rate"],
        **changes,
    )


def context(store, name, call_id):
    """Create separate SDK wrappers sharing the invocation's evidence store."""
    return ToolContext(
        context=store, tool_name=name, tool_call_id=call_id, tool_arguments="{}"
    )


def test_precise_evidence_and_source_are_separate_from_editorial_choices(ranking):
    """Preserve authoritative numbers, page coverage, nulls, and safe fields."""
    store = EvidenceStore()
    reference = capture_evidence(store, "rank_units", ranking)
    bundle = store.bundles[reference["evidence_ref"]]
    dataset = bundle.datasets[0]
    assert dataset.rows[0].values["top4_rate"] == 0.6251
    assert dataset.rows[0].values["avg_placement"] == 3.4567
    assert dataset.rows[0].values["delta"] is None
    assert "private" not in bundle.model_dump_json()
    assert dataset.page.offset == 5 and dataset.page.has_more
    assert bundle.warnings[0].code == "sample"
    presentation = resolve_presentation(
        store,
        specification(bundle.ref, group_by="unit_name", primary_metric="top4_rate"),
        "present",
    )
    assert presentation.bundle == bundle
    assert "values" not in presentation.display.model_dump_json()


@pytest.mark.parametrize(
    "changes",
    [
        {"columns": ["scope_id"]},
        {"columns": ["games", "games"]},
        {"sort_by": "avg_placement"},
        {"primary_metric": "unit_name"},
        {"group_by": "games"},
        {"kind": "distribution"},
        {"dataset_ref": "missing"},
    ],
)
def test_rejects_incompatible_editorial_choices(ranking, changes):
    """Reject fields, display types, and grouping outside the evidence contract."""
    store = EvidenceStore()
    ref = capture_evidence(store, "rank_units", ranking)["evidence_ref"]
    data = specification(ref).model_dump() | changes
    with pytest.raises(ValueError):
        resolve_presentation(store, DisplaySpec.model_validate(data), "present")


def test_unknown_reference_and_second_surface_are_rejected(ranking):
    """Keep references local and allow only one successful initial display."""
    store = EvidenceStore()
    ref = capture_evidence(store, "rank_units", ranking)["evidence_ref"]
    with pytest.raises(ValueError, match="Unknown evidence"):
        resolve_presentation(EvidenceStore(), specification(ref), "other")
    resolve_presentation(store, specification(ref), "one")
    with pytest.raises(ValueError, match="One initial"):
        resolve_presentation(store, specification(ref), "two")


def test_empty_and_capped_rankings_preserve_coverage(ranking):
    """Empty results stay renderable and presentation bounds never imply completeness."""
    store = EvidenceStore()
    ranking["results"] = []
    ref = capture_evidence(store, "rank_units", ranking)["evidence_ref"]
    assert store.bundles[ref].datasets[0].rows == ()
    ranking["results"] = [{"unit_name": "Jinx", "games": 10}] * 201
    ranking["page"]["has_more"] = False
    ref = capture_evidence(store, "rank_units", ranking)["evidence_ref"]
    dataset = store.bundles[ref].datasets[0]
    assert len(dataset.rows) == 200 and dataset.page.has_more


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 62.5, True])
def test_invalid_rates_do_not_register_evidence(ranking, value):
    """Never guess percentage points or expose non-finite presentation values."""
    ranking["results"][0]["top4_rate"] = value
    store = EvidenceStore()
    assert capture_evidence(store, "rank_units", ranking) is None
    assert not store.bundles


def comparison():
    """Return a reportable target distribution and a suppressed baseline."""
    return {
        "kind": "comparison",
        "context": {"minimum_reportable_boards": 10},
        "target": {
            "label": "Target",
            "boards": 28,
            "suppressed": False,
            "histogram": {str(i): i - 1 for i in range(1, 9)},
        },
        "baseline": {"label": "Baseline", "boards": None, "suppressed": True},
        "effects": [],
        "overlap": {"boards": None, "suppressed": True},
        "warnings": [],
    }


def test_distribution_separates_populations_and_preserves_zero_and_suppression():
    """Keep suppressed populations distinct from explicitly reported zero counts."""
    store = EvidenceStore()
    ref = capture_evidence(store, "compare_cohorts", comparison())["evidence_ref"]
    target, baseline = store.bundles[ref].datasets
    assert target.bins[0].count == 0 and sum(item.count for item in target.bins) == 28
    assert baseline.unavailable and baseline.bins == () and baseline.boards is None
    spec = DisplaySpec(
        evidence_ref=ref, dataset_ref="target", kind="distribution", title="Placements"
    )
    assert resolve_presentation(store, spec, "call").display.kind == "distribution"
    bad = comparison()
    del bad["target"]["histogram"]["1"]
    assert capture_evidence(EvidenceStore(), "compare_cohorts", bad) is None


def test_registered_tool_capture_handoff_and_stream_preserve_precision(ranking):
    """Exercise SDK wrappers through a responder call and resolved stream event."""

    async def run():
        """Use one store across distinct analytical and responder tool contexts."""
        store = EvidenceStore()

        async def analytical(ctx, payload):
            """Stand in for the completed bounded database operation."""
            return ranking

        tool = _ensure_sdk_tool(
            SimpleNamespace(
                name="rank_units", on_invoke_tool=analytical, params_json_schema={}
            )
        )
        output = await tool.on_invoke_tool(context(store, "rank_units", "rank"), "{}")
        assert output["results"][0]["top4_rate"] == 0.63
        ref = output["evidence"]["evidence_ref"]
        spec = specification(ref)
        ack = await get_tool("present_evidence").on_invoke_tool(
            context(store, "present_evidence", "view"),
            json.dumps({"request": spec.model_dump()}),
        )
        assert ack["presented"] and "bundle" not in ack

        class Events:
            """Provide the SDK presentation call/output pair to the stream adapter."""

            async def stream_events(self):
                """Emit arguments and acknowledgement, with no numerical payload."""
                yield SimpleNamespace(
                    type="run_item_stream_event",
                    name="tool_called",
                    item=SimpleNamespace(
                        raw_item=SimpleNamespace(
                            name="present_evidence",
                            call_id="view",
                            arguments=json.dumps({"request": spec.model_dump()}),
                        )
                    ),
                )
                yield SimpleNamespace(
                    type="run_item_stream_event",
                    name="tool_output",
                    item=SimpleNamespace(call_id="view", output=ack),
                )

        events = []
        async for frame in stream_agent_events(
            Events(),
            tools_by_name={},
            request_id="request",
            trace_id="trace",
            evidence_store=store,
        ):
            events.append(
                json.loads(
                    base64.b64decode(
                        frame.strip()[
                            len(STREAM_EVENT_PREFIX) : -len(STREAM_EVENT_SUFFIX)
                        ]
                    )
                )
            )
        assert events[0]["type"] == "presentation"
        assert (
            events[0]["presentation"]["bundle"]["datasets"][0]["rows"][0]["values"][
                "top4_rate"
            ]
            == 0.6251
        )
        assert events[1]["type"] == "tool"

    asyncio.run(run())


@pytest.mark.parametrize("tier", ["Bronze", "Silver", "Unique", "Gold", "Prismatic", "All"])
def test_trait_medals_survive_evidence_capture(ranking, tier: str) -> None:
    """Preserve medal labels when ranking results enter the evidence display.

    Args:
        ranking: Public ranking fixture with population and pagination metadata.
        tier: Named medal or rollup label returned by the ranking tool.
    """
    ranking["results"] = [{"trait_name": "TFT18_Fae", "tier": tier, "games": 125}]
    ranking["context"]["group_by"] = ["trait_name", "tier"]
    store = EvidenceStore()
    reference = capture_evidence(store, "rank_traits", ranking)
    bundle = store.bundles[reference["evidence_ref"]]
    dataset = bundle.datasets[0]
    assert dataset.rows[0].values["tier"] == tier
    field = next(field for field in dataset.fields if field.key == "tier")
    assert field.unit == "text" and field.groupable
    presentation = resolve_presentation(store, DisplaySpec(
        evidence_ref=bundle.ref, dataset_ref="rows", kind="interactive_table",
        title="Trait outcomes", columns=["trait_name", "tier", "games"],
        group_by="tier", primary_metric="games",
    ), "present")
    assert presentation.bundle == bundle
