"""Read-only source fingerprints for preparation and actual worker execution."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess


def source_provenance(root: Path) -> dict[str, str]:
    """Record code/resource identity without copying source bytes or secrets.

    Args:
        root: Checkout root whose tracked and untracked source files are hashed.

    Returns:
        Commit and working-tree fingerprint, with an explicit unavailable fallback.
    """
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
        diff = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL)
        untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=root, stderr=subprocess.DEVNULL)
        fingerprint = hashlib.sha256(diff)
        for raw in sorted(part for part in untracked.split(b'\0') if part):
            path = root / os.fsdecode(raw)
            fingerprint.update(raw + b'\0')
            fingerprint.update(hashlib.sha256(os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()).digest())
        return {'git_revision': revision, 'working_tree_fingerprint': fingerprint.hexdigest()}
    except (OSError, subprocess.CalledProcessError):
        return {'git_revision': os.environ.get('CHAT_TFT_GIT_REVISION', 'unavailable'),
                'working_tree_fingerprint': os.environ.get('CHAT_TFT_WORKING_TREE_FINGERPRINT', 'unavailable')}
