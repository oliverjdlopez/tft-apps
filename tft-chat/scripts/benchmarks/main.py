"""CLI and workload orchestration for development database benchmarks."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import platform
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .models import BenchmarkCase, CaseReport, WorkloadDefinition
from .utils import (
    benchmark_session_scope,
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
        "resolve_names", "light", "resolve_tft_names",
        "Resolve representative unit, item, and trait names.", "resolution",
        prerequisites=("unit", "item", "trait"),
    ),
    WorkloadDefinition(
        "rank_units_rollup", "light", "rank_units",
        "Rank across-star unit rollups by observed games.",
        group_by=("unit_name",),
    ),
    WorkloadDefinition(
        "rank_items_rollup", "light", "rank_items",
        "Rank overall item rollups by boards.", group_by=("item_name",),
    ),
    WorkloadDefinition(
        "rank_traits_rollup", "light", "rank_traits",
        "Rank trait rollups by observed games.", group_by=("trait_name",),
    ),
    WorkloadDefinition(
        "rank_units_conditioned", "heavy", "rank_units",
        "Rank units on boards with an active trait.",
        group_by=("unit_name",), prerequisites=("trait",),
    ),
    WorkloadDefinition(
        "rank_unit_loadout", "heavy", "rank_unit_loadouts",
        "Rank reportable loadouts for a verified unit.",
        group_by=("unit_name", "loadout_key"),
        prerequisites=("unit",),
    ),
    WorkloadDefinition(
        "query_cohort_three_way", "heavy", "query_cohort",
        "Group a trait cohort by unit, item, and active trait.",
        group_by=("unit_name", "item_name", "trait_name"),
        prerequisites=("trait", "unit", "item"),
    ),
    WorkloadDefinition(
        "compare_holder_item", "heavy", "compare_cohorts",
        "Compare a holder-item cohort with its within-holder complement.",
        "comparison", prerequisites=("unit", "item"),
    ),
    WorkloadDefinition(
        "cohort_unit_deltas", "heavy", "get_cohort_unit_deltas",
        "Measure unit outcome deltas inside a trait cohort.",
        group_by=("unit_name",), prerequisites=("trait",),
    ),
    WorkloadDefinition(
        "cohort_item_deltas", "heavy", "get_cohort_item_deltas",
        "Measure item outcome deltas by holder inside a trait cohort.",
        group_by=("item_name", "unit_name"), prerequisites=("trait",),
    ),
    WorkloadDefinition(
        "cohort_trait_deltas", "heavy", "get_cohort_trait_deltas",
        "Measure active-trait outcome deltas inside a trait cohort.",
        group_by=("trait_name", "tier"), prerequisites=("trait",),
    ),
)


def positive_integer(value: str) -> int:
    """Parse a positive CLI integer.

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


def concurrency_value(value: str) -> int:
    """Parse the supported bounded concurrent-call count.

    Args:
        value: User-provided command-line value.

    Returns:
        Concurrent timed-call limit from one through four.

    Raises:
        argparse.ArgumentTypeError: If the value is outside the supported range.
    """
    parsed = positive_integer(value)
    if parsed > 4:
        raise argparse.ArgumentTypeError("expected a value from 1 through 4")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the development benchmark command-line parser.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        description="Run read-only benchmarks against the configured application database tools."
    )
    parser.add_argument(
        "--suite", choices=("light", "heavy", "all"), default="all",
        help="Workload tier to execute (default: all).",
    )
    parser.add_argument(
        "--light-runs", type=positive_integer, default=3,
        help="Timed samples per light workload (default: 3).",
    )
    parser.add_argument(
        "--heavy-runs", type=positive_integer, default=1,
        help="Timed samples per heavy workload (default: 1).",
    )
    parser.add_argument(
        "--concurrency", type=concurrency_value, default=1,
        help="Concurrent timed calls per case, from 1 through 4 (default: sequential).",
    )
    parser.add_argument(
        "--no-profile", action="store_true",
        help="Skip the separate worker-thread cProfile pass.",
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("profiles/benchmarks"),
        help="Directory for ignored benchmark artifacts.",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List workload definitions without connecting to the database.",
    )
    return parser


def print_workloads() -> None:
    """Print stable workload names and descriptions without DB access."""
    for definition in WORKLOAD_DEFINITIONS:
        print(
            f"{definition.tier:6} {definition.name:28} "
            f"{definition.tool_name:24} {definition.description}"
        )


