"""Generated presentation-timestamp checks independent of source frame rate."""

from hypothesis import given, settings, strategies as st

from backend.sampling import TimeSampler


@settings(max_examples=100, derandomize=True)
@given(deltas=st.lists(st.integers(1, 500), min_size=1, max_size=100), interval_ms=st.integers(1, 2000))
def test_irregular_frames_select_first_frame_in_each_elapsed_window(deltas, interval_ms):
    """Use integer time arithmetic as an independent oracle for floating sampling."""
    timestamps = [0]
    for delta in deltas:
        timestamps.append(timestamps[-1] + delta)
    sampler = TimeSampler(interval_ms / 1000)
    actual = [timestamp for timestamp in timestamps if sampler.select(timestamp / 1000)]
    expected, deadline = [], 0
    for timestamp in timestamps:
        if timestamp >= deadline:
            expected.append(timestamp)
            deadline = (timestamp // interval_ms + 1) * interval_ms
    assert actual == expected
    assert actual == sorted(set(actual))


@given(timestamps=st.lists(st.integers(0, 100_000), unique=True).map(sorted))
def test_zero_interval_keeps_every_distinct_frame(timestamps):
    """Every-frame mode preserves all source observations without resampling."""
    sampler = TimeSampler(0)
    assert [time for time in timestamps if sampler.select(time / 1000)] == timestamps
