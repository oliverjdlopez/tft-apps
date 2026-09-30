"""Constants shared by repository resource providers."""

from pathlib import Path

from common.paths import find_repo_root

RESOURCE_DIR = Path(__file__).resolve().parents[2] / "resources"
CONTEXT_DIR = RESOURCE_DIR / "context"
SKILLS_DIR = RESOURCE_DIR / "skills"
ROOT_DIR = find_repo_root(CONTEXT_DIR)
MAX_CONTEXT_SNIPPETS: int | None = None
MAX_CONTEXT_CHARS: int | None = None
MAX_SELECTOR_CANDIDATES: int | None = None
MAX_SELECTOR_CHARS: int | None = None
MAX_SELECTED_SKILLS = 3

__all__ = [
    "CONTEXT_DIR", "MAX_CONTEXT_CHARS", "MAX_CONTEXT_SNIPPETS",
    "MAX_SELECTED_SKILLS", "MAX_SELECTOR_CANDIDATES", "MAX_SELECTOR_CHARS",
    "RESOURCE_DIR", "ROOT_DIR", "SKILLS_DIR",
]
