"""Sweep expansion, deterministic input selection, and artifact helpers."""

import hashlib
import itertools
import json
import platform
import random
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from domain.compositions.models import (
    BoardObservation,
    EntityRef,
    ItemOccurrence,
    UnitOccurrence,
)
from domain.compositions.registry import get_adapter
from .models import RunCase


# =====================================================================
# Run definitions and reproducible inputs
# Every workload sees the same ordered sample for a given size and seed.
# Synthetic inputs are explicit throughput fixtures, not gameplay evidence.
# =====================================================================


def expand_runs(config):
    """Validate adapter parameters and expand every sweep before starting work."""
    cases = []
    for sweep in config.sweeps:
        adapter = get_adapter(sweep.algorithm) if sweep.kind == "adapter" else None
        keys = sorted(sweep.parameters)
        for values in itertools.product(*(sweep.parameters[k] for k in keys)):
            parameters = dict(zip(keys, values))
            if adapter:
                parameters = adapter.Parameters.model_validate(parameters).model_dump(
                    mode="json"
                )
            for size, seed, backend in itertools.product(
                config.sample_sizes, config.seeds, sweep.backends
            ):
                payload = dict(
                    kind=sweep.kind,
                    algorithm=sweep.algorithm,
                    algorithm_version=adapter.algorithm_version if adapter else None,
                    backend=backend,
                    sample_size=size,
                    seed=seed,
                    parameters=parameters,
                )
                key = hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest()[:16]
                cases.append(RunCase(case_id=key, **payload))
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Sweep defines duplicate effective runs")
    if len(cases) * config.repeats > 2000:
        raise ValueError("Sweep exceeds 2000 timed runs; narrow the parameter space")
    return cases


def synthetic_boards(count, seed):
    """Generate varied eight-unit throughput fixtures with four shared anchors."""
    rng = random.Random(seed)
    boards = []
    for index in range(count):
        family = index % 4
        units = []
        for slot in range(8):
            key = f"anchor-{family}" if slot == 0 else f"unit-{rng.randrange(40)}"
            items = tuple(
                ItemOccurrence(
                    slot=i,
                    item=EntityRef(
                        key=f"item-{rng.randrange(20)}", name="Synthetic item"
                    ),
                )
                for i in range(3 if slot == 0 else rng.randrange(2))
            )
            units.append(
                UnitOccurrence(
                    occurrence_index=slot,
                    unit=EntityRef(key=key, name=key),
                    star_level=rng.choice([1, 2, 2, 2, 3]),
                    items=items,
                )
            )
        boards.append(
            BoardObservation(
                observation_id=f"synthetic-{index:06}",
                level=8,
                units=tuple(units),
                traits=(),
            )
        )
    return tuple(boards)


def load_inputs(config, config_path):
    """Read a frozen board list or snapshot JSON without database access or resampling."""
    if not config.input_path:
        return None, {
            "kind": "synthetic",
            "revision": "synthetic.v1",
            "note": "Throughput fixture; not representative gameplay data",
        }
    path = (config_path.parent / config.input_path).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["boards"] if isinstance(payload, dict) else payload
    boards = tuple(BoardObservation.model_validate(row) for row in rows)
    if len({b.observation_id for b in boards}) != len(boards):
        raise ValueError("Input observations must have unique IDs")
    if len(boards) < max(config.sample_sizes):
        raise ValueError(
            "Input has fewer boards than the largest requested sample; no silent downsampling"
        )
    digest = hashlib.sha256(
        json.dumps([b.model_dump(mode="json") for b in boards], sort_keys=True).encode()
    ).hexdigest()
    return boards, {"kind": "saved", "sha256": digest, "available_boards": len(boards)}


def select_sample(boards, size, seed):
    """Use nested, deterministic samples shared across algorithms and backends."""
    if boards is None:
        return synthetic_boards(size, seed)
    ordered = sorted(boards, key=lambda b: b.observation_id)
    random.Random(seed).shuffle(ordered)
    return tuple(ordered[:size])


def machine_metadata(root):
    """Record hardware and dependency versions without secrets or environment dumps."""
    packages = {}
    for name in ("numpy", "scipy", "hdbscan", "cuml-cu12", "cupy-cuda12x"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            pass

    def git(*args):
        """Read optional revision metadata without making Git a runtime dependency."""
        try:
            return subprocess.check_output(
                ["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    cpu = platform.processor() or platform.machine()
    info = Path("/proc/cpuinfo")
    if info.exists():
        cpu = next(
            (
                line.split(":", 1)[1].strip()
                for line in info.read_text(encoding="utf-8").splitlines()
                if line.startswith("model name")
            ),
            cpu,
        )
    return {
        "python": platform.python_version(),
        "system": platform.system(),
        "cpu": cpu,
        "packages": packages,
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")),
    }


def write_results(output, report):
    """Replace JSON and its standalone HTML view after each finished repetition."""
    from .report import render_report

    output.mkdir(parents=True, exist_ok=True)
    for name, content in (
        ("results.json", json.dumps(report, indent=2, allow_nan=False)),
        ("index.html", render_report(report)),
    ):
        temporary = output / (name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(output / name)
