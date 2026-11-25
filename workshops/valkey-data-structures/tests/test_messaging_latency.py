"""UTC event ages remain distinct from local GLIDE dequeue latency."""

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from events import event_age_ms  # noqa: E402


@pytest.mark.parametrize("timestamp", ["manual", "", None, "2026-11-23T12:00:00"])
def test_manual_missing_or_naive_event_has_no_clock_comparison(timestamp):
    received = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
    assert event_age_ms({"occurred_at": timestamp}, received) is None


def test_timezone_aware_event_age_uses_actual_utc_instant():
    received = datetime(2026, 11, 23, 12, 0, 0, 125000, tzinfo=timezone.utc)
    assert event_age_ms({"occurred_at": "2026-11-23T14:00:00+02:00"}, received) == 125.0


def test_clock_skew_is_visible_instead_of_fabricating_zero_delivery_latency():
    received = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
    assert event_age_ms({"occurred_at": "2026-11-23T12:00:00.250000+00:00"}, received) == -250.0
