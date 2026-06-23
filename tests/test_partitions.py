"""Partition / bookmark logic of UserInsightsStream (the user-insights core)."""

from __future__ import annotations

import pytest
from singer_sdk.exceptions import ConfigurationError

from tap_instagram_user.streams import UserInsightsStream
from tests.conftest import make_tap, set_bookmark, user_stream


def _build(day_by_day, start, end):
    return UserInsightsStream._build_range_partitions(start, end, day_by_day)


# --- _build_range_partitions (pure) -----------------------------------------

def test_build_range_day_by_day() -> None:
    from datetime import date

    parts = _build(True, date(2026, 6, 17), date(2026, 6, 19))
    assert parts == [
        {"since": "2026-06-17", "until": "2026-06-18"},
        {"since": "2026-06-18", "until": "2026-06-19"},
        {"since": "2026-06-19", "until": "2026-06-20"},
    ]


def test_build_range_single_call() -> None:
    from datetime import date

    parts = _build(False, date(2026, 6, 17), date(2026, 6, 19))
    assert parts == [{"since": "2026-06-17", "until": "2026-06-20"}]


def test_build_range_empty_when_start_after_end() -> None:
    from datetime import date

    assert _build(True, date(2026, 6, 20), date(2026, 6, 19)) == []


# --- partitions (stateful) ---------------------------------------------------

def test_first_run_requires_start_date(fixed_today) -> None:
    tap = make_tap()
    stream = user_stream(tap)
    set_bookmark(stream, None)  # no bookmark, no start_date
    with pytest.raises(ConfigurationError, match="start_date"):
        _ = stream.partitions


def test_first_run_uses_start_date(fixed_today) -> None:
    tap = make_tap(start_date="2026-06-18T00:00:00Z", generate_dates_range="inactive")
    stream = user_stream(tap)
    set_bookmark(stream, None)
    # start 2026-06-18 .. end (today-1) 2026-06-19, single call -> until = 06-20.
    assert stream.partitions == [{"since": "2026-06-18", "until": "2026-06-20"}]


def test_resume_from_bookmark(fixed_today) -> None:
    tap = make_tap(generate_dates_range="inactive")
    stream = user_stream(tap)
    set_bookmark(stream, "2026-06-17T10:00:00+00:00")
    assert stream.partitions == [{"since": "2026-06-17", "until": "2026-06-20"}]


def test_already_ran_today_returns_empty(fixed_today) -> None:
    tap = make_tap()
    stream = user_stream(tap)
    set_bookmark(stream, "2026-06-20T08:00:00+00:00")  # bookmark == today
    assert stream.partitions == []


def test_days_to_subtract_extends_window_back(fixed_today) -> None:
    tap = make_tap(generate_dates_range="inactive", days_to_subtract=2)
    stream = user_stream(tap)
    set_bookmark(stream, "2026-06-18T00:00:00+00:00")
    # start = 06-18 - 2 days = 06-16.
    assert stream.partitions == [{"since": "2026-06-16", "until": "2026-06-20"}]


def test_monthly_consolidation_on_first_of_month(fixed_today) -> None:
    tap = make_tap(generate_dates_range="inactive")
    stream = user_stream(tap)
    set_bookmark(stream, "2026-06-01T00:00:00+00:00")  # 1st of month -> consolidate
    parts = stream.partitions
    # Consolidation of the month before last (April 2026) comes first...
    assert {"since": "2026-04-01", "until": "2026-05-01"} in parts
    # ...followed by the recent window (from 06-01).
    assert {"since": "2026-06-01", "until": "2026-06-20"} in parts
    assert parts[0] == {"since": "2026-04-01", "until": "2026-05-01"}


def test_per_metric_start_date_override(fixed_today) -> None:
    # No global start_date, but the stream carries a per-metric override.
    tap = make_tap()
    stream = user_stream(
        tap, start_date="2026-06-19T00:00:00Z"
    )
    stream._override_generate_dates_range = "inactive"
    set_bookmark(stream, None)
    assert stream.partitions == [{"since": "2026-06-19", "until": "2026-06-20"}]
