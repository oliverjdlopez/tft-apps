"""Remote transport and sparse round detector regression tests."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading

import numpy as np
import pytest

from backend import online

REAL_REMOTE_VIDEO = online.RemoteVideo


@pytest.mark.parametrize("url", [
    "https://youtu.be/abcdefghijk?t=40", "https://www.youtube.com/watch?v=abcdefghijk&list=x",
    "https://youtube.com/shorts/abcdefghijk", "https://youtube.com/live/abcdefghijk",
])
def test_canonical_source(url):
    assert online.canonical_source(url) == ("abcdefghijk", "https://www.youtube.com/watch?v=abcdefghijk")


@pytest.mark.parametrize("url", [
    "https://youtube.com.evil.test/watch?v=abcdefghijk", "file:///tmp/video.mp4",
    "https://youtube.com/playlist?list=abcdefghijk", "https://user@youtube.com/watch?v=abcdefghijk",
    "https://youtu.be/short", "https://youtube.com/channel/abcdefghijk",
])
def test_reject_untrusted_or_non_video_sources(url):
    with pytest.raises(ValueError):
        online.canonical_source(url)


def test_metadata_never_returns_transport_secrets(monkeypatch):
    monkeypatch.setattr(online, "_resolve", lambda *args: {
        "title": "A TFT replay", "duration": 90, "width": 640, "height": 360,
        "url": "https://signed.test/video?secret=123", "http_headers": {"Authorization": "secret"},
    })
    metadata = online.resolve_metadata("https://youtu.be/abcdefghijk")
    assert metadata == {"source_id": "abcdefghijk", "source_url": "https://www.youtube.com/watch?v=abcdefghijk",
                        "original_name": "A TFT replay", "duration": 90.0, "width": 640, "height": 360}


class FakeRemote:
    calls = []
    representation = "137"

    def __init__(self, video):
        self.video = video

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def frame(self, timestamp):
        self.calls.append(timestamp)
        # Integer sample position is encoded in the crop for deterministic OCR.
        return np.full((8, 8, 3), int(timestamp), np.uint8), timestamp + 0.02


class FakeClassifier:
    device_label = "test-cpu"

    def __init__(self, label):
        self.label = label
        self.calls = 0

    def predict_batch(self, crops):
        self.calls += len(crops)
        return [(self.label(int(crop[0, 0, 0])), .9) for crop in crops]


VIDEO = {"source_id": "abcdefghijk", "source_url": "https://www.youtube.com/watch?v=abcdefghijk", "duration": 31.0}
BOX = {"x": 0, "y": 0, "width": 1, "height": 1}


def run_analysis(monkeypatch, tmp_path, label, video=None, reuse=False):
    FakeRemote.calls = []
    monkeypatch.setattr(online, "RemoteVideo", FakeRemote)
    classifier = FakeClassifier(label)
    results, progress = [], []
    summary = online.analyze_online(video or VIDEO, BOX, 4, 10, classifier, tmp_path,
                                    lambda *args: progress.append(args), lambda rows: results.append(rows), reuse)
    return summary, results, progress, classifier


def test_refines_raw_coarse_changes_and_confirms_first_round(monkeypatch, tmp_path):
    summary, results, progress, _ = run_analysis(monkeypatch, tmp_path, lambda t: "21" if t < 13 else "22")
    assert [row[2] for row in results[-1]] == ["21", "22"]
    assert results[-1][1][:2] == (13.0, 13.02)
    assert summary[1] == "test-cpu"
    assert {p[0] for p in progress} == {"scanning", "refining"}
    assert len(FakeRemote.calls) == len(set(FakeRemote.calls))
    assert {0., 10., 20., 30., 30.9}.issubset(FakeRemote.calls)


def test_multiple_changes_and_game_reset_inside_refinement(monkeypatch, tmp_path):
    def label(t):
        return "71" if t < 13 else "72" if t < 17 else "11"
    _, results, _, _ = run_analysis(monkeypatch, tmp_path, label)
    assert [r[2] for r in results[-1]] == ["71", "72", "11"]


def test_unknown_coarse_gap_refines_between_readable_labels(monkeypatch, tmp_path):
    def label(t):
        return "unknown" if t == 10 else "21" if t < 15 else "22"
    _, results, _, _ = run_analysis(monkeypatch, tmp_path, label)
    assert [r[2] for r in results[-1]] == ["21", "22"]
    assert results[-1][1][0] == 15


def test_isolated_error_does_not_create_transition(monkeypatch, tmp_path):
    _, results, _, _ = run_analysis(monkeypatch, tmp_path, lambda t: "22" if t == 10 else "21")
    assert [r[2] for r in results[-1]] == ["21"]


def test_no_vote_across_sparse_gaps():
    assert online._transitions({0.: (0., "21", .9), 10.: (10., "21", .9), 20.: (20., "21", .9)}) == []
    rows = online._transitions({0.: (0., "21", .9), 1.: (1., "21", .9), 2.: (2., "21", .9),
                               10.: (10., "21", .9), 11.: (11., "21", .9), 12.: (12., "21", .9)})
    assert len(rows) == 1


def test_unknown_source_produces_no_invented_rounds(monkeypatch, tmp_path):
    _, results, _, _ = run_analysis(monkeypatch, tmp_path, lambda _: "unknown")
    assert results[-1] == []
    assert len(FakeRemote.calls) == 5


def test_cache_reuses_crops_predictions_and_reruns_ocr(monkeypatch, tmp_path):
    _, first, _, _ = run_analysis(monkeypatch, tmp_path, lambda _: "21")
    _, second, _, classifier = run_analysis(monkeypatch, tmp_path, lambda _: "22")
    assert second[-1] == first[-1]
    assert FakeRemote.calls == [] and classifier.calls == 0
    _, third, _, classifier = run_analysis(monkeypatch, tmp_path, lambda _: "22", reuse=True)
    assert third[-1][0][2] == "22"
    assert FakeRemote.calls == [] and classifier.calls > 0
    assert "signed" not in "".join(p.read_text() for p in tmp_path.rglob("*.json"))


def test_range_and_crop_are_part_of_cache_identity(monkeypatch, tmp_path):
    run_analysis(monkeypatch, tmp_path, lambda _: "21")
    run_analysis(monkeypatch, tmp_path, lambda _: "21", video={**VIDEO, "source_start_seconds": 40})
    assert FakeRemote.calls
    assert len(list(tmp_path.iterdir())) == 2


def test_short_video_confirmed_with_local_neighbors(monkeypatch, tmp_path):
    _, results, _, _ = run_analysis(monkeypatch, tmp_path, lambda _: "21", video={**VIDEO, "duration": 2.9})
    assert [r[2] for r in results[-1]] == ["21"]


@contextmanager
def range_server(payload, support_ranges=True):
    """Serve a small video with actual HTTP byte-range semantics for PyAV."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            header = self.headers.get("Range")
            requests.append(header)
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", header or "")
            if match and support_ranges:
                start = int(match.group(1))
                end = min(int(match.group(2)) if match.group(2) else len(payload) - 1, len(payload) - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
                data = payload[start:end + 1]
            else:
                self.send_response(200)
                data = payload
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/video.mp4", requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def make_video(path):
    av = pytest.importorskip("av")
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
        for index in range(60):
            frame = av.VideoFrame.from_ndarray(np.full((32, 32, 3), index * 3, np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path.read_bytes()


def test_actual_http_seeking_preserves_range_offset(monkeypatch, tmp_path):
    payload = make_video(tmp_path / "fixture.mp4")
    with range_server(payload) as (url, requests):
        monkeypatch.setattr(online, "_resolve", lambda *args: {"url": url, "format_id": "test", "http_headers": {}})
        with online.RemoteVideo({**VIDEO, "duration": 3, "source_start_seconds": 2}) as source:
            frame, actual = source.frame(1.1)
            assert frame.shape == (32, 32, 3)
            assert actual == pytest.approx(1.1, abs=.1)
            assert np.mean(frame) == pytest.approx(31 * 3, abs=5)
            _, earlier = source.frame(.2)
            assert earlier == pytest.approx(.2, abs=.1)
            _, last = source.frame(2.99)
            assert last < 3
            assert last == pytest.approx(2.9, abs=.05)
        assert requests[0] == "bytes=0-0"
        assert all(requests)


def test_non_range_server_rejected_before_decoder(monkeypatch):
    with range_server(b"x" * 100, support_ranges=False) as (url, requests):
        monkeypatch.setattr(online, "_resolve", lambda *args: {"url": url})
        with pytest.raises(RuntimeError, match="range requests"):
            with online.RemoteVideo(VIDEO) as source:
                source.frame(0)
        assert requests == ["bytes=0-0"]


def test_remote_seek_retries_only_once(monkeypatch):
    class BrokenContainer:
        def seek(self, *args, **kwargs):
            raise OSError("expired")
    source = online.RemoteVideo(VIDEO)
    source.container = BrokenContainer()
    source.stream = type("Stream", (), {"start_time": 0, "time_base": .1})()
    opens = []
    monkeypatch.setattr(source, "_open", lambda: opens.append(True))
    with pytest.raises(RuntimeError, match="Offline"):
        source.frame(1)
    assert len(opens) == 1


def test_corrupt_record_recovers_sample(monkeypatch, tmp_path):
    run_analysis(monkeypatch, tmp_path, lambda _: "21")
    for path in tmp_path.rglob("*.json"):
        path.write_text("[]")
    _, results, _, _ = run_analysis(monkeypatch, tmp_path, lambda _: "21")
    assert FakeRemote.calls
    assert results[-1][0][2] == "21"


def test_cached_ocr_rerun_requires_no_transport(monkeypatch, tmp_path):
    monkeypatch.setattr(FakeRemote, "representation", "mp4-720p-x")
    run_analysis(monkeypatch, tmp_path, lambda _: "21")
    monkeypatch.setattr(online, "RemoteVideo", REAL_REMOTE_VIDEO)
    def unavailable(*args):
        raise AssertionError("Cached OCR rerun must not resolve a source")
    monkeypatch.setattr(online, "_resolve", unavailable)
    results = []
    classifier = FakeClassifier(lambda _: "21")
    online.analyze_online(VIDEO, BOX, 4, 10, classifier, tmp_path, lambda *args: None,
                          results.append, reuse_cached=True)
    assert results[-1][0][2] == "21"
    assert classifier.calls > 0


def test_duplicate_actual_frames_do_not_supply_extra_votes():
    assert online._transitions({0.: (0., "21", .9), .5: (0., "21", .9), 1.: (1., "21", .9)}) == []


def test_range_reader_requests_bounded_chunks_and_reuses_buffer():
    payload = bytes(range(256)) * 4096
    with range_server(payload) as (url, requests):
        reader = online._RangeReader(url, {})
        assert reader.read(10) == payload[:10]
        assert reader.read(10) == payload[10:20]
        assert len(requests) == 2
        reader.seek(700000)
        assert reader.read(10) == payload[700000:700010]
        assert requests[-1] == f"bytes=700000-{700000 + reader.chunk_size - 1}"
        assert reader.seek(-10, 2) == len(payload) - 10
        assert reader.read(100) == payload[-10:]
        assert reader.read(100) == b""
        reader.close()
        assert reader._url == "" and reader._headers == {}
        with pytest.raises(ValueError, match="closed"):
            reader.read(1)


def test_resolver_enables_available_node_without_runtime_script_downloads(monkeypatch):
    import sys
    from types import SimpleNamespace
    captured = {}
    class Downloader:
        def __init__(self, options):
            captured.update(options)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            assert download is False
            return {"id": "abcdefghijk", "duration": 60, "url": "https://stream.test/video.mp4",
                    "width": 1280, "height": 720, "protocol": "https"}
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=Downloader))
    assert online._resolve(VIDEO["source_url"], "720p")["id"] == "abcdefghijk"
    assert captured["js_runtimes"] == {"deno": {}, "node": {}}
    assert not captured.get("remote_components")
