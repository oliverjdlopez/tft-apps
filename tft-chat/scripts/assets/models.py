"""Manifest records for the standalone asset downloader."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    """Identify a catalogue image and its destination in a download bundle."""

    group: str
    api_name: str
    variant: str
    url: str
    file: str
