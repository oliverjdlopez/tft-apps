"""Load runtime round labels independently of retired annotation tooling."""

import json
import os
from pathlib import Path
import re


def load_round_labels() -> tuple[str, ...]:
    """Read validated classifier labels for live processing and round benchmarks.

    Returns:
        The configured label IDs in their original order. VOD_ROUND_LABEL_CONFIG
        can select a custom JSON array; the default is config/round_labels.json.

    Raises:
        RuntimeError: If labels are empty, duplicated, or unsafe identifiers.
    """
    root = Path(__file__).resolve().parent.parent
    path = Path(os.environ.get("VOD_ROUND_LABEL_CONFIG", root / "config/round_labels.json"))
    labels = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(labels, list) or not labels
            or any(not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", label) for label in labels)
            or len(set(labels)) != len(labels)):
        raise RuntimeError("Round labels must be a nonempty JSON array of unique safe label IDs")
    return tuple(labels)
