from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from scripts import copy_rds


class _FakeStdout:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakePopen:
    def __init__(self, args: list[str], stdout: object) -> None:
        self.args = args
        self.stdout = _FakeStdout()
        self.returncode = 0

    def wait(self) -> int:
        return self.returncode


def test_copy_rds_database_streams_dump_to_restore(monkeypatch) -> None:
    popen_calls: list[list[str]] = []
    run_calls: list[tuple[list[str], object]] = []
    popen_procs: list[_FakePopen] = []

    def fake_popen(args: list[str], stdout: object) -> _FakePopen:
        popen_calls.append(args)
        proc = _FakePopen(args, stdout)
        popen_procs.append(proc)
        return proc

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        run_calls.append((args, kwargs["stdin"]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(copy_rds, "_require_tool", lambda _name: None)
    monkeypatch.setattr(copy_rds.subprocess, "Popen", fake_popen)

    copy_rds.copy_rds_database(
        copy_rds.CopyOptions(
            source="postgresql://source.example.com/chat_tft",
            destination="postgresql://dest.example.com/chat_tft_eval",
            drop_existing_objects=True,
        ),
        run=fake_run,
    )

    assert popen_calls == [
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            "postgresql://source.example.com/chat_tft",
        ]
    ]
    assert run_calls[0][0] == [
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        "postgresql://dest.example.com/chat_tft_eval",
        "--clean",
        "--if-exists",
    ]
    assert run_calls[0][1] is popen_procs[0].stdout
    assert popen_procs[0].stdout.closed


def test_copy_rds_database_rejects_invalid_jobs(monkeypatch) -> None:
    monkeypatch.setattr(copy_rds, "_require_tool", lambda _name: None)

    with pytest.raises(ValueError, match="jobs"):
        copy_rds.copy_rds_database(
            copy_rds.CopyOptions(
                source="postgresql:///source",
                destination="postgresql:///destination",
                jobs=0,
            )
        )


def test_copy_rds_database_uses_temp_archive_for_parallel_restore(monkeypatch) -> None:
    run_calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        run_calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(copy_rds, "_require_tool", lambda _name: None)

    copy_rds.copy_rds_database(
        copy_rds.CopyOptions(
            source="postgresql:///source",
            destination="postgresql:///destination",
            jobs=2,
        ),
        run=fake_run,
    )

    assert run_calls[0][:6] == [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        "postgresql:///source",
    ]
    assert run_calls[0][-2] == "--file"
    archive_path = run_calls[0][-1]
    assert run_calls[1] == [
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        "postgresql:///destination",
        "--jobs",
        "2",
        archive_path,
    ]


def test_copy_rds_database_redacts_failed_destination_dsn(monkeypatch) -> None:
    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(copy_rds, "_require_tool", lambda _name: None)
    monkeypatch.setattr(copy_rds.subprocess, "Popen", lambda *args, **kwargs: _FakePopen(*args, **kwargs))

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        copy_rds.copy_rds_database(
            copy_rds.CopyOptions(
                source="postgresql://user:secret@source.example.com/chat_tft",
                destination="postgresql://user:secret@dest.example.com/chat_tft_eval",
            ),
            run=fake_run,
        )

    assert exc_info.value.cmd == [
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        "<redacted>",
    ]


def test_copy_rds_database_passes_password_outside_process_arguments(monkeypatch) -> None:
    """Verify a separate libpq password never enters process arguments."""
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(args: list[str], **kwargs: object) -> _FakePopen:
        """Capture the pg_dump invocation and return a successful process."""
        popen_calls.append((args, kwargs))
        return _FakePopen(args, kwargs["stdout"])

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        """Represent a successful pg_restore invocation."""
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(copy_rds, "_require_tool", lambda _name: None)
    monkeypatch.setattr(copy_rds.subprocess, "Popen", fake_popen)

    copy_rds.copy_rds_database(
        copy_rds.CopyOptions(
            source="postgresql://user@source.example.com/chat_tft",
            destination="postgresql:///chat_tft",
        ),
        source_password="secret-token",
        run=fake_run,
    )

    args, kwargs = popen_calls[0]
    assert "secret-token" not in " ".join(args)
    assert kwargs["env"]["PGPASSWORD"] == "secret-token"


def test_dsn_helpers() -> None:
    dsn = "postgresql://user:secret@example.com:5432/chat_tft_eval?sslmode=require"

    assert copy_rds._database_name(dsn) == "chat_tft_eval"
    assert (
        copy_rds._dsn_with_database(dsn, "postgres")
        == "postgresql://user:secret@example.com:5432/postgres?sslmode=require"
    )
    assert (
        copy_rds._dsn_with_database("postgresql:///chat_tft", "postgres")
        == "postgresql:///postgres"
    )
    assert copy_rds._database_name("postgresql:///local%20copy") == "local copy"


def test_database_name_requires_path() -> None:
    with pytest.raises(ValueError, match="database name"):
        copy_rds._database_name("postgresql://example.com")
