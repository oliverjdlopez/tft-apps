"""Load application-local settings before backend modules read environment values."""

from pathlib import Path

from dotenv import load_dotenv

# Shell and desktop-owned settings retain precedence over file defaults.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
