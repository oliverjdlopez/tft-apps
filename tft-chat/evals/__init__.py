"""ChatTFT evaluation execution, assertions, and platform integration."""
from __future__ import annotations
import sys
from pathlib import Path

# Workers can run from a checkout outside the installed application entrypoint.
backend_src = str(Path(__file__).resolve().parents[1] / "app/backend/src")
if backend_src not in sys.path:
    sys.path.insert(0, backend_src)
