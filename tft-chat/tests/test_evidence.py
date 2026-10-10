"""Contract tests for backend-owned evidence and reference-only presentation."""

import asyncio
import base64
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from agents.tool_context import ToolContext

from domain.assistants.constants import AssistantName
from domain.runtime.models import AssistantRunContext, RuntimeSettings
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
    target, baseline = store.bundles[ref].datasets[:2]
    assert target.bins[0].count == 0 and sum(item.count for item in target.bins) == 28
    assert baseline.unavailable and baseline.bins == () and baseline.boards is None
    spec = DisplaySpec(
        evidence_ref=ref, dataset_ref="target", kind="distribution", title="Placements"
    )
    assert resolve_presentation(store, spec, "call").display.kind == "distribution"
    bad = comparison()
    del bad["target"]["histogram"]["1"]
    assert capture_evidence(EvidenceStore(), "compare_cohorts", bad) is None


def cohort_table():
    """Supply holder-bound cohort rows with public grouping and precise rates."""
    return {
        "kind": "table",
        "context": {
            "population": "Boards containing Nidalee",
            "population_boards": 1000,
            "group_by": ["unit_name", "unit_star_level", "item_name"],
            "sort": [{"metric": "distinct_boards", "direction": "desc"}],
            "minimum_reportable_boards": 50,
        },
        "results": [{
            "unit_name": "Nidalee", "unit_star_level": 2,
            "item_name": "Blue Buff", "distinct_boards": 125,
            "distinct_lobbies": 100, "avg_placement": Decimal("3.4567"),
            "top4_rate": Decimal("0.6251"), "win_rate": None,
            "pick_rate": Decimal("0.125"), "board_key": "private-board",
        }],
        "page": {"offset": 20, "count": 1, "has_more": True},
        "warnings": [{"code": "observational", "message": "Final boards only."}],
    }


def test_cohort_table_preserves_grouping_precision_coverage_and_public_fields():
    """Present actual grouped rows with no inferred aggregation or private keys."""
    store = EvidenceStore()
    reference = capture_evidence(store, "query_cohort", cohort_table())
    bundle = store.bundles[reference["evidence_ref"]]
    dataset = bundle.datasets[0]
    assert dataset.rows[0].values["top4_rate"] == 0.6251
    assert dataset.rows[0].values["win_rate"] is None
    assert dataset.page.offset == 20 and dataset.page.has_more
    assert dataset.source_sort == ("distinct_boards desc",)
    assert "private-board" not in bundle.model_dump_json()
    assert bundle.population_boards == 1000
    assert bundle.warnings[0].code == "observational"
    spec = DisplaySpec(
        evidence_ref=bundle.ref, dataset_ref="rows", kind="interactive_table",
        title="Nidalee holders", columns=["unit_name", "unit_star_level", "item_name", "distinct_boards", "top4_rate"],
        primary_metric="top4_rate", group_by="unit_name",
    )
    assert resolve_presentation(store, spec, "cohort-view").bundle == bundle


@pytest.mark.parametrize(
    "dimension,value,unit",
    [
        ("unit_loadout_key", "Blue Buff|Jeweled Gauntlet", "text"),
        ("trait_tier", "Silver", "text"),
        ("region", "NA", "text"),
        ("platform", "NA1", "text"),
        ("unit_item_count", 3, "count"),
    ],
)
def test_cohort_dimensions_keep_backend_field_semantics(dimension, value, unit):
    """Retain categorical labels and counts in approved cohort dimensions."""
    result = cohort_table()
    result["context"]["group_by"] = [dimension]
    result["results"][0][dimension] = value
    store = EvidenceStore()
    reference = capture_evidence(store, "query_cohort", result)
    dataset = store.bundles[reference["evidence_ref"]].datasets[0]
    assert dataset.rows[0].values[dimension] == value
    assert dataset.fields[0].unit == unit and dataset.fields[0].groupable


@pytest.mark.parametrize(
    "field,value",
    [("distinct_boards", None), ("distinct_boards", 49), ("distinct_boards", True),
     ("top4_rate", 62.5), ("avg_placement", float("nan"))],
)
def test_malformed_or_unreportable_cohort_rows_do_not_register(field, value):
    """Reject incomplete samples and invalid metrics without inventing evidence."""
    result = cohort_table()
    result["results"][0][field] = value
    store = EvidenceStore()
    assert capture_evidence(store, "query_cohort", result) is None
    assert not store.bundles


