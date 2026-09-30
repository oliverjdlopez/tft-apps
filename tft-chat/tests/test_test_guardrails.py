"""Tests for repository-wide test execution guardrails."""

from __future__ import annotations

import time

import pytest

from conftest import StalledTestTimeoutError, _test_timeout


def test_test_timeout_interrupts_a_stalled_call() -> None:
    """Raise a useful failure instead of waiting indefinitely."""
    started = time.monotonic()

    with pytest.raises(StalledTestTimeoutError, match="stalled-test exceeded"):
        with _test_timeout(0.03, label="stalled-test"):
            time.sleep(1.0)

    assert time.monotonic() - started < 0.5


def test_test_timeout_can_be_disabled() -> None:
    """Permit explicit opt-out for intentionally interactive test calls."""
    with _test_timeout(None, label="disabled-test"):
        time.sleep(0.001)

