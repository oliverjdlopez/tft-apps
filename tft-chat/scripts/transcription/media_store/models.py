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


@dataclass(frozen=True)
class Resource:
    """Describe one immutable shared artifact and its application provenance."""

    id: str
    kind: str
    source: str
    name: str
    content_type: str
    size: int
    sha256: str
    metadata: dict

    @property
    def reference(self) -> str:
        """Return a portable reference usable by either application's store."""
        return "tft-resource:" + self.id
