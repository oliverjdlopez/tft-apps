"""Exercise sweep contracts, timing boundaries, persistence, and numerical parity."""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from domain.compositions.distance import board_distance
from domain.compositions.fixtures import fixture_boards
from scripts.composition_benchmarks import __main__ as runner
from scripts.composition_benchmarks.compute import (
    CudaUnavailable,
    check_distances,
    cpu_distances,
    cuda_distances,
    encode_boards,
    prepare_cuda,
)
from scripts.composition_benchmarks.models import BenchmarkConfig
from scripts.composition_benchmarks.report import render_report
from scripts.composition_benchmarks.utils import expand_runs, load_inputs, select_sample


def test_cartesian_sweep_freezes_effective_defaults():
    """Cross sizes, seeds, and parameters without losing adapter defaults."""
    config = BenchmarkConfig(
        sample_sizes=[24, 48],
        seeds=[2, 3],
        sweeps=[{"algorithm": "hdbscan", "parameters": {"min_cluster_size": [3, 5]}}],
    )
    cases = expand_runs(config)
    assert len(cases) == 8
    assert len({r.case_id for r in cases}) == 8
    assert all(r.parameters["rejection_distance"] == 2.0 for r in cases)
    assert cases == expand_runs(config)


@pytest.mark.parametrize(
    "definition",
    [
        {"kind": "adapter", "algorithm": "leiden", "backends": ["cuda"]},
        {"algorithm": "hdbscan", "parameters": {"min_samples": []}},
        {"kind": "distance", "parameters": {"unknown": [1]}},
    ],
)
def test_invalid_workload_rejected(definition):
    """Never mislabel CPU adapters as GPU implementations or accept empty axes."""
    with pytest.raises(ValueError):
        BenchmarkConfig(sweeps=[definition])


def test_invalid_adapter_parameter_rejected_before_execution():
    """Catch unknown algorithm settings and equivalent duplicated runs up front."""
    config = BenchmarkConfig(
        sweeps=[{"algorithm": "hdbscan", "parameters": {"missing": [1]}}]
    )
    with pytest.raises(ValueError):
        expand_runs(config)
    config = BenchmarkConfig(sweeps=[{"kind": "distance"}, {"kind": "distance"}])
    with pytest.raises(ValueError, match="duplicate"):
        expand_runs(config)


def test_samples_are_nested_and_real_input_is_not_silently_clamped(tmp_path):
    """Keep comparisons fair across sizes, workload order, and input row order."""
    assert select_sample(None, 20, 5) == select_sample(None, 40, 5)[:20]
    boards = fixture_boards()
    assert (
        select_sample(boards, 10, 5)
        == select_sample(tuple(reversed(boards)), 20, 5)[:10]
    )
    (tmp_path / "boards.json").write_text(
        json.dumps([b.model_dump(mode="json") for b in boards])
    )
    config = BenchmarkConfig(
        sample_sizes=[25], input_path="boards.json", sweeps=[{"kind": "distance"}]
    )
    with pytest.raises(ValueError, match="fewer"):
        load_inputs(config, tmp_path / "runs.toml")


def test_cpu_distance_preserves_duplicates_unknown_traits_and_empty_boards():
    """Compare every pair against scalar Euclidean distance, including empty inputs."""
    boards = fixture_boards()
    boards = (*boards, boards[0].model_copy(update={"units": (), "traits": ()}))
    expected = [[board_distance(a, b) for b in boards] for a in boards]
    actual = cpu_distances(encode_boards(boards))
    np.testing.assert_allclose(actual, expected, atol=1e-15, rtol=0)
    assert check_distances(boards, actual) < 1e-15