def selected_definitions(suite: str) -> list[WorkloadDefinition]:
    """Select definitions in stable declaration order.

    Args:
        suite: Requested tier or all tiers.

    Returns:
        Matching workload definitions.
    """
    if suite == "all":
        return list(WORKLOAD_DEFINITIONS)
    return [definition for definition in WORKLOAD_DEFINITIONS if definition.tier == suite]


def discovery_case(
    name: str,
    tool_name: str,
    arguments: dict[str, Any],
    description: str,
    expected_kind: str = "table",
) -> BenchmarkCase:
    """Build a temporary discovery invocation.

    Args:
        name: Discovery operation name.
        tool_name: Registered read-only database tool.
        arguments: Validated invocation arguments.
        description: Diagnostic purpose.
        expected_kind: Result family expected from the tool.

    Returns:
        Temporary discovery case.
    """
    return BenchmarkCase(
        name, "light", tool_name, arguments, description,
        expected_kind=expected_kind,  # type: ignore[arg-type]
    )


def rows_from(record: Any) -> list[dict[str, Any]]:
    """Return dictionary rows from a successful discovery invocation.

    Args:
        record: Invocation record containing an optional retained result.

    Returns:
        Result rows, or an empty list for errors and unexpected shapes.
    """
    if getattr(record, "status", None) != "success":
        return []
    result = getattr(record, "result", None)
    rows = result.get("results") if isinstance(result, Mapping) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


async def discover_anchors(
    definitions: list[WorkloadDefinition],
    run_id: str,
    event_records: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, str], dict[str, Any], str | None]:
    """Discover only names required by selected cases, then verify their kinds.

    Args:
        definitions: Selected workloads whose prerequisites drive discovery.
        run_id: Unique benchmark run identifier.
        event_records: Captured database timing events.

    Returns:
        Exact anchors, per-anchor errors, safe observed population metadata,
        and the discovery operation that timed out, if any.
    """
    required = {name for definition in definitions for name in definition.prerequisites}
    anchors: dict[str, str] = {}
    errors: dict[str, str] = {}
    metadata: dict[str, Any] = {}
    needs_trait = "trait" in required
    needs_pair = bool(required & {"unit", "item"})
    traits: list[str] = []
    if needs_trait:
        trait_result = await invoke_tool(
            discovery_case(
                "discovery_traits",
                "rank_traits",
                {"sort_by": "games", "sort_direction": "asc", "range": [0, 5]},
                "Select bounded, lower-frequency candidate traits.",
            ),
            "discovery", 0, run_id, event_records, keep_result=True,
        )
        if trait_result.status == "timeout":
            errors["discovery"] = "Trait discovery timed out."
            return anchors, errors, metadata, trait_result.case_name
        context = getattr(trait_result, "result", None)
        if isinstance(context, Mapping) and isinstance(context.get("context"), Mapping):
            metadata["trait_population_boards"] = context["context"].get("population_boards")
        for row in rows_from(trait_result):
            value = row.get("trait_name")
            if isinstance(value, str) and value and value not in traits:
                traits.append(value)
        if not traits:
            errors["trait"] = trait_result.error or "no reportable trait rows were returned"

    if needs_pair:
        chosen: tuple[str, str, str] | None = None
        for candidate_index, trait in enumerate(traits):
            cohort = {"trait_conditions": [{"name": trait}]}
            pair_result = await invoke_tool(
                discovery_case(
                    "discovery_item_holders",
                    "get_cohort_item_deltas",
                    {"cohort": cohort, "group_by_holder": True, "range": [0, 10]},
                    "Find a reportable item-holder pair inside a candidate trait cohort.",
                ),
                "discovery", candidate_index, run_id, event_records, keep_result=True,
            )
            pair_context = getattr(pair_result, "result", None)
            if (
                isinstance(pair_context, Mapping)
                and isinstance(pair_context.get("context"), Mapping)
            ):
                metadata["fact_cohort_population_boards"] = (
                    pair_context["context"].get("population_boards")
                )
                metadata["minimum_reportable_boards"] = (
                    pair_context["context"].get("minimum_reportable_boards")
                )
            for row in rows_from(pair_result):
                item = row.get("item_name")
                holder = row.get("unit_name")
                if trait and isinstance(item, str) and item and isinstance(holder, str) and holder:
                    chosen = (trait, holder, item)
                    break
            log_event(
                "discovery_candidate",
                candidate_index=candidate_index,
                outcome=(
                    "pair_found"
                    if chosen
                    else pair_result.status
                    if pair_result.status != "success"
                    else "no_reportable_pair"
                ),
            )
            if pair_result.status == "timeout":
                errors["discovery"] = "Item-holder discovery timed out."
                return anchors, errors, metadata, pair_result.case_name
            if chosen:
                break
        if chosen:
            anchors.update(trait=chosen[0], unit=chosen[1], item=chosen[2])
        elif needs_trait:
            unavailable_pair = (
                "no reportable item-holder pair was found in candidate trait cohorts"
            )
            errors.setdefault("unit", unavailable_pair)
            errors.setdefault("item", unavailable_pair)
    elif traits:
        anchors["trait"] = traits[0]

    # Verify stored names and entity categories before workloads use them.
    if anchors:
        kinds = [("unit", "unit"), ("item", "item"), ("trait", "trait")]
        names = [anchors[key] for key, _ in kinds if key in anchors]
        resolution = await invoke_tool(
            discovery_case(
                "discovery_verify_names",
                "resolve_tft_names",
                {"names": names},
                "Verify discovered names and entity kinds.",
                "resolution",
            ),
            "discovery", 2, run_id, event_records, keep_result=True,
        )
        if resolution.status == "timeout":
            errors["discovery"] = "Name verification timed out."
            return anchors, errors, metadata, resolution.case_name
        entries = rows_from(resolution)
        required_kinds = [pair for pair in kinds if pair[0] in anchors]
        for index, (key, expected_kind) in enumerate(required_kinds):
            entry = entries[index] if index < len(entries) else {}
            matches = entry.get("matches", [])
            exact = any(
                isinstance(match, Mapping)
                and match.get("name") == anchors[key]
                and match.get("kind") == expected_kind
                for match in matches
            )
            if not exact:
                errors[key] = resolution.error or (
                    f"resolver did not verify {expected_kind} name {anchors[key]!r}"
                )
                anchors.pop(key, None)
    return anchors, errors, metadata, None


