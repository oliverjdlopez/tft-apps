"""Local Langfuse snapshot discovery for the assistant-spec editor."""
from __future__ import annotations

from pathlib import Path

from .models import EvalSuite


def load_eval_suites() -> list[EvalSuite]:
    """Expose exported suite metadata without requiring the platform or SDK.

    Returns:
        Suite identities, frozen cases, and execution settings for local discovery.
    """
    from .langfuse.content import load_catalog, load_snapshot

    root = Path(__file__).parent / "langfuse" / "snapshots"
    suites = []
    for entry in load_catalog(root):
        bundle = load_snapshot(entry["snapshot"], root)
        suites.append(EvalSuite(entry["name"], entry["assistant"], entry["execution"],
                                bundle["items"], bundle["suite"]))
    return suites
