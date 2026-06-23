"""Pytest configuration and shared helpers."""

from __future__ import annotations

from datetime import date

import pytest

from tap_instagram_user import streams as streams_mod
from tap_instagram_user.streams import (
    MediaInsightsStream,
    MediaStream,
    UserInsightsStream,
)
from tap_instagram_user.tap import TapInstagramUser

# Minimal config that passes tap validation (access_token / ig_user_id /
# metrics are the required group). The token is fake: no test hits the network.
BASE_CONFIG = {
    "access_token": "test-token",
    "ig_user_id": "123456789",
    "metrics": [{"metric": "reach", "breakdowns": [""]}],
}

# Fixed "today" used by the partition/bookmark tests.
FIXED_TODAY = date(2026, 6, 20)


class _FixedDate(date):
    """date subclass with a frozen today(), for deterministic partition tests."""

    @classmethod
    def today(cls) -> date:
        return FIXED_TODAY


@pytest.fixture
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> date:
    """Freeze date.today() inside the streams module to FIXED_TODAY."""
    monkeypatch.setattr(streams_mod, "date", _FixedDate)
    return FIXED_TODAY


def make_tap(**overrides) -> TapInstagramUser:
    """Build a TapInstagramUser from BASE_CONFIG plus overrides."""
    cfg = dict(BASE_CONFIG)
    cfg.update(overrides)
    return TapInstagramUser(config=cfg, parse_env_config=False, validate_config=False)


def user_stream(
    tap: TapInstagramUser, metric: str = "reach", breakdown: str = "", **overrides
) -> UserInsightsStream:
    """Build a single user-insights stream, optionally with per-metric overrides."""
    return UserInsightsStream(
        tap=tap,
        name=f"ig_user_insights_{metric}",
        metric_name=metric,
        breakdown=breakdown,
        **overrides,
    )


def set_bookmark(stream, value: str | None) -> None:
    """Force the stream's persisted replication value (the previous-run bookmark)."""
    state = {"replication_key_value": value} if value else {}
    stream.get_context_state = lambda ctx=None: state


def media_stream(tap: TapInstagramUser) -> MediaStream:
    """Build the ig_media parent stream."""
    return MediaStream(tap=tap, name="ig_media")


def media_insights_stream(
    tap: TapInstagramUser, metric: str = "reach", breakdown: str = ""
) -> MediaInsightsStream:
    """Build a single media-insights child stream."""
    return MediaInsightsStream(
        tap=tap,
        name=f"ig_media_insights_{metric}",
        metric_name=metric,
        breakdown=breakdown,
    )


class FakeResponse:
    """Minimal stand-in for requests.Response in unit tests."""

    def __init__(self, payload: dict | None = None, status_code: int = 200, text: str = ""):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text

    def json(self) -> dict:
        return self._payload
