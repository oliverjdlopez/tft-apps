"""Validated schedule settings persisted by the creator-import service."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

try:
    from ..models import DownloadQuality, ReplayDiscoveryRequest
except ImportError:  # Backend-directory uvicorn launch.
    from models import DownloadQuality, ReplayDiscoveryRequest
from .utils import is_replay_source_url


class ReplaySchedule(BaseModel):
    """Configure one shared daily import and its rolling publication window."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    sources: list[str] = Field(default_factory=list, max_length=25)
    daily_time: str = Field(default="09:00", min_length=5, max_length=5, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    window_hours: float = Field(default=24, gt=0, le=24 * 90, allow_inf_nan=False)
    quality: DownloadQuality = "720p"

    @model_validator(mode="after")
    def validate_settings(self) -> "ReplaySchedule":
        """Reject invalid zones and sources before they can cause scheduled network work."""
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Choose a valid IANA timezone, such as America/New_York") from exc
        if self.sources:
            self.sources = ReplayDiscoveryRequest(sources=self.sources).sources
            self.sources = [source.rstrip("/") for source in self.sources]
            if len(set(self.sources)) != len(self.sources) or any(not is_replay_source_url(source) for source in self.sources):
                raise ValueError("Use unique YouTube channel or Twitch creator URLs")
        elif self.enabled:
            raise ValueError("Add at least one creator before enabling automatic imports")
        return self
