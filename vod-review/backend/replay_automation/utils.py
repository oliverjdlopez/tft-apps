"""Source identity, publication windows, and local daily scheduling utilities."""

from datetime import datetime, time, timedelta, timezone
import math
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo


def is_replay_source_url(value: str) -> bool:
    """Accept creator pages, excluding individual videos and unrelated hosts."""
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme not in {"http", "https"} or parsed.query or parsed.fragment:
        return False
    if host == "youtube.com" or host.endswith(".youtube.com"):
        return bool(parts) and (parts[0].startswith("@") or (parts[0] in {"channel", "c", "user"} and len(parts) >= 2))
    if host == "twitch.tv" or host.endswith(".twitch.tv"):
        return len(parts) == 1 and parts[0].lower() not in {"videos", "directory", "downloads", "settings"}
    return False


def discovery_urls(source: str) -> list[str]:
    """Scan YouTube uploads, completed streams and shorts, or Twitch archives."""
    parsed = urlparse(source)
    base = source.rstrip("/")
    if "youtube.com" in (parsed.hostname or ""):
        if base.rsplit("/", 1)[-1] in {"videos", "streams", "shorts", "featured"}:
            base = base.rsplit("/", 1)[0]
        return [f"{base}/{tab}" for tab in ("videos", "streams", "shorts")]
    return [f"{base}/videos?filter=archives&sort=time"]


def media_identity(url: str) -> str | None:
    """Normalize public video URL variants for automatic/manual deduplication."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if host == "youtu.be" and parts:
        return f"youtube:{parts[0]}"
    if host == "youtube.com" or host.endswith(".youtube.com"):
        identifier = parse_qs(parsed.query).get("v", [None])[0]
        if len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
            identifier = parts[1]
        return f"youtube:{identifier}" if identifier else None
    if (host == "twitch.tv" or host.endswith(".twitch.tv")) and len(parts) == 2 and parts[0] == "videos":
        return f"twitch:{parts[1]}"
    return None


def publication_time(entry: dict) -> datetime | None:
    """Use a precise timestamp; a date alone cannot establish an hourly window."""
    for field in ("timestamp", "release_timestamp"):
        value = entry.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            try:
                return datetime.fromtimestamp(value, timezone.utc)
            except (ValueError, OverflowError, OSError):
                pass
    return None


def daily_occurrence(day, daily_time: str, zone_name: str) -> datetime:
    """Choose the first repeated time and shift a nonexistent time across the DST gap."""
    local = datetime.combine(day, time.fromisoformat(daily_time), ZoneInfo(zone_name))
    return local.astimezone(timezone.utc)


def next_occurrence(after: datetime, daily_time: str, zone_name: str) -> datetime:
    """Find the next daily occurrence strictly after an aware UTC instant."""
    day = after.astimezone(ZoneInfo(zone_name)).date()
    for offset in range(3):
        candidate = daily_occurrence(day + timedelta(days=offset), daily_time, zone_name)
        if candidate > after:
            return candidate
    raise ValueError("Could not determine the next daily occurrence")


def latest_occurrence(now: datetime, daily_time: str, zone_name: str) -> datetime:
    """Coalesce missed days into the most recent elapsed daily occurrence."""
    day = now.astimezone(ZoneInfo(zone_name)).date()
    candidate = daily_occurrence(day, daily_time, zone_name)
    return candidate if candidate <= now else daily_occurrence(day - timedelta(days=1), daily_time, zone_name)
