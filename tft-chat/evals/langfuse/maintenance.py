"""Explicit export, migration, and reviewed-baseline maintenance operations."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

from .content import load_catalog, load_snapshot
from .migration import apply_migration, plan_migration
from .native import NativeWorkspace
from .utils import atomic_write, canonical_json, configured_workspace


def migrate_workspace(destination: Path, *, apply: bool = False) -> dict:
    """Export once, prepare a lossless plan, and optionally resume its application."""
    from dotenv import dotenv_values
    import domain.assistants
    from domain.providers.skills import _discover_skills
    root = Path(__file__).parent
    workspace = configured_workspace()
    destination.mkdir(parents=True, exist_ok=True)
    backup_path = destination / 'before-natural-workspace.json'
    plan_path = destination / 'natural-migration-plan.json'
    try:
        backup = json.loads(backup_path.read_text()) if backup_path.exists() else export_complete_workspace(backup_path)
        if plan_path.exists():
            plan = json.loads(plan_path.read_text())
        else:
            suites = {entry['name']: load_snapshot(entry['snapshot'], root / 'snapshots')['suite']
                      for entry in load_catalog(root / 'snapshots')}
            plan = plan_migration(backup, suites, available_skills={skill.name for skill in _discover_skills()})
            atomic_write(plan_path, canonical_json(plan))
        if not apply:
            return {'plan': str(plan_path), 'datasets': len(plan['datasets']), 'assertions': len(plan['assertions'])}
        local = {**dotenv_values(root / '.env'), **os.environ}
        native = NativeWorkspace(local.get('LANGFUSE_BASE_URL', 'http://localhost:15510'),
                                 local['LANGFUSE_INIT_USER_EMAIL'], local['LANGFUSE_INIT_USER_PASSWORD'],
                                 local.get('LANGFUSE_PROJECT_ID', 'tft-apps-evals'))
        try:
            result = apply_migration(workspace, native, plan, destination / 'natural-migration-journal.json')
            # Preserve the explicitly production-labelled prompt definition as the
            # initial baseline; never move a baseline to an arbitrary latest edit.
            for prompt in backup['prompts']:
                if prompt['name'] != 'chattft/judge' and 'production' in prompt.get('labels', []):
                    current = workspace.request('GET', 'v2/prompts/' + quote(prompt['name'], safe=''),
                                                params={'version': prompt['version']})
                    if 'baseline' not in current.get('labels', []):
                        workspace.request('PATCH', f"v2/prompts/{quote(prompt['name'], safe='')}/versions/{prompt['version']}",
                                          json={'newLabels': sorted((set(current.get('labels', [])) - {'latest'}) | {'baseline'})})
            return result
        finally:
            native.close()
    finally:
        workspace.close()


def record_reviewed_baseline(snapshot: str, reviewer: str, destination: Path) -> None:
    """Record an explicitly reviewed snapshot without promoting passing runs."""
    bundle = load_snapshot(snapshot, Path(__file__).parent / 'snapshots')
    if not reviewer.strip():
        raise ValueError('A baseline review requires an explicit reviewer')
    atomic_write(destination, canonical_json({'snapshot': snapshot, 'reviewer': reviewer,
                                             'suite': bundle['suite']['name'], 'grading': bundle.get('grading')}))


def export_complete_workspace(destination: Path) -> dict:
    """Export active and archived definitions plus public historical results."""
    from .utils import configured_native_workspace
    workspace = configured_workspace()
    native = configured_native_workspace()
    try:
        return workspace.export(destination, native=native)
    finally:
        native.close()
        workspace.close()