def build_cases(
    anchors: Mapping[str, str], suite: str
) -> tuple[list[BenchmarkCase], list[CaseReport]]:
    """Bind selected definitions and create explicit prerequisite-failure records.

    Args:
        anchors: Discovered and verified stored names.
        suite: Requested workload tier.

    Returns:
        Runnable cases and reports for cases that cannot be meaningfully bound.
    """
    cases: list[BenchmarkCase] = []
    unavailable: list[CaseReport] = []
    for definition in selected_definitions(suite):
        missing = [key for key in definition.prerequisites if key not in anchors]
        trait_cohort = {"trait_conditions": [{"name": anchors.get("trait", "")}]}
        arguments: dict[str, Any] = {
            "resolve_names": {
                "names": [
                    anchors[key]
                    for key in ("unit", "item", "trait")
                    if key in anchors
                ]
            },
            "rank_units_rollup": {"sort_by": "games", "range": [0, 20]},
            "rank_items_rollup": {"sort_by": "boards", "range": [0, 20]},
            "rank_traits_rollup": {"sort_by": "games", "range": [0, 20]},
            "rank_units_conditioned": {
                "trait": anchors.get("trait", ""),
                "sort_by": "games",
                "range": [0, 20],
            },
            "rank_unit_loadout": {
                "unit": anchors.get("unit", ""),
                "sort_by": "boards",
                "range": [0, 20],
            },
            "query_cohort_three_way": {
                "cohort": {
                    **trait_cohort,
                    "item_conditions": [{
                        "name": anchors.get("item", ""),
                        "holder": anchors.get("unit", ""),
                    }],
                },
                "group_by": ["unit_name", "item_name", "trait_name"],
                "order_by": [{"metric": "distinct_boards", "direction": "desc"}],
                "limit": 100,
            },
            "compare_holder_item": {
                "target": {
                    "item_conditions": [{
                        "name": anchors.get("item", ""),
                        "holder": anchors.get("unit", ""),
                    }]
                },
                "shared": {"unit_conditions": [{"name": anchors.get("unit", "")}]},
            },
            "cohort_unit_deltas": {"cohort": trait_cohort, "range": [0, 20]},
            "cohort_item_deltas": {
                "cohort": trait_cohort,
                "group_by_holder": True,
                "range": [0, 20],
            },
            "cohort_trait_deltas": {
                "cohort": trait_cohort,
                "group_by_tier": True,
                "range": [0, 20],
            },
        }
        case = BenchmarkCase(
            definition.name,
            definition.tier,
            definition.tool_name,
            arguments[definition.name],
            definition.description,
            definition.expected_kind,
            definition.group_by,
            definition.prerequisites,
        )
        if missing:
            report = CaseReport(
                case=case,
                status="unavailable_prerequisite",
                error="Missing verified prerequisite(s): " + ", ".join(missing),
            )
            unavailable.append(report)
        else:
            cases.append(case)
    return cases, unavailable


