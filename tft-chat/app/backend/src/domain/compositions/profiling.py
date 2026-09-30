"""Low-overhead stage and hardware profiling for composition experiments."""

from contextlib import contextmanager
import os
import resource
import time


def hardware_snapshot():
    """Capture process, host, and available CUDA resource counters."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # ru_maxrss is bytes on macOS and KiB on Linux.
    peak_rss = usage.ru_maxrss * (1 if os.uname().sysname == "Darwin" else 1024)
    snapshot = {
        "cpu_count": os.cpu_count(),
        "process_cpu_seconds": usage.ru_utime + usage.ru_stime,
        "process_peak_rss_bytes": peak_rss,
        "host_memory_bytes": _host_memory_bytes(),
    }
    try:
        import cupy as cp

        free, total = cp.cuda.runtime.memGetInfo()
        snapshot["cuda"] = {
            "device": cp.cuda.runtime.getDevice(),
            "free_bytes": int(free),
            "total_bytes": int(total),
            "used_bytes": int(total - free),
        }
    except Exception:
        # Telemetry must remain optional on hosts with partial CUDA installations.
        snapshot["cuda"] = None
    return snapshot


def _host_memory_bytes():
    """Return installed host RAM where the operating system exposes it."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


class CompositionProfiler:
    """Collect named wall-time and resource snapshots for one experiment."""

    def __init__(self):
        """Start an in-memory profile without adding a runtime dependency."""
        self.stages = []
        self.started_at = time.time()
        self.start_resources = hardware_snapshot()

    @contextmanager
    def stage(self, name):
        """Record a stage even when it raises, preserving partial failure evidence."""
        start = time.perf_counter()
        before = hardware_snapshot()
        try:
            yield
        finally:
            after = hardware_snapshot()
            self.stages.append({
                "stage": name,
                "wall_seconds": time.perf_counter() - start,
                "cpu_seconds_delta": after["process_cpu_seconds"] - before["process_cpu_seconds"],
                "peak_rss_bytes": after["process_peak_rss_bytes"],
                "cuda": after["cuda"],
            })

    def report(self):
        """Format the collected stages and host/device resource summary."""
        end = hardware_snapshot()
        lines = [
            "Composition experiment profile",
            f"Started: {self.started_at:.3f} Unix time",
            f"CPU cores: {end['cpu_count']}",
            f"Host RAM: {end['host_memory_bytes']} bytes",
            f"Peak process RSS: {end['process_peak_rss_bytes']} bytes",
            f"Process CPU time: {end['process_cpu_seconds']:.3f} seconds",
            f"CUDA: {end['cuda']}",
            "Stages:",
        ]
        lines.extend(
            f"  {row['stage']}: wall={row['wall_seconds']:.3f}s, "
            f"cpu={row['cpu_seconds_delta']:.3f}s, peak_rss={row['peak_rss_bytes']} bytes, "
            f"cuda={row['cuda']}" for row in self.stages
        )
        return "\n".join(lines) + "\n"
