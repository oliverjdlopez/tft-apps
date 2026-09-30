"""Presentation-timestamp sampling independent of the encoded frame rate."""
import math


class TimeSampler:
    def __init__(self, interval_seconds):
        if not math.isfinite(interval_seconds) or interval_seconds < 0:
            raise ValueError('Analysis interval must be finite and nonnegative')
        self.interval = interval_seconds
        self.next_time = 0.0

    def select(self, timestamp):
        if self.interval == 0:
            return True
        if timestamp + 1e-9 < self.next_time:
            return False
        self.next_time = (math.floor((timestamp + 1e-9) / self.interval) + 1) * self.interval
        return True