def repository_revision() -> dict[str, Any]:
    """Return the current Git revision and dirty state without file contents.

    Returns:
        Short SHA and working-tree dirty flag, or an unavailable diagnostic.
    """
    repository = Path(__file__).resolve().parents[3]
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return {"sha": sha, "dirty": bool(dirty)}
    except (OSError, subprocess.CalledProcessError):
        return {"sha": None, "dirty": None}


def safe_database_metadata() -> dict[str, Any]:
    """Read non-identifying database and active-build metadata read-only.

    Returns:
        PostgreSQL server version and active scope/fact-build properties,
        excluding credentials, connection URLs, and internal scope IDs.
    """
    from sqlalchemy import text

    from db.models.analysis import AnalysisFactBuild, AnalysisScope
    from domain.tools.db_tools import utils as db_tool_utils

    session = db_tool_utils.open_db(ensure_schema=False)
    try:
        connection = session.connection()
        if connection.dialect.name == "postgresql":
            # PostgreSQL requires READ ONLY to be the first statement in a transaction.
            session.execute(text("SET TRANSACTION READ ONLY"))
        server_version = getattr(connection.dialect, "server_version_info", None)
        active_scope = (
            session.query(
                AnalysisScope.scope_id,
                AnalysisScope.patch,
                AnalysisScope.queue_id,
                AnalysisScope.tft_set_number,
                AnalysisScope.status,
                AnalysisScope.universe_boards,
            )
            .filter(AnalysisScope.is_active.is_(True))
            .one_or_none()
        )
        fact_build = (
            session.get(AnalysisFactBuild, active_scope.scope_id)
            if active_scope is not None
            else None
        )
        return {
            "database_product": connection.dialect.name,
            "server_version": (
                ".".join(map(str, server_version)) if server_version else None
            ),
            "active_scope": (
                {
                    "patch": active_scope.patch,
                    "queue_id": active_scope.queue_id,
                    "tft_set_number": active_scope.tft_set_number,
                    "status": active_scope.status,
                    "universe_boards": active_scope.universe_boards,
                }
                if active_scope is not None
                else None
            ),
            "active_fact_build": (
                {
                    "status": fact_build.status,
                    "schema_version": fact_build.schema_version,
                    "board_count": fact_build.board_count,
                    "lobby_count": fact_build.lobby_count,
                    "processed_match_count": fact_build.processed_match_count,
                }
                if fact_build is not None
                else None
            ),
        }
    finally:
        session.close()


def print_report_table(reports: Iterable[CaseReport]) -> None:
    """Print a compact timing and status table.

    Args:
        reports: Completed or unavailable case reports.
    """
    print(
        "\ncase                         tier   status                    "
        "median ms   db execution ms"
    )
    print("-" * 92)
    for report in reports:
        timed = [
            record.elapsed_ms
            for record in report.records
            if record.phase == "timed" and record.status == "success"
        ]
        database = [
            record.database_timing.get("execution_ms")
            for record in report.records
            if record.phase == "timed"
            and record.status == "success"
            and isinstance(record.database_timing.get("execution_ms"), (int, float))
        ]
        median = f"{statistics.median(timed):.3f}" if timed else "-"
        db_median = f"{statistics.median(database):.3f}" if database else "-"
        print(
            f"{report.case.name:28} {report.case.tier:6} "
            f"{report.status:25} {median:>10} {db_median:>17}"
        )


