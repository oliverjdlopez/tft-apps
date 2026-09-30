"""Record site-process filesystem activity in a repository-local text log."""

from contextlib import contextmanager
from contextvars import ContextVar
import builtins
import io
import os
from pathlib import Path
import threading
import time
import uuid

_request_id = ContextVar("disk_profile_request_id", default="background")
_guard = threading.local()
_lock = threading.Lock()
_installed = False
_log_path = None
_native_open = builtins.open
_native_io_open = io.open


def request_scope(request_id):
    """Return a context manager that tags disk activity with an HTTP request ID."""
    return _request_scope(request_id)


@contextmanager
def _request_scope(request_id):
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def _path_text(path):
    """Normalize filesystem arguments without reading file contents."""
    try:
        return os.fsdecode(os.fspath(path))
    except (TypeError, ValueError):
        return repr(path)


def _record(operation, path, started, *, bytes_read=0, bytes_written=0, detail=""):
    """Append one completed disk-operation record using the uninstrumented opener."""
    if _log_path is None or getattr(_guard, "active", False):
        return
    resolved = _path_text(path)
    if resolved == str(_log_path):
        return
    _guard.active = True
    try:
        elapsed = time.perf_counter() - started
        line = (
            f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} "
            f"request={_request_id.get()} pid={os.getpid()} "
            f"thread={threading.current_thread().name} op={operation} "
            f"path={resolved!r} elapsed_seconds={elapsed:.9f} "
            f"bytes_read_estimate={bytes_read} bytes_written_estimate={bytes_written} {detail}\n"
        )
        with _lock:
            with _native_open(_log_path, "a", encoding="utf-8") as log:
                log.write(line)
    except OSError:
        # Profiling output must never interrupt site I/O if the report path fills
        # or becomes unavailable.
        pass
    finally:
        _guard.active = False


class _ProfiledFile:
    """Proxy file methods to summarize a complete open/read/write/close session."""

    def __init__(self, stream, path, mode, started):
        """Wrap an already opened file and retain counters until it closes."""
        self._stream = stream
        self._path = path
        self._mode = mode
        self._opened = started
        self._operations = 0
        self._read_calls = 0
        self._write_calls = 0
        self._read = 0
        self._written = 0
        self._io_seconds = 0.0

    def __enter__(self):
        """Preserve normal context-manager behavior while returning the proxy."""
        self._stream.__enter__()
        return self

    def __exit__(self, *exc):
        """Close the stream and emit its combined I/O summary."""
        return self.close(*exc)

    def __iter__(self):
        """Make line iteration pass through the proxy's measured next operation."""
        return self

    def __next__(self):
        """Measure one line read and count the returned bytes or encoded text."""
        return self._measure("read", lambda: next(self._stream), self._size)

    def _measure(self, kind, operation, amount=None):
        """Time one stream operation and update the session byte counters."""
        started = time.perf_counter()
        try:
            value = operation()
            if kind == "read":
                self._read_calls += 1
                self._read += amount(value)
            elif kind == "write":
                self._write_calls += 1
                self._written += amount(value)
            return value
        finally:
            self._operations += 1
            self._io_seconds += time.perf_counter() - started

    def _size(self, value):
        """Measure byte strings and encoded text without retaining contents."""
        if isinstance(value, str):
            return len(value.encode(getattr(self._stream, "encoding", None) or "utf-8"))
        if isinstance(value, (bytes, bytearray, memoryview)):
            return len(value)
        return 0

    def read(self, *args, **kwargs):
        """Read through the wrapped stream and account returned content bytes."""
        return self._measure("read", lambda: self._stream.read(*args, **kwargs), self._size)

    def readline(self, *args, **kwargs):
        """Read one line and account returned content bytes."""
        return self._measure("read", lambda: self._stream.readline(*args, **kwargs), self._size)

    def readlines(self, *args, **kwargs):
        """Read all remaining lines and account their encoded size."""
        return self._measure(
            "read", lambda: self._stream.readlines(*args, **kwargs),
            lambda rows: sum(self._size(row) for row in rows),
        )

    def write(self, value):
        """Write through the wrapped stream and count the supplied bytes."""
        return self._measure("write", lambda: self._stream.write(value), self._size)

    def writelines(self, lines):
        """Write line sequences and count their encoded content size."""
        materialized = tuple(lines)
        return self._measure(
            "write", lambda: self._stream.writelines(materialized),
            lambda _: sum(self._size(line) for line in materialized),
        )

    def close(self, *exc):
        """Close once and report the accumulated file-session measurements."""
        if self._stream.closed:
            return None
        try:
            return self._stream.close()
        finally:
            _record(
                "file_session", self._path, self._opened,
                bytes_read=self._read, bytes_written=self._written,
                detail=(f"mode={self._mode!r} stream_operations={self._operations} "
                        f"read_calls={self._read_calls} write_calls={self._write_calls} "
                        f"io_seconds={self._io_seconds:.9f}"),
            )

    def __getattr__(self, name):
        """Delegate standard stream attributes not involved in profiling."""
        return getattr(self._stream, name)


def _wrap_open(native_open):
    """Build an open wrapper that times opening and profiles the resulting session."""
    def profiled_open(file, mode="r", *args, **kwargs):
        """Open one path and begin measuring its stream lifetime."""
        started = time.perf_counter()
        try:
            stream = native_open(file, mode, *args, **kwargs)
        except Exception as error:
            _record("open_failed", file, started, detail=f"mode={mode!r} error={type(error).__name__}")
            raise
        return _ProfiledFile(stream, _path_text(file), mode, started)

    profiled_open.__name__ = "open"
    profiled_open.__doc__ = native_open.__doc__
    return profiled_open


def _wrap_os_operation(name, native):
    """Time one path-based operating-system operation and append its outcome."""
    def profiled_operation(path, *args, **kwargs):
        """Delegate one OS call and log timing whether it succeeds or fails."""
        started = time.perf_counter()
        outcome = "ok"
        try:
            return native(path, *args, **kwargs)
        except Exception as error:
            outcome = f"error={type(error).__name__}"
            raise
        finally:
            destination = args[0] if name in {"rename", "replace"} and args else None
            target = f" destination={_path_text(destination)!r}" if destination is not None else ""
            detail = f"outcome={outcome}{target}"
            _record(name, path, started, detail=detail)

    profiled_operation.__name__ = name
    return profiled_operation


def install_disk_profiler(repo_root):
    """Instrument common Python filesystem APIs for the lifetime of the site."""
    global _installed, _log_path
    if _installed:
        return _log_path
    _log_path = Path(repo_root) / "profiles" / "disk_usage.txt"
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    with _native_open(_log_path, "a", encoding="utf-8") as log:
        log.write(f"\nDisk profile started {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")

    builtins.open = _wrap_open(_native_open)
    io.open = _wrap_open(_native_io_open)
    for name in (
        "stat", "lstat", "listdir", "scandir", "access", "mkdir", "makedirs",
        "unlink", "remove", "rmdir", "rename", "replace", "chmod",
    ):
        native = getattr(os, name, None)
        if native is not None:
            setattr(os, name, _wrap_os_operation(name, native))
    _installed = True
    return _log_path


def new_request_id():
    """Create a compact identifier for correlating request filesystem activity."""
    return uuid.uuid4().hex[:12]
