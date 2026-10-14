"""Bounded remote frame sampling and coarse-to-fine YouTube/Twitch round analysis."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse, urljoin
from urllib.request import Request, urlopen

import numpy as np

try:
    from .processor import RoundTransitionDetector, box_to_pixels
except ImportError:  # Standalone uvicorn app:app startup.
    from processor import RoundTransitionDetector, box_to_pixels

ANALYSIS_VERSION = 1
NETWORK_TIMEOUT = 20


def canonical_source(url: str) -> tuple[str, str]:
    """Validate a YouTube or Twitch VOD URL and return its stable identity and URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError("Online mode requires a public YouTube or Twitch VOD URL")
    if host in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}:
        match = re.fullmatch(r"/(?:videos/|[^/]+/video/)([0-9]+)/?", parsed.path)
        if not match:
            raise ValueError("Online mode requires a Twitch VOD URL, not a live channel or clip")
        return f"twitch:{match[1]}", f"https://www.twitch.tv/videos/{match[1]}"
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = parsed.path.split("/")[2]
        else:
            video_id = ""
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Online mode requires a YouTube video URL, not a playlist or channel")
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


def _resolve(url: str, quality: str) -> dict[str, Any]:
    """Resolve temporary transport details without persisting signed URLs."""
    import yt_dlp

    source_id, canonical = canonical_source(url)
    height = int(str(quality).removesuffix("p")) if str(quality).removesuffix("p").isdigit() else 720
    twitch = source_id.startswith("twitch:")
    with yt_dlp.YoutubeDL({
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "socket_timeout": NETWORK_TIMEOUT, "retries": 1, "extractor_retries": 1,
        "js_runtimes": {"deno": {}, "node": {}},
        "format": f"best[height<={height}][protocol=m3u8_native]/best[height<={height}][protocol=m3u8]" if twitch else f"bestvideo[ext=mp4][height<={height}][protocol=https]/best[ext=mp4][height<={height}][protocol=https]",
    }) as downloader:
        info = downloader.extract_info(canonical, download=False)
    if not info or info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
        raise ValueError("Online analysis requires a completed prerecorded video")
    resolved_id = str(info.get("id", "")).removeprefix("v") if twitch else info.get("id")
    if resolved_id != source_id.removeprefix("twitch:"):
        raise ValueError("Resolved video identity does not match the requested source")
    duration = float(info.get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0 or not info.get("url"):
        raise ValueError("No seekable video representation is available; use Offline mode")
    transport = urlparse(info["url"])
    if transport.scheme != "https" or info.get("protocol") not in {None, "https", "http", "m3u8_native", "m3u8"}:
        raise ValueError("No seekable HTTPS video representation is available; use Offline mode")
    if not info.get("width") or not info.get("height") or int(info["width"]) <= 0 or int(info["height"]) <= 0:
        raise ValueError("Video dimensions are unavailable; use Offline mode")
    return info


def resolve_metadata(url: str, quality: str = "720p") -> dict[str, Any]:
    """Return stable metadata for a public, completed YouTube video or Twitch VOD."""
    source_id, source_url = canonical_source(url)
    info = _resolve(source_url, quality)
    return {"source_id": source_id, "source_url": source_url,
            "original_name": str(info.get("title") or source_id),
            "duration": float(info["duration"]), "width": int(info.get("width") or 1280),
            "height": int(info.get("height") or 720)}


class _RangeReader:
    """Expose a remote byte-range source as a bounded seekable decoder input."""

    chunk_size = 256 * 1024

    def __init__(self, url: str, headers: dict[str, str]):
        self._url = url
        self._headers = dict(headers)
        self._position = 0
        self._buffer = b""
        self._buffer_start = 0
        self.closed = False
        with self._request(0, 0) as response:
            match = re.fullmatch(r"bytes 0-0/(\d+)", response.headers.get("Content-Range", ""))
            if not match:
                raise RuntimeError("Source does not support bounded range requests; use Offline mode")
            self._length = int(match.group(1))
            response.read(1)

    def _request(self, start: int, end: int) -> Any:
        headers = {**self._headers, "Range": f"bytes={start}-{end}"}
        try:
            response = urlopen(Request(self._url, headers=headers), timeout=NETWORK_TIMEOUT)
        except Exception:
            raise RuntimeError("Remote byte-range request failed; retry or choose Offline mode") from None
        if response.status != 206:
            response.close()
            raise RuntimeError("Source does not support bounded range requests; use Offline mode")
        return response

    def read(self, size: int = -1) -> bytes:
        """Read at most one bounded chunk, caching adjacent decoder reads."""
        if self.closed:
            raise ValueError("Remote reader is closed")
        if self._position >= self._length or size == 0:
            return b""
        size = min(size if size >= 0 else self.chunk_size, self.chunk_size)
        if not self._buffer_start <= self._position < self._buffer_start + len(self._buffer):
            end = min(self._length - 1, self._position + self.chunk_size - 1)
            with self._request(self._position, end) as response:
                expected = f"bytes {self._position}-{end}/{self._length}"
                if response.headers.get("Content-Range") != expected:
                    raise RuntimeError("Remote source returned an inconsistent byte range")
                self._buffer = response.read(end - self._position + 1)
                if len(self._buffer) != end - self._position + 1:
                    raise RuntimeError("Remote byte-range response was incomplete")
                self._buffer_start = self._position
        offset = self._position - self._buffer_start
        data = self._buffer[offset:offset + size]
        self._position += len(data)
        return data

    def seek(self, offset: int, whence: int = 0) -> int:
        """Move within the remote resource without sequentially reading it."""
        position = offset if whence == 0 else self._position + offset if whence == 1 else self._length + offset if whence == 2 else -1
        if position < 0:
            raise ValueError("Invalid remote seek")
        self._position = position
        return position

    def tell(self) -> int:
        """Return the current byte position."""
        return self._position

    def seekable(self) -> bool:
        """Identify this byte-range input as seekable to PyAV."""
        return True

    def readable(self) -> bool:
        """Identify this input as readable to PyAV."""
        return True

    def writable(self) -> bool:
        """Identify this input as read-only to PyAV."""
        return False

    def close(self) -> None:
        """Release buffered bytes and transient transport credentials."""
        self.closed = True
        self._buffer = b""
        self._url = ""
        self._headers.clear()


class _HlsVideo:
    """Read bounded unencrypted MPEG-TS VOD segments on the playlist timeline."""

    def __init__(self, url: str, headers: dict[str, str]):
        self.headers = headers
        playlist = self._fetch(url, 4 * 1024 * 1024).decode("utf-8")
        if not playlist.startswith("#EXTM3U") or "#EXT-X-ENDLIST" not in playlist:
            raise RuntimeError("Online HLS requires a completed VOD; use Offline mode")
        # Twitch publishes independent MPEG-TS segments. Reject layouts that need
        # encryption, initialization fragments or partial byte-range assembly.
        if any(tag in playlist for tag in ("#EXT-X-KEY", "#EXT-X-MAP", "#EXT-X-BYTERANGE")):
            raise RuntimeError("Unsupported HLS layout; use Offline mode")
        self.segments = []
        elapsed = 0.0
        duration = None
        for line in playlist.splitlines():
            line = line.strip()
            if line.startswith("#EXTINF:"):
                duration = float(line.split(":", 1)[1].split(",", 1)[0])
                if not math.isfinite(duration) or duration <= 0:
                    raise RuntimeError("Invalid HLS segment duration")
            elif line and not line.startswith("#"):
                if duration is None:
                    raise RuntimeError("Invalid HLS media playlist")
                segment_url = urljoin(url, line)
                if urlparse(segment_url).scheme != "https":
                    raise RuntimeError("HLS segments must use HTTPS")
                self.segments.append((elapsed, duration, segment_url))
                elapsed += duration
                duration = None
        if not self.segments:
            raise RuntimeError("Empty HLS media playlist")
        self.cached = None

    def _fetch(self, url: str, limit: int) -> bytes:
        """Fetch a bounded playlist or segment without retaining signed URLs."""
        try:
            with urlopen(Request(url, headers=self.headers), timeout=NETWORK_TIMEOUT) as response:
                payload = response.read(limit + 1)
        except Exception:
            raise RuntimeError("HLS resource unavailable; retry or choose Offline mode") from None
        if len(payload) > limit:
            raise RuntimeError("HLS resource exceeded its download budget")
        return payload

    def frame(self, video: dict[str, Any], timestamp: float) -> tuple[np.ndarray, float]:
        """Decode the selected segment and at most its immediate successor."""
        import av

        start = float(video.get("source_start_seconds") or 0)
        end = start + float(video["duration"])
        target = start + timestamp
        index = next((i for i, (offset, duration, _) in enumerate(self.segments)
                      if offset <= target < offset + duration), None)
        if index is None:
            raise RuntimeError("Timestamp is outside the HLS playlist")
        last = None
        begun = time.monotonic()
        for offset, duration, url in self.segments[index:index + 2]:
            if offset >= end:
                break
            if self.cached is None or self.cached[0] != url:
                self.cached = (url, self._fetch(url, 64 * 1024 * 1024))
            with av.open(io.BytesIO(self.cached[1])) as container:
                stream = container.streams.video[0]
                # MPEG-TS PTS may start far from zero or reset at discontinuities.
                # The playlist supplies source time; stream start supplies local time.
                origin = stream.start_time
                for count, frame in enumerate(container.decode(stream)):
                    if count >= 1800 or time.monotonic() - begun > NETWORK_TIMEOUT:
                        raise RuntimeError("HLS sample exceeded its decode budget")
                    if frame.pts is None:
                        continue
                    if origin is None:
                        origin = frame.pts
                    actual = offset + float((frame.pts - origin) * frame.time_base)
                    if actual >= min(end, offset + duration):
                        break
                    if actual >= start:
                        last = (frame.to_ndarray(format="rgb24"), actual - start)
                        if actual + 1e-6 >= target:
                            return last
        if last is not None:
            return last
        raise RuntimeError("No frame found in HLS sample")


class RemoteVideo:
    """Seek a resolved remote video with bounded decode and transport retries."""

    def __init__(self, video: dict[str, Any]):
        self.video = video
        self.container = None
        self._reader = None
        self.stream = None
        self._hls = None
        # The selected representation policy and resolved dimensions identify
        # crops independently of expiring signed URLs. Opening stays lazy so
        # cached OCR reruns do not need a network connection.
        transport = "hls" if str(video.get("source_id", "")).startswith("twitch:") else "mp4"
        self.representation = f"{transport}-{video.get('source_quality') or video.get('quality') or '720p'}-{video.get('width', '')}x{video.get('height', '')}"

    def __enter__(self) -> "RemoteVideo":
        return self

    def __exit__(self, *args: Any) -> None:
        self._hls = None
        if self.container is not None:
            self.container.close()
            self.container = None
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    def _open(self) -> None:
        import av

        self.__exit__()
        info = _resolve(self.video["source_url"], self.video.get("source_quality") or self.video.get("quality") or "720p")
        if info.get("protocol") in {"m3u8_native", "m3u8"}:
            self._hls = _HlsVideo(info["url"], info.get("http_headers", {}))
            return
        try:
            self._reader = _RangeReader(info["url"], info.get("http_headers", {}))
            self.container = av.open(self._reader, buffer_size=32768)
        except Exception as exc:
            self.__exit__()
            if isinstance(exc, RuntimeError):
                raise
            # Native decoder errors can contain transport details.
            raise RuntimeError("Remote decoder could not open the source; retry or choose Offline mode") from None
        try:
            self.stream = self.container.streams.video[0]

        except Exception:
            self.__exit__()
            raise

    def frame(self, review_timestamp: float) -> tuple[np.ndarray, float]:
        """Decode the first frame at/after a review-relative sample timestamp."""
        if not math.isfinite(review_timestamp) or review_timestamp < 0 or review_timestamp >= float(self.video["duration"]):
            raise ValueError("Sample timestamp must be inside the review")
        if self.container is None and self._hls is None:
            self._open()
        if self._hls is not None:
            for attempt in range(2):
                try:
                    return self._hls.frame(self.video, review_timestamp)
                except Exception:
                    if attempt:
                        raise RuntimeError("Remote HLS frame unavailable; retry or choose Offline mode") from None
                    self._open()
        source_start = float(self.video.get("source_start_seconds") or 0)
        source_end = source_start + float(self.video["duration"])
        target = source_start + review_timestamp
        for attempt in range(2):
            try:
                stream = self.stream
                start = int(stream.start_time or 0)
                self.container.seek(int(target / float(stream.time_base)) + start, stream=stream,
                                    backward=True, any_frame=False)
                begun = time.monotonic()
                last_valid = None
                for count, frame in enumerate(self.container.decode(stream)):
                    if count >= 1800 or time.monotonic() - begun > NETWORK_TIMEOUT:
                        raise RuntimeError("Remote seek exceeded its decode budget")
                    if frame.pts is None:
                        continue
                    actual = float((frame.pts - start) * frame.time_base)
                    if actual >= source_end:
                        break
                    if actual >= source_start:
                        last_valid = (frame, actual)
                        if actual + 1e-6 >= target:
                            return frame.to_ndarray(format="rgb24"), actual - source_start
                # The final scheduled sample can fall after the last encoded
                # frame. Preserve its actual PTS without crossing the range.
                if last_valid is not None:
                    frame, actual = last_valid
                    return frame.to_ndarray(format="rgb24"), actual - source_start
                raise RuntimeError("No frame found at the requested timestamp")
            except Exception as exc:
                if attempt:
                    raise RuntimeError("Remote frame unavailable; retry or choose Offline mode") from exc
                self._open()
        raise AssertionError("unreachable")


def fetch_preview(video: dict[str, Any], timestamp: float) -> tuple[np.ndarray, float]:
    """Fetch one preview frame without downloading a local video."""
    with RemoteVideo(video) as source:
        return source.frame(timestamp)


def _transitions(observations: dict[float, tuple[float, str, float]]) -> list[tuple[float, float, str, float]]:
    """Confirm consecutive observations, retaining the label across sparse gaps."""
    detector = RoundTransitionDetector()
    previous = None
    emitted = []
    seen_frames: set[float] = set()
    ordered = sorted(observations.items())
    scheduled_by_observation = {(actual, label): scheduled for scheduled, (actual, label, _) in reversed(ordered)}
    for scheduled, (actual, label, confidence) in ordered:
        # Several scheduled seeks can resolve to one final/low-FPS frame;
        # repeated pixels must not supply independent confirmation votes.
        if actual in seen_frames:
            continue
        seen_frames.add(actual)
        if previous is not None and scheduled - previous > 1.000001:
            detector.reset_window()
        result = detector.observe(actual, label, confidence)
        if result:
            stamp, selected, certainty = result
            supporting = scheduled_by_observation.get((stamp, selected), scheduled)
            emitted.append((supporting, stamp, selected, certainty))
        previous = scheduled
    return emitted


def analyze_online(video: dict[str, Any], box: dict[str, float], batch_size: int,
                   interval: float, classifier: Any, cache_dir: Path,
                   on_progress: Callable[[str, int, int], None],
                   on_results: Callable[[list[tuple[float, float, str, float]]], None],
                   reuse_cached: bool = False) -> tuple[int, str]:
    """Analyze coarse samples, then refine observed label changes at one second.

    Args:
        video: Stable source metadata with review-relative duration and range.
        box: Normalized analysis crop.
        batch_size: Maximum OCR batch size.
        interval: Positive coarse sample spacing (ten seconds by default in UI).
        classifier: Existing OCR classifier.
        cache_dir: App-owned cache directory, separate from shared media.
        on_progress: Receives scanning/refining phase and sample counts.
        on_results: Receives chronological cumulative confirmed transitions.
        reuse_cached: Rerun OCR using saved crops instead of saved predictions.

    Returns:
        Number of observed samples and classifier device label.
    """
    duration = float(video["duration"])
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(interval) or interval < 1 or batch_size < 1:
        raise ValueError("Online analysis requires a positive duration and interval of at least one second")
    observations: dict[float, tuple[float, str, float]] = {}
    with RemoteVideo(video) as source:
        identity = {"version": ANALYSIS_VERSION, "source": video["source_id"],
                    "start": video.get("source_start_seconds", 0), "duration": duration,
                    "representation": source.representation, "quality": video.get("source_quality") or video.get("quality") or "720p",
                    "crop": {k: box[k] for k in ("x", "y", "width", "height")}}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        directory = Path(cache_dir) / digest
        directory.mkdir(parents=True, exist_ok=True)

        def collect(times: list[float], phase: str) -> None:
            """Fetch missing crops and persist complete observations per sample."""
            total = len(times)
            on_progress(phase, 0, total)
            for offset in range(0, total, batch_size):
                pending = []
                for scheduled in times[offset:offset + batch_size]:
                    if scheduled in observations:
                        continue
                    name = f"{scheduled:.6f}"
                    record_path, crop_path = directory / f"{name}.json", directory / f"{name}.npy"
                    record = None
                    try:
                        record = json.loads(record_path.read_text())
                        if not isinstance(record, dict) or not isinstance(record.get("actual"), (float, int)):
                            raise ValueError("Invalid observation cache")
                        if not math.isfinite(record["actual"]) or not 0 <= record["actual"] < duration:
                            raise ValueError("Cached timestamp outside review")
                        if "label" in record and (not isinstance(record["label"], str)
                                                   or not isinstance(record.get("confidence"), (float, int))
                                                   or not math.isfinite(record["confidence"])):
                            raise ValueError("Invalid cached OCR observation")
                        crop = np.load(crop_path, allow_pickle=False)
                        if crop.ndim != 3 or crop.shape[2] != 3 or not crop.size:
                            raise ValueError("Invalid crop cache")
                    except (OSError, ValueError, KeyError):
                        frame, actual = source.frame(scheduled)
                        x0, y0, x1, y1 = box_to_pixels(box, frame.shape[1], frame.shape[0])
                        crop = frame[y0:y1, x0:x1].copy()
                        np.save(crop_path, crop, allow_pickle=False)
                        record = {"actual": actual}
                    if not reuse_cached and "label" in record and "confidence" in record:
                        observations[scheduled] = (record["actual"], record["label"], record["confidence"])
                    else:
                        pending.append((scheduled, crop, record, record_path))
                predictions = classifier.predict_batch([item[1] for item in pending]) if pending else []
                for (scheduled, _, record, path), (label, confidence) in zip(pending, predictions, strict=True):
                    record.update(label=str(label), confidence=float(confidence))
                    temporary = path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(record))
                    temporary.replace(path)
                    observations[scheduled] = (float(record["actual"]), str(label), float(confidence))
                on_progress(phase, min(total, offset + batch_size), total)
                if phase == "refining":
                    on_results(_transitions(observations))

        end = max(0.0, round(duration - min(0.1, duration / 2), 6))
        coarse = sorted(set([round(n * interval, 6) for n in range(math.ceil(duration / interval))] + [end]))
        collect(coarse, "scanning")
        readable = [t for t in coarse if observations[t][1] != "unknown"]
        windows = []
        if readable:
            windows.append((max(0, readable[0] - 1), min(end, readable[0] + 2)))
        for left, right in zip(readable, readable[1:]):
            if observations[left][1] != observations[right][1]:
                windows.append((max(0, left - 1), min(end, right + 2)))
        refinement = set()
        for left, right in windows:
            refinement.update(float(t) for t in range(math.ceil(left), math.floor(right) + 1))
        collect(sorted(refinement - observations.keys()), "refining")
        on_results(_transitions(observations))
    return len(observations), str(classifier.device_label)
