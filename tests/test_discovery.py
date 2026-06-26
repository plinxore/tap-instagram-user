"""Stream discovery: naming scheme and conditional media discovery."""

from __future__ import annotations

import pytest
from singer_sdk.exceptions import ConfigurationError

from tests.conftest import make_tap

COMPAT = {"FEED": ["reach", "views"], "REELS": ["reach"], "STORY": ["reach"]}


def _names(tap) -> set[str]:
    return {s.name for s in tap.discover_streams()}


def test_user_stream_naming() -> None:
    tap = make_tap(
        metrics=[
            {"metric": "views", "breakdowns": ["follow_type", "a,b", ""]},
            {"metric": "reach", "breakdowns": [""]},
        ]
    )
    names = _names(tap)
    assert names == {
        "ig_user_insights_views_by_follow_type",
        "ig_user_insights_views_by_a_and_b",
        "ig_user_insights_views",
        "ig_user_insights_reach",
    }


def test_metric_type_ventilation() -> None:
    # total_value (default) -> no segment; non-default -> a `_<metric_type>`
    # segment, so the same metric can be requested in both without collision.
    tap = make_tap(
        metrics=[
            {"metric": "reach"},  # inherits the default total_value
            {"metric": "reach", "metric_type": "time_series"},
        ]
    )
    names = _names(tap)
    assert "ig_user_insights_reach" in names
    assert "ig_user_insights_reach_time_series" in names
    assert len(names) == 2  # distinct, no collision/overwrite


def test_no_media_streams_without_media_fields() -> None:
    # User-only setup: no media streams discovered.
    assert not any(n.startswith("ig_media") for n in _names(make_tap()))


def test_no_ig_user_stream_without_user_fields() -> None:
    assert "ig_user" not in _names(make_tap())


def test_ig_user_stream_discovered_with_user_fields() -> None:
    assert "ig_user" in _names(make_tap(user_fields=["username", "followers_count"]))


def test_media_streams_discovered_with_config() -> None:
    tap = make_tap(
        media_fields=["id", "media_product_type"],
        media_metrics=[{"metric": "reach"}, {"metric": "views"}],
        media_metric_compatibility=COMPAT,
    )
    names = _names(tap)
    assert "ig_media" in names
    assert "ig_media_insights_reach" in names
    assert "ig_media_insights_views" in names


# The tap discovers streams during construction (setup_mapper), so the
# conditional ConfigurationError surfaces at make_tap() time.

def test_media_metrics_requires_media_fields() -> None:
    with pytest.raises(ConfigurationError, match="media_fields"):
        make_tap(
            media_metrics=[{"metric": "reach"}],
            media_metric_compatibility=COMPAT,
        )


def test_media_metrics_requires_compatibility_table() -> None:
    with pytest.raises(ConfigurationError, match="media_metric_compatibility"):
        make_tap(
            media_fields=["id", "media_product_type"],
            media_metrics=[{"metric": "reach"}],
        )