async def run_benchmark(args: argparse.Namespace) -> int:
    """Run the selected benchmark workloads and write summary artifacts.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Nonzero when a case or runner setup failed.
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
    anchor_errors: dict[str, str] = {}
    build_metadata: dict[str, Any] = {}
    database = "unavailable"
    run_error: str | None = None
    try:
        from db.session import database_label

        database = database_label()
    except Exception as exc:
        run_error = (
            "Could not resolve the configured application database "
            f"({type(exc).__name__})."
        )

    with event_logging(run_dir / "events.jsonl") as events:
        log_event(
            "run_start",
            run_id=run_id,
            suite=args.suite,
            database=database,
            profile=not args.no_profile,
            concurrency=args.concurrency,
        )
        if run_error is None:
            try:
                # Keep schema creation disabled until every DB worker has drained.
                with benchmark_session_scope():
                    definitions = selected_definitions(args.suite)
                    try:
                        build_metadata.update(safe_database_metadata())
                    except Exception as exc:
                        # This metadata is descriptive; preserve execution if unavailable.
                        build_metadata["database_metadata_error"] = type(exc).__name__
                    anchors, anchor_errors, discovered_metadata, discovery_timeout = await discover_anchors(
                        definitions, run_id, events.records
                    )
                    build_metadata.update(discovered_metadata)
                    cases, unavailable = build_cases(anchors, args.suite)
                    if discovery_timeout is not None:
                        bound_cases = {case.name: case for case in cases}
                        bound_cases.update({report.case.name: report.case for report in unavailable})
                        unavailable = [
                            CaseReport(
                                case=bound_cases[definition.name],
                                status="not_run_timeout",
                                error=f"Not scheduled after discovery timeout in {discovery_timeout}.",
                            )
                            for definition in definitions
                        ]
                        cases = []
                    reports.extend(unavailable)
                    for index, case in enumerate(cases):
                        iterations = (
                            args.light_runs
                            if case.tier == "light"
                            else args.heavy_runs
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
                            concurrency=args.concurrency,
                        )
                        reports.append(report)
                        log_event(
                            "case_complete",
                            run_id=run_id,
                            case=case.name,
                            tier=case.tier,
                            status=report.status,
                        )
                        if any(record.status == "timeout" for record in report.records):
                            # A timeout stops later work after this case drains its workers.
                            for pending_case in cases[index + 1 :]:
                                reports.append(
                                    CaseReport(
                                        case=pending_case,
                                        status="not_run_timeout",
                                        error=(
                                            f"Not scheduled after timeout in {case.name}."
                                        ),
                                    )
                                )
                            break
            except Exception as exc:
                run_error = f"Benchmark setup or orchestration failed ({type(exc).__name__}): {exc}"
                log_event("run_error", run_id=run_id, error_type=type(exc).__name__)
        else:
            log_event("run_error", run_id=run_id, error=run_error)

        failures = [report for report in reports if report.status != "success"]
        status = "failed" if run_error or failures else "success"
        summary = {
            "schema_version": 2,
            "run_id": run_id,
            "status": status,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "revision": repository_revision(),
            "database": database,
            "build_metadata": {"python": platform.python_version(), **build_metadata},
            "configuration": {
                "suite": args.suite,
                "light_runs": args.light_runs,
                "heavy_runs": args.heavy_runs,
                "profile": not args.no_profile,
                "concurrency": args.concurrency,
                "timed_execution": (
                    "sequential" if args.concurrency == 1 else "concurrent"
                ),
                "warmup_runs_per_case": 1,
                "profile_runs_per_case": 0 if args.no_profile else 1,
                "output_root": str(output_root),
                "latency_units": "milliseconds",
                "statistics": (
                    "successful timed samples only; p50 requires at least "
                    "one sample and p95 requires at least 20"
                ),
            },
            "anchors": anchors,
            "anchor_errors": anchor_errors,
            "error": run_error,
            "cases": [case_report_dict(report) for report in reports],
        }
        write_json(run_dir / "summary.json", summary)
        log_event("run_complete", run_id=run_id, status=status)
    print_report_table(reports)
    print(f"\nBenchmark artifacts: {run_dir}")
    if run_error:
        print(f"Benchmark failed: {run_error}", file=sys.stderr)
    return (
        1
        if run_error or any(report.status != "success" for report in reports)
        else 0
    )


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the benchmark command.

    Args:
        argv: Optional argument vector.

    Returns:
        Command exit code.
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
