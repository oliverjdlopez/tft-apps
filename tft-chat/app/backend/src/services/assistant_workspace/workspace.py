"""Draft lifecycle, graph capture, conflict checks, and journaled apply."""
from __future__ import annotations

import base64
import difflib
import json
from pathlib import Path
import time
import uuid

from common.assistant_workspace import atomic_bytes, checkout_lock, recover_locked
from domain.assistants.capture import EDITABLE_FILES, capture, configure, digest, reachable, registry_from_files
from domain.assistants.registry import assistant_registry
from .store import Store


class ConflictError(ValueError):
    """Signal a stale source, runtime, or draft revision without overwriting it."""


class Workspace:
    """Own one checkout's editable drafts independently of active definitions."""
    def __init__(self, root: Path, specs: Path, registry=None):
        """Bind checkout paths and the active registry; initialize runtime storage."""
        self.root = root
        self.specs = specs
        self.registry = registry if registry is not None else assistant_registry
        self.store = Store(root / '.runtime' / 'assistant-workspace')

    def source_files(self) -> dict[str, dict[str, str]]:
        """Read only editable files, refusing symlink and identity escapes."""
        result = {}
        for directory in sorted(self.specs.iterdir()):
            if not directory.is_dir() or not (directory / 'system.md').exists():
                continue
            if directory.is_symlink():
                raise ValueError('Symlinked assistant directories cannot be edited')
            documents = {}
            for filename in EDITABLE_FILES:
                path = directory / filename
                if path.is_symlink():
                    raise ValueError('Symlinked assistant files cannot be edited')
                if path.exists():
                    documents[filename] = path.read_bytes().decode('utf-8')
            result[directory.name] = documents
        return result

    def active(self):
        """Capture the cached registry before inspecting a mutable source tree."""
        return configure(self.registry.snapshot())

    def state(self, name: str) -> dict:
        """Describe active instructions, editable head, source drift, and saved runs."""
        active = self.active()
        spec = active.get_spec(name)
        source = self.source_files()
        graph = capture(active)
        draft = self.store.head(name)
        files = draft['files'] if draft else active.source_files.get(name, source.get(name, {}))
        validation = self.validate(name, files, active)
        differences = {}
        for filename in EDITABLE_FILES:
            old = source.get(name, {}).get(filename, '')
            new = files.get(filename, '')
            if old != new or (filename in source.get(name, {})) != (filename in files):
                differences[filename] = ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile='active/' + filename, tofile='draft/' + filename))
        return {'name': name, 'active': {'hash': graph['hash'], 'files': active.source_files.get(name, {}),
                'instructions': spec.system_prompt, 'configuration': graph['specs'][name]},
                'source_hash': digest(source), 'source_changed': source != active.source_files,
                'draft': draft, 'validation': validation, 'diff': differences,
                'runs': self.store.runs(name), 'history': self.store.history(name), 'configuration': validation.get('configuration')}

    def check(self, name: str, expected_draft: str | None, expected_active: str, expected_source: str) -> tuple:
        """Reject intervening edits across draft, source, and loaded registry."""
        active = self.active()
        active.get_spec(name)
        head = self.store.head(name)
        source = self.source_files()
        if (head['id'] if head else None) != expected_draft:
            raise ConflictError('The saved draft changed. Reload before continuing; your edits are preserved.')
        if capture(active)['hash'] != expected_active:
            raise ConflictError('Active definitions changed. Reload before continuing; the draft is preserved.')
        if digest(source) != expected_source:
            raise ConflictError('Repository files changed. Refresh active definitions and reload; the draft is preserved.')
        return active, head, source

    def validate(self, name: str, files: dict, active=None) -> dict:
        """Validate a complete candidate graph while allowing invalid drafts to save."""
        active = active or self.active()
        inventory = {**active.source_files, name: files}
        try:
            registry = registry_from_files(inventory)
            spec = registry.get_spec(name)
            return {'valid': True, 'errors': [], 'graph_hash': capture(registry)['hash'],
                    'configuration': capture(registry)['specs'][spec.name]}
        except (ValueError, KeyError, TypeError, OSError) as exc:
            return {'valid': False, 'errors': [str(exc)], 'configuration': None}

    def save(self, name: str, files: dict, *, expected_draft: str | None, expected_active: str, expected_source: str, provenance=None) -> dict:
        """Save immutable editable contents without writing application source files."""
        if set(files) - set(EDITABLE_FILES) or 'system.md' not in files:
            raise ValueError('Only system.md, agent.json, and task.md can be saved; system.md is required')
        if any(not isinstance(value, str) or len(value) > 1_000_000 for value in files.values()):
            raise ValueError('Each editable file must be text of at most 1000000 characters')
        with checkout_lock(self.store.root):
            recover_locked(self.store.root, self.specs)
            active, head, source = self.check(name, expected_draft, expected_active, expected_source)
            self.store.save(name, {'files': files, 'content_hash': digest(files),
                'base_active': head['base_active'] if head else capture(active)['hash'],
                'base_source': head['base_source'] if head else digest(source),
                'validation': self.validate(name, files, active), 'provenance': provenance})
        return self.state(name)

    def discard(self, name: str, **expected) -> dict:
        """Close an editable draft without removing its immutable history."""
        with checkout_lock(self.store.root):
            self.check(name, **expected)
            self.store.close(name, 'discarded')
        return self.state(name)

    def restore(self, name: str, revision: str, **expected) -> dict:
        """Create a fresh draft from an earlier saved revision's complete files."""
        old = self.store.revision(revision)
        if old['assistant'] != name:
            raise ValueError('Revision belongs to another assistant')
        # Restoring intentionally rebases onto the current active/source identity.
        with checkout_lock(self.store.root):
            active, _, source = self.check(name, **expected)
            self.store.save(name, {'files': old['files'], 'content_hash': old['content_hash'],
                'base_active': capture(active)['hash'], 'base_source': digest(source),
                'validation': self.validate(name, old['files'], active), 'provenance': {'restored_from': revision}})
        return self.state(name)

    def graphs(self, name: str, entry: str, **expected) -> tuple[dict, dict, dict]:
        """Freeze active and draft graphs with their union of reachable targets."""
        active, head, source = self.check(name, **expected)
        if head is None:
            raise ValueError('Save a draft before testing or applying')
        draft = registry_from_files({**active.source_files, name: head['files']})
        names = sorted(set(reachable(active, entry)) | set(reachable(draft, entry)))
        if name not in names:
            raise ValueError('The edited assistant is not reachable from this workflow')
        names = sorted(set(names) | {target for target in ('context_selector', 'skill_selector') if target in active.list_assistants()})
        return capture(active, names), capture(draft, names), head

    def apply(self, name: str, **expected) -> dict:
        """Stage, validate, journal, replace files, and install a complete snapshot."""
        with checkout_lock(self.store.root):
            recover_locked(self.store.root, self.specs)
            active, head, source = self.check(name, **expected)
            if head is None:
                raise ValueError('Save a draft before applying')
            if head['base_active'] != capture(active)['hash'] or head['base_source'] != digest(source):
                raise ConflictError('The draft started from older definitions. Restore its revision into a new draft to rebase after reviewing changes.')
            # Repository drift is never silently incorporated into the runtime.
            if source != active.source_files:
                raise ConflictError('Refresh active definitions before applying repository changes')
            candidate = registry_from_files({**source, name: head['files']})
            changes = {}
            for filename in EDITABLE_FILES:
                old = source[name].get(filename)
                new = head['files'].get(filename)
                if old != new:
                    changes[filename] = [base64.b64encode(value.encode()).decode() if value is not None else None for value in (old, new)]
            journal = {'id': uuid.uuid4().hex, 'assistant': name, 'revision': head['id'], 'created': time.time(), 'changes': changes}
            path = self.store.root / 'apply-journal.json'
            atomic_bytes(path, json.dumps(journal).encode())
            try:
                # Recheck source bytes after staging, immediately before mutation.
                if self.source_files() != source:
                    raise ConflictError('Repository files changed during staging')
                for filename in changes:
                    content = head['files'].get(filename)
                    atomic_bytes(self.specs / name / filename, content.encode() if content is not None else None)
                self.registry.install(candidate)
                atomic_bytes(path, json.dumps({**journal, 'committed': True}).encode())
            except BaseException:
                recover_locked(self.store.root, self.specs)
                self.registry.install(active)
                raise
            recover_locked(self.store.root, self.specs)
        return self.state(name)

    def refresh(self, expected_active: str, expected_source: str) -> dict:
        """Validate the entire repository graph before explicitly refreshing runtime."""
        with checkout_lock(self.store.root):
            recover_locked(self.store.root, self.specs)
            source = self.source_files()
            if capture(self.active())['hash'] != expected_active or digest(source) != expected_source:
                raise ConflictError('Definitions changed before refresh; reload first')
            candidate = registry_from_files(source)
            if self.source_files() != source:
                raise ConflictError('Repository files changed during refresh')
            self.registry.install(candidate)
        return {'active_hash': capture(self.active())['hash'], 'source_hash': digest(source)}