def test_runner_saves_repetitions_skips_and_failure_without_stopping(
    tmp_path, monkeypatch
):
    """Preserve usable CPU results when GPU is absent or one timed case fails."""
    config = BenchmarkConfig(
        sample_sizes=[8],
        repeats=2,
        warmups=0,
        sweeps=[{"kind": "distance", "backends": ["cpu", "cuda"]}],
    )

    def unavailable():
        """Simulate a host with no optional GPU runtime."""
        raise CudaUnavailable("GPU absent")

    monkeypatch.setattr(runner, "prepare_cuda", unavailable)
    report = runner.run_benchmark(config, tmp_path / "runs.toml", tmp_path / "out")
    assert [r["status"] for r in report["rows"]] == [
        "completed",
        "completed",
        "skipped",
        "skipped",
    ]
    saved = json.loads((tmp_path / "out/results.json").read_text())
    assert saved == report
    assert (tmp_path / "out/index.html").exists()

    def broken(*args):
        """Simulate a per-case failure that should not erase prior measurements."""
        raise ValueError("bad computation")

    monkeypatch.setattr(runner, "measure_distance", broken)
    report = runner.run_benchmark(config, tmp_path / "runs.toml", tmp_path / "failure")
    assert report["state"] == "completed_with_errors"
    assert len(report["rows"]) == 4


def test_warmups_are_not_recorded_as_repetitions(tmp_path, monkeypatch):
    """Count warmups separately so medians contain only requested timed runs."""
    calls = []

    def measure(*args):
        """Record measurement invocation without doing numerical work."""
        calls.append(1)
        return {"total_seconds": 0.1}

    monkeypatch.setattr(runner, "measure_distance", measure)
    config = BenchmarkConfig(
        sample_sizes=[4], repeats=2, warmups=2, sweeps=[{"kind": "distance"}]
    )
    report = runner.run_benchmark(config, tmp_path / "runs.toml", tmp_path / "out")
    assert len(calls) == 4 and len(report["rows"]) == 2


def test_report_escapes_script_terminators():
    """Keep titles, parameters, and exception strings inert in the HTML report."""
    payload = {"name": '</script><img src=x onerror="alert(1)">'}
    html = render_report(payload)
    assert payload["name"] not in html
    data = html.split('<script id="data" type="application/json">')[1].split(
        "</script>"
    )[0]
    assert json.loads(data) == payload


@pytest.mark.skipif(
    os.environ.get("CHATTFT_BENCHMARK_CUDA_TEST") != "1",
    reason="Opt-in actual CUDA parity check",
)
def test_cuda_matches_cpu_for_all_fixture_pairs():
    """Execute on real hardware and compare the entire matrix, not sampled pairs."""
    prepare_cuda()
    boards = (
        *fixture_boards(),
        fixture_boards()[0].model_copy(update={"units": (), "traits": ()}),
    )
    encoded = encode_boards(boards)
    np.testing.assert_allclose(
        cuda_distances(encoded), cpu_distances(encoded), atol=1e-12, rtol=0
    )


def test_interrupt_keeps_completed_measurements(tmp_path, monkeypatch):
    """Retain partial reports and mark interruption when a user stops a long sweep."""
    calls = 0

    def measure(*args):
        """Interrupt the second timed call after the first result has been saved."""
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return {"total_seconds": 0.1}

    monkeypatch.setattr(runner, "measure_distance", measure)
    config = BenchmarkConfig(
        sample_sizes=[4], repeats=3, warmups=0, sweeps=[{"kind": "distance"}]
    )
    with pytest.raises(KeyboardInterrupt):
        runner.run_benchmark(config, tmp_path / "runs.toml", tmp_path / "out")
    saved = json.loads((tmp_path / "out/results.json").read_text())
    assert saved["state"] == "interrupted"
    assert len(saved["rows"]) == 1


def test_hdbscan_gpu_sweeps_expand_and_other_algorithms_are_rejected():
    """Expand HDBSCAN CPU/CUDA classifier runs and reject retired adapters."""
    config = BenchmarkConfig(
        sample_sizes=[24],
        sweeps=[
            {"algorithm": name, "backends": ["cpu", "cuda"]}
            for name in ("hdbscan",)
        ],
    )
    cases = expand_runs(config)
    assert {(case.algorithm, case.backend) for case in cases} == {
        (name, backend)
        for name in ("hdbscan",)
        for backend in ("cpu", "cuda")
    }