@pytest.mark.parametrize("dimensions", [["scope_id"], [], ["unit_name", "unit_name"]])
def test_cohort_capture_rejects_unknown_or_invalid_grouping(dimensions):
    """Prevent private metadata or contradictory grain from entering displays."""
    result = cohort_table()
    result["context"]["group_by"] = dimensions
    store = EvidenceStore()
    assert capture_evidence(store, "query_cohort", result) is None
    assert not store.bundles


def test_cohort_capture_rejects_rows_missing_a_grouping_field():
    """Do not present a holder relationship whose declared entity is missing."""
    result = cohort_table()
    del result["results"][0]["unit_name"]
    store = EvidenceStore()
    assert capture_evidence(store, "query_cohort", result) is None
    assert not store.bundles


def test_cohort_table_empty_and_capped_results_preserve_coverage():
    """Keep declared columns for empty results and label capped slices honestly."""
    result = cohort_table()
    row = result["results"][0]
    result["results"] = []
    store = EvidenceStore()
    reference = capture_evidence(store, "query_cohort", result)
    assert store.bundles[reference["evidence_ref"]].datasets[0].rows == ()
    result["results"] = [row] * 201
    result["page"]["has_more"] = False
    reference = capture_evidence(store, "query_cohort", result)
    dataset = store.bundles[reference["evidence_ref"]].datasets[0]
    assert len(dataset.rows) == 200 and dataset.page.has_more
    assert dataset.page.offset == 20


def test_comparison_summary_is_presentable_without_a_histogram():
    """Expose aligned reported summaries without requiring or inventing bins."""
    result = comparison()
    result["target"].update(histogram=None, avg_placement=3.4567, top4_rate=0.6251)
    store = EvidenceStore()
    reference = capture_evidence(store, "compare_cohorts", result)
    bundle = store.bundles[reference["evidence_ref"]]
    target, baseline, summary = bundle.datasets
    assert target.unavailable and baseline.unavailable
    assert summary.ref == "summary"
    assert summary.rows[0].values == {
        "cohort": "Target", "boards": 28, "avg_placement": 3.4567,
        "top4_rate": 0.6251, "win_rate": None,
    }
    assert summary.rows[1].values == {
        "cohort": "Baseline", "boards": None, "avg_placement": None,
        "top4_rate": None, "win_rate": None,
    }
    assert summary.page.count == 2 and not summary.page.has_more
    spec = DisplaySpec(
        evidence_ref=bundle.ref, dataset_ref="summary", kind="static_table",
        title="Two cohorts", columns=["cohort", "boards", "avg_placement"],
        primary_metric="avg_placement",
    )
    assert resolve_presentation(store, spec, "summary-view").bundle == bundle
    descriptor = next(item for item in reference["datasets"] if item["dataset_ref"] == "summary")
    assert descriptor["displays"] == ["static_table", "interactive_table"]


def test_comparison_suppression_discards_all_numerical_summary_values():
    """Honor suppression even when an upstream result contains stray numbers."""
    result = comparison()
    result["baseline"].update(boards=3, avg_placement=1.23, top4_rate=1.0, win_rate=1.0)
    store = EvidenceStore()
    reference = capture_evidence(store, "compare_cohorts", result)
    bundle = store.bundles[reference["evidence_ref"]]
    baseline = bundle.datasets[1]
    row = bundle.datasets[2].rows[1]
    assert baseline.unavailable and baseline.boards is None
    assert all(value is None for key, value in row.values.items() if key != "cohort")


@pytest.mark.parametrize("empty_key", ["target", "baseline"])
def test_empty_comparison_cohort_preserves_other_evidence_and_zero_sample(empty_key):
    """Preserve actual empty-cohort output without discarding the reportable side."""
    result = comparison()
    other_key = "baseline" if empty_key == "target" else "target"
    result[other_key] = {**result["target"], "label": "Reportable cohort"}
    result[empty_key] = {
        "label": "Empty cohort", "boards": 0, "suppressed": False, "histogram": {},
    }
    store = EvidenceStore()
    reference = capture_evidence(store, "compare_cohorts", result)
    bundle = store.bundles[reference["evidence_ref"]]
    distributions = {dataset.ref: dataset for dataset in bundle.datasets[:2]}
    summary = {row.key: row.values for row in bundle.datasets[2].rows}
    assert distributions[empty_key].unavailable
    assert distributions[empty_key].boards == 0 and distributions[empty_key].bins == ()
    assert not distributions[other_key].unavailable
    assert sum(bin.count for bin in distributions[other_key].bins) == 28
    assert summary[empty_key] == {
        "cohort": "Empty cohort", "boards": 0,
        "avg_placement": None, "top4_rate": None, "win_rate": None,
    }
    assert summary[other_key]["boards"] == 28


