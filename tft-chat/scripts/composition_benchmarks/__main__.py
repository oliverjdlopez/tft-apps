"""Define, run, and display a small composition benchmark sweep."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import tomllib

from .compute import CudaUnavailable, measure_adapter, measure_distance, prepare_cuda
from .models import BenchmarkConfig
from .utils import (
    expand_runs,
    load_inputs,
    machine_metadata,
    select_sample,
    write_results,
)


def run_benchmark(config, config_path, output):
    """Run sequentially to avoid contention and save every completed measurement.

    Args:
        config: Validated parameter space and timing settings.
        config_path: Source file used to resolve relative input paths.
        output: Directory for incremental JSON and standalone HTML artifacts.

    Returns:
        Complete report including explicit failures, skips, and warmup durations.
    """
    cases = expand_runs(config)
    boards, source = load_inputs(config, config_path)
    report = {
        "schema_version": "composition-benchmark.v1",
        "name": config.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": "running",
        "config": config.model_dump(mode="json"),
        "source": source,
        "machine": machine_metadata(Path(__file__).resolve().parents[2]),
        "planned_runs": len(cases) * config.repeats,
        "rows": [],
    }
    write_results(output, report)
    cuda_error = None
    if any(case.backend == "cuda" for case in cases):
        started = time.perf_counter()
        try:
            report["machine"]["gpu"] = prepare_cuda()
        except CudaUnavailable as error:
            cuda_error = str(error)
        report["cuda_setup_seconds"] = time.perf_counter() - started
    try:
        for case in cases:
            sample = select_sample(boards, case.sample_size, case.seed)
            common = case.model_dump(mode="json")
            warmup_seconds = None
            warmup_error = None
            if not (case.backend == "cuda" and cuda_error):
                started = time.perf_counter()
                try:
                    for _ in range(config.warmups):
                        if case.kind == "distance":
                            measure_distance(sample, case.backend)
                        else:
                            measure_adapter(sample, case)
                except Exception as error:
                    warmup_error = f"{type(error).__name__}: {error}"
                warmup_seconds = time.perf_counter() - started
            for repeat in range(config.repeats):
                row = {**common, "repeat": repeat + 1, "warmup_seconds": warmup_seconds}
                try:
                    if case.backend == "cuda" and cuda_error:
                        raise CudaUnavailable(cuda_error)
                    if warmup_error:
                        raise RuntimeError(f"Warmup failed: {warmup_error}")
                    metrics = (
                        measure_distance(sample, case.backend)
                        if case.kind == "distance"
                        else measure_adapter(sample, case)
                    )
                    row.update(status="completed", **metrics)
                except CudaUnavailable as error:
                    row.update(status="skipped", error=str(error))
                except Exception as error:
                    row.update(
                        status="failed", error=f"{type(error).__name__}: {error}"
                    )
                report["rows"].append(row)
                write_results(output, report)
                elapsed = (
                    f"{row['total_seconds']:.3f}s"
                    if "total_seconds" in row
                    else row["error"]
                )
                print(
                    f"[{len(report['rows'])}/{report['planned_runs']}] {case.algorithm or 'distance'} {case.backend} n={case.sample_size} {row['status']}: {elapsed}",
                    flush=True,
                )
    except KeyboardInterrupt:
        report["state"] = "interrupted"
        write_results(output, report)
        raise
    report["state"] = (
        "completed_with_errors"
        if any(r["status"] == "failed" for r in report["rows"])
        else "completed"
    )
    write_results(output, report)
    return report


def main():
    """Validate a TOML plan, optionally list it, or execute and write a local report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="TOML run definition")
    parser.add_argument(
        "--output", type=Path, default=Path("profiles/composition-benchmarks")
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Validate and show expanded runs without execution",
    )
    args = parser.parse_args()
    config = BenchmarkConfig.model_validate(
        tomllib.loads(args.config.read_text(encoding="utf-8"))
    )
    cases = expand_runs(config)
    if args.list:
        print(json.dumps([case.model_dump(mode="json") for case in cases], indent=2))
        return
    output = args.output
    if not output.is_absolute():
        output = Path(__file__).resolve().parents[2] / output
    output = output.resolve()
    if (output / "results.json").exists():
        parser.error(
            "Output already contains a report; choose another --output directory"
        )
    try:
        report = run_benchmark(config, args.config.resolve(), output)
    except KeyboardInterrupt:
        print("Interrupted; completed results have been saved.")
        raise SystemExit(130)
    print(f"Report: {output / 'index.html'}")
    if report["state"] == "completed_with_errors":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
