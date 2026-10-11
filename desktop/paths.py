"""Canonical suite roots used by Python desktop import bootstrapping."""
from pathlib import Path

DESKTOP_ROOT = Path(__file__).resolve().parent
SUITE_ROOT = DESKTOP_ROOT.parent
CHAT_ROOT = SUITE_ROOT / "tft-chat"
VOD_ROOT = SUITE_ROOT / "vod-review"