def test_empty_and_suppressed_comparison_cohorts_keep_distinct_sample_states():
    """Keep an explicit zero sample separate from a hidden sample and null rates."""
    result = comparison()
    result["target"].update(boards=0, histogram={}, top4_rate=0, win_rate=0)
    store = EvidenceStore()
    reference = capture_evidence(store, "compare_cohorts", result)
    summary = store.bundles[reference["evidence_ref"]].datasets[2]
    assert summary.rows[0].values["boards"] == 0
    assert summary.rows[1].values["boards"] is None
    for row in summary.rows:
        assert row.values["top4_rate"] is None and row.values["win_rate"] is None


@pytest.mark.parametrize("columns", [["top4_rate"], ["cohort", "top4_rate"], ["boards", "top4_rate"]])
def test_comparison_summary_requires_visible_identity_and_sample(columns):
    """Reject ambiguous cohort statistics with a correctable display error."""
    store = EvidenceStore()
    reference = capture_evidence(store, "compare_cohorts", comparison())
    spec = DisplaySpec(
        evidence_ref=reference["evidence_ref"], dataset_ref="summary",
        kind="static_table", title="Two cohorts", columns=columns,
    )
    with pytest.raises(ValueError, match="include columns: boards, cohort"):
        resolve_presentation(store, spec, "ambiguous-summary")
    assert not store.presentations


@pytest.mark.parametrize("omitted", ["unit_name", "unit_star_level", "item_name", "distinct_boards"])
def test_grouped_cohort_table_requires_complete_grain_and_sample(omitted):
    """Keep holder, star and sample distinctions visible for every grouped row."""
    store = EvidenceStore()
    reference = capture_evidence(store, "query_cohort", cohort_table())
    columns = ["unit_name", "unit_star_level", "item_name", "distinct_boards", "top4_rate"]
    columns.remove(omitted)
    spec = DisplaySpec(
        evidence_ref=reference["evidence_ref"], dataset_ref="rows",
        kind="interactive_table", title="Grouped cohorts", columns=columns,
    )
    with pytest.raises(ValueError, match="Keep cohort identity and board samples visible"):
        resolve_presentation(store, spec, "ambiguous-group")
    assert not store.presentations


@pytest.mark.parametrize("field,value", [("boards", None), ("boards", 9), ("avg_placement", 8.1)])
def test_malformed_comparison_summary_does_not_register(field, value):
    """Reject unsupported samples and placement metrics at the display boundary."""
    result = comparison()
    result["target"][field] = value
    store = EvidenceStore()
    assert capture_evidence(store, "compare_cohorts", result) is None
    assert not store.bundles


@pytest.mark.parametrize("name,dataset_ref", [("query_cohort", "rows"), ("compare_cohorts", "summary")])
@pytest.mark.parametrize("with_store", [False, True])
def test_registered_cohort_tools_share_chat_context_and_retain_prose_fallback(name, dataset_ref, with_store):
    """Use chat's typed evidence context while preserving no-store eval outputs."""

    async def run():
        """Invoke the registry boundary and presentation without database or model calls."""
        output = cohort_table() if name == "query_cohort" else comparison()
        if name == "compare_cohorts":
            output["target"]["top4_rate"] = 0.6251
        store = EvidenceStore()
        run_context = AssistantRunContext(
            runtime=RuntimeSettings(
                request_id="evidence-test", set_number=None,
                root_assistant=AssistantName.UNIT_EXPERT,
            ),
            evidence=store,
        ) if with_store else None

        async def analytical(ctx, payload):
            """Return a completed public cohort result at original precision."""
            return output

        tool = _ensure_sdk_tool(SimpleNamespace(
            name=name, on_invoke_tool=analytical, params_json_schema={},
        ))
        captured = await tool.on_invoke_tool(context(run_context, name, "query"), "{}")
        if not with_store:
            assert "evidence" not in captured
            return
        reference = captured["evidence"]["evidence_ref"]
        columns = (
            ["unit_name", "unit_star_level", "item_name", "distinct_boards", "top4_rate"]
            if name == "query_cohort" else ["cohort", "boards", "top4_rate"]
        )
        spec = DisplaySpec(
            evidence_ref=reference, dataset_ref=dataset_ref, kind="static_table",
            title="Cohort outcome", columns=columns, primary_metric="top4_rate",
        )
        ack = await get_tool("present_evidence").on_invoke_tool(
            context(run_context, "present_evidence", "view"),
            json.dumps({"request": spec.model_dump()}),
        )
        assert ack["presented"]
        presentation = store.presentations["view"]
        dataset = next(item for item in presentation.bundle.datasets if item.ref == dataset_ref)
        assert dataset.rows[0].values["top4_rate"] == 0.6251

    asyncio.run(run())


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
