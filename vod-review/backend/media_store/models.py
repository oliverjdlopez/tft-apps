"""Version-one media catalog request model, shared with vod-review."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaRequest:
    """Describe source timeline coverage and the required media representation."""

    url: str
    kind: str = "audio"
    start: float = 0.0
    end: float | None = None
    profile: str = "audio"
    height: int | None = None
    playable: bool = False
