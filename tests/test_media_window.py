"""Date-window logic of the ig_media list (MediaStream._media_window)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from tests.conftest import FIXED_TODAY, make_tap, media_stream


def _unix(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _stream(**cfg):
    return media_stream(make_tap(media_fields=["id", "media_product_type"], **cfg))


def test_no_config_means_no_window() -> None:
    s = _stream()
    assert s._media_window(None, FIXED_TODAY) == (None, None)
    assert s._media_window("2026-06-19T00:00:00+00:00", FIXED_TODAY) == (None, None)


def test_media_since_applies_to_every_run() -> None:
    # Without an active window, the floor bounds the snapshot on every run.
    s = _stream(media_since="2026-01-01T00:00:00Z")
    floor = _unix(date(2026, 1, 1))
    assert s._media_window(None, FIXED_TODAY) == (floor, None)  # first run
    assert s._media_window("2026-06-19T00:00:00+00:00", FIXED_TODAY) == (floor, None)  # ongoing


def test_active_window_first_run_backfills_to_floor() -> None:
    s = _stream(media_since="2026-01-01T00:00:00Z", media_active_window_days=30)
    assert s._media_window(None, FIXED_TODAY) == (_unix(date(2026, 1, 1)), None)


def test_active_window_ongoing_uses_rolling_window() -> None:
    s = _stream(media_since="2026-01-01T00:00:00Z", media_active_window_days=30)
    since, _ = s._media_window("2026-06-19T00:00:00+00:00", FIXED_TODAY)
    assert since == _unix(FIXED_TODAY - timedelta(days=30))


def test_active_window_covers_a_gap() -> None:
    # Pipeline was down: last run older than the window -> go back to last run.
    s = _stream(media_active_window_days=30)
    since, _ = s._media_window("2026-04-01T00:00:00+00:00", FIXED_TODAY)
    assert since == _unix(date(2026, 4, 1))


def test_active_window_is_floored_by_media_since() -> None:
    # Window would reach further back than the floor -> capped at media_since.
    s = _stream(media_since="2026-06-01T00:00:00Z", media_active_window_days=200)
    since, _ = s._media_window("2026-06-19T00:00:00+00:00", FIXED_TODAY)
    assert since == _unix(date(2026, 6, 1))


def test_media_until_is_passed_through() -> None:
    s = _stream(media_until="2026-06-15T00:00:00Z")
    _, until = s._media_window(None, FIXED_TODAY)
    assert until == _unix(date(2026, 6, 15))


def test_url_params_include_since_until_when_set() -> None:
    s = _stream()
    s._media_since_ts, s._media_until_ts = 1700000000, 1800000000
    params = s.get_url_params(None, None)
    assert params["since"] == 1700000000
    assert params["until"] == 1800000000


def test_url_params_omit_since_until_when_unset() -> None:
    s = _stream()  # no window computed -> class defaults are None
    params = s.get_url_params(None, None)
    assert "since" not in params
    assert "until" not in params
