"""CLI and workload orchestration for development database benchmarks."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .models import BenchmarkCase, CaseReport, WorkloadDefinition
from .utils import (
    case_report_dict,
    event_logging,
    invoke_tool,
    log_event,
    run_case,
    shutdown_database_worker,
    write_json,
)


WORKLOAD_DEFINITIONS = (
    WorkloadDefinition(
        name="resolve_names",
        tier="light",
        tool_name="resolve_tft_names",
        description="Resolve one representative unit, item, and trait.",
    ),
    WorkloadDefinition(
        name="rank_units_rollup",
        tier="light",
        tool_name="rank_units",
        description="Rank unit rollups by observed games.",
    ),
    WorkloadDefinition(
        name="rank_items_rollup",
        tier="light",
        tool_name="rank_items",
        description="Rank overall item rollups by boards.",
    ),
    WorkloadDefinition(
        name="rank_traits_rollup",
        tier="light",
        tool_name="rank_traits",
        description="Rank trait rollups by observed games.",
    ),
    WorkloadDefinition(
        name="rank_items_conditioned",
        tier="heavy",
        tool_name="rank_items",
        description="Rank holder items inside a trait-conditioned board cohort.",
    ),
    WorkloadDefinition(
        name="query_cohort_three_way",
        tier="heavy",
        tool_name="query_cohort",
        description="Group a trait cohort by unit, item, and active trait.",
    ),
    WorkloadDefinition(
        name="compare_holder_item",
        tier="heavy",
        tool_name="compare_cohorts",
        description="Compare a holder-item cohort with its within-holder complement.",
    ),
)


def positive_integer(value: str) -> int:
    """Parse a strictly positive CLI integer.

    Args:
        value: User-provided command-line value.

    Returns:
        Parsed positive integer.

    Raises:
        argparse.ArgumentTypeError: If the value is not positive.
    """
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the development benchmark command-line parser.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run sequential read-only benchmarks against the configured "
            "application database tools."
        )
    )
    parser.add_argument(
        "--suite",
        choices=("light", "heavy", "all"),
        default="all",
        help="Workload tier to execute (default: all).",
    )
    parser.add_argument(
        "--light-runs",
        type=positive_integer,
        default=3,
        help="Timed samples per light workload (default: 3).",
    )
    parser.add_argument(
        "--heavy-runs",
        type=positive_integer,
        default=1,
        help="Timed samples per heavy workload (default: 1).",
    )
    parser.add_argument(
        "--no-profile",
        action="store_true",
        help="Skip the separate worker-thread cProfile pass.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("profiles/benchmarks"),
        help="Directory for ignored benchmark artifacts.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List workload definitions without connecting to the database.",
    )
    return parser


def print_workloads() -> None:
    """Print stable workload names and descriptions without DB access."""
    for definition in WORKLOAD_DEFINITIONS:
        print(
            f"{definition.tier:6} {definition.name:28} "
            f"{definition.tool_name:20} {definition.description}"
        )


def selected_definitions(suite: str) -> list[WorkloadDefinition]:
    """Select light, heavy, or all workload definitions.

    Args:
        suite: Requested CLI suite name.

    Returns:
        Definitions in stable declaration order.
    """
    if suite == "all":
        return list(WORKLOAD_DEFINITIONS)
    return [definition for definition in WORKLOAD_DEFINITIONS if definition.tier == suite]


def discovery_case(
    name: str, tool_name: str, arguments: dict[str, Any], description: str
) -> BenchmarkCase:
    """Build a temporary case used only for representative-data discovery.

    Args:
        name: Discovery operation name.
        tool_name: Registered database tool to call.
        arguments: Tool arguments.
        description: Diagnostic description.

    Returns:
        Discovery benchmark case.
    """
    return BenchmarkCase(
        name=name,
        tier="light",
        tool_name=tool_name,
        arguments=arguments,
        description=description,
    )


def rows_from(record: Any) -> list[dict[str, Any]]:
    """Return dictionary rows from a successful discovery invocation.

    Args:
        record: Invocation record containing an optional retained result.

    Returns:
        Result rows, or an empty list for errors and unexpected shapes.
    """
    result = getattr(record, "result", None)
    if not isinstance(result, Mapping):
        return []
    rows = result.get("results")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


async def discover_anchors(
    run_id: str, event_records: list[dict[str, Any]]
) -> dict[str, str]:
    """Find a reportable trait, unit, and holder item for dynamic workloads.

    Args:
        run_id: Unique benchmark run identifier.
        event_records: In-memory logger records for DB timing correlation.

    Returns:
        Exact stored names for ``trait``, ``unit``, and ``item``.

    Raises:
        RuntimeError: If the active database has no usable representative data.
    """
    trait_case = discovery_case(
        "discovery_traits",
        "rank_traits",
        {"sort_by": "games", "limit": 10},
        "Select candidate traits.",
    )
    trait_record = await invoke_tool(
        trait_case, "discovery", 0, run_id, event_records, keep_result=True
    )
    trait_rows = rows_from(trait_record)
    failures = [trait_record.error, trait_record.error_type]
    for trait_row in trait_rows:
        trait_name = trait_row.get("trait_name")
        if not isinstance(trait_name, str) or not trait_name:
            continue
        unit_case = discovery_case(
            "discovery_units",
            "rank_units",
            {
                "within": {"traits": [trait_name]},
                "sort_by": "games",
                "limit": 10,
            },
            "Select a reportable unit inside the candidate trait.",
        )
        unit_record = await invoke_tool(
            unit_case,
            "discovery",
            len(failures),
            run_id,
            event_records,
            keep_result=True,
        )
        failures.extend([unit_record.error, unit_record.error_type])
        for unit_row in rows_from(unit_record):
            unit_name = unit_row.get("unit_name")
            if not isinstance(unit_name, str) or not unit_name:
                continue
            item_case = discovery_case(
                "discovery_holder_items",
                "rank_items",
                {
                    "holder": unit_name,
                    "within": {"traits": [trait_name]},
                    "sort_by": "boards",
                    "limit": 5,
                },
                "Select a reportable item held by the candidate unit.",
            )
            item_record = await invoke_tool(
                item_case,
                "discovery",
                len(failures),
                run_id,
                event_records,
                keep_result=True,
            )
            failures.extend([item_record.error, item_record.error_type])
            item_rows = rows_from(item_record)
            if item_rows:
                item_name = item_rows[0].get("item_name")
                if isinstance(item_name, str) and item_name:
                    anchors = {
                        "trait": trait_name,
                        "unit": unit_name,
                        "item": item_name,
                    }
                    log_event("anchors_discovered", anchors=anchors)
                    return anchors
    detail = next((value for value in failures if value), "no reportable rows")
    raise RuntimeError(
        "Could not discover reportable aggregate/fact data for the benchmark "
        f"workloads: {detail}"
    )


def build_cases(
    anchors: Mapping[str, str], suite: str
) -> list[BenchmarkCase]:
    """Bind workload definitions to exact names from the active database.

    Args:
        anchors: Discovered exact trait, unit, and item names.
        suite: Requested workload tier.

    Returns:
        Fully bound benchmark cases in stable order.
    """
    trait = anchors["trait"]
    unit = anchors["unit"]
    item = anchors["item"]
    arguments: dict[str, dict[str, Any]] = {
        "resolve_names": {"names": [unit, item, trait]},
        "rank_units_rollup": {"sort_by": "games", "range": [0, 20]},
        "rank_items_rollup": {"sort_by": "boards", "range": [0, 20]},
        "rank_traits_rollup": {"sort_by": "games", "range": [0, 20]},
        "rank_items_conditioned": {
            "holder": unit,
            "within": {"traits": [trait]},
            "sort_by": "avg_placement",
            "sort_direction": "asc",
            "range": [0, 100],
        },
        "query_cohort_three_way": {
            "cohort": {"traits": [trait]},
            "group_by": ["unit_name", "item_name", "trait_name"],
            "order_by": [{"metric": "distinct_boards", "direction": "desc"}],
            "limit": 100,
        },
        "compare_holder_item": {
            "target": {
                "item_conditions": [{"name": item, "holder": unit}]
            },
            "shared": {"units": [unit]},
        },
    }
    definitions = selected_definitions(suite)
    return [
        BenchmarkCase(
            name=definition.name,
            tier=definition.tier,
            tool_name=definition.tool_name,
            arguments=arguments[definition.name],
            description=definition.description,
        )
        for definition in definitions
    ]


def print_report_table(reports: Iterable[CaseReport]) -> None:
    """Print a compact timing/status table for completed cases.

    Args:
        reports: Completed case reports.
    """
    print("\ncase                         tier   status    median ms   db execution ms")
    print("-" * 75)
    for report in reports:
        timed = [record.elapsed_ms for record in report.records if record.phase == "timed"]
        database = [
            record.database_timing.get("execution_ms")
            for record in report.records
            if record.phase == "timed"
            and isinstance(record.database_timing.get("execution_ms"), (int, float))
        ]
        median = f"{statistics.median(timed):.3f}" if timed else "-"
        db_median = f"{statistics.median(database):.3f}" if database else "-"
        print(
            f"{report.case.name:28} {report.case.tier:6} "
            f"{report.status:9} {median:>10} {db_median:>17}"
        )


async def run_benchmark(args: argparse.Namespace) -> int:
    """Run the selected development DB benchmark suite and write artifacts.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Process exit code, nonzero when discovery or any case failed.
    """
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:8]
    )
    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = Path(__file__).resolve().parents[2] / output_root
    run_dir = output_root / run_id
    profile_dir = run_dir / "profiles"
    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    reports: list[CaseReport] = []
    anchors: dict[str, str] = {}
    database = "unavailable"
    run_error: str | None = None
    try:
        from db.session import database_label

        database = database_label()
    except Exception as exc:
        run_error = f"Could not resolve the configured application database: {exc}"

    with event_logging(run_dir / "events.jsonl") as events:
        log_event(
            "run_start",
            run_id=run_id,
            suite=args.suite,
            database=database,
            profile=not args.no_profile,
        )
        if run_error is None:
            try:
                anchors = await discover_anchors(run_id, events.records)
                cases = build_cases(anchors, args.suite)
                for case in cases:
                    iterations = (
                        args.light_runs if case.tier == "light" else args.heavy_runs
                    )
                    log_event(
                        "case_start",
                        run_id=run_id,
                        case=case.name,
                        tier=case.tier,
                        iterations=iterations,
                    )
                    report = await run_case(
                        case,
                        run_id,
                        iterations,
                        not args.no_profile,
                        profile_dir,
                        events.records,
                    )
                    reports.append(report)
                    log_event(
                        "case_complete",
                        run_id=run_id,
                        case=case.name,
                        tier=case.tier,
                        status=report.status,
                    )
            except Exception as exc:
                run_error = str(exc)
                log_event("run_error", run_id=run_id, error_type=type(exc).__name__)
        else:
            log_event("run_error", run_id=run_id, error=run_error)

        failed_cases = [report for report in reports if report.status != "success"]
        status = "failed" if run_error or failed_cases else "success"
        summary = {
            "schema_version": 1,
            "run_id": run_id,
            "status": status,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "database": database,
            "configuration": {
                "suite": args.suite,
                "light_runs": args.light_runs,
                "heavy_runs": args.heavy_runs,
                "profile": not args.no_profile,
                "execution": "sequential",
            },
            "anchors": anchors,
            "error": run_error,
            "cases": [case_report_dict(report) for report in reports],
        }
        write_json(run_dir / "summary.json", summary)
        log_event("run_complete", run_id=run_id, status=status)
    print_report_table(reports)
    print(f"\nBenchmark artifacts: {run_dir}")
    if run_error:
        print(f"Benchmark failed: {run_error}", file=sys.stderr)
    return 1 if run_error or any(report.status != "success" for report in reports) else 0


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run the benchmark suite.

    Args:
        argv: Optional argument list, defaulting to ``sys.argv``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    if args.list:
        print_workloads()
        return 0
    try:
        return asyncio.run(run_benchmark(args))
    finally:
        shutdown_database_worker()


if __name__ == "__main__":
    raise SystemExit(main())
