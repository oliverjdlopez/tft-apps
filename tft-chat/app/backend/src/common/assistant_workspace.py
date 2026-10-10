"""Crash recovery primitives usable before assistant specification discovery."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile


def atomic_bytes(path: Path, data: bytes | None) -> None:
    """Replace or remove one editable file with durable directory metadata."""
    if path.is_symlink():
        raise ValueError('Refusing to replace a symlinked assistant file')
    if data is None:
        path.unlink(missing_ok=True)
    else:
        descriptor, temporary = tempfile.mkstemp(prefix='.workspace-', dir=path.parent)
        try:
            os.fchmod(descriptor, path.stat().st_mode & 0o777 if path.exists() else 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def checkout_lock(runtime: Path):
    """Serialize workspace mutations and recovery across backend processes."""
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'checkout.lock').open('a+b') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def recover_locked(runtime: Path, specs_root: Path) -> None:
    """Roll back an interrupted write without overwriting intervening edits.

    Args:
        runtime: Checkout-owned workspace store directory.
        specs_root: Allowlisted specification directory for this checkout.
    """
    import base64
    import sqlite3
    journal = runtime / 'apply-journal.json'
    if not journal.exists():
        return
    operation = json.loads(journal.read_text())
    name = operation['assistant']
    if Path(name).name != name or name in {'.', '..'}:
        raise ValueError('Invalid recovery identity')
    if operation.get('committed'):
        # Commit intent is durable before closing the draft; finish it exactly
        # once after a crash between source installation and store finalization.
        with sqlite3.connect(runtime / 'workspace.sqlite3') as connection:
            connection.execute('DELETE FROM heads WHERE assistant=? AND revision=?', (name, operation['revision']))
            connection.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)',
                               (operation['id'], name, 'applied', operation['revision'], operation['created']))
    else:
        changes = operation['changes']
        decoded = {}
        for filename, values in changes.items():
            if filename not in {'system.md', 'agent.json', 'task.md'}:
                raise ValueError('Invalid recovery filename')
            path = specs_root / name / filename
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError('Recovery refuses symlinked assistant files')
            old, new = (base64.b64decode(value) if value is not None else None for value in values)
            current = path.read_bytes() if path.exists() else None
            if current not in (old, new):
                raise ValueError('Apply recovery conflicts with an external edit; preserve the journal for review')
            decoded[path] = old
        for path, old in decoded.items():
            atomic_bytes(path, old)
    journal.unlink()


def recover(runtime: Path, specs_root: Path) -> None:
    """Recover interrupted workspace writes before any source discovery."""
    if not (runtime / 'apply-journal.json').exists():
        return
    with checkout_lock(runtime):
        recover_locked(runtime, specs_root)
