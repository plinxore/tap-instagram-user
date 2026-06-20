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


def test_no_media_streams_without_media_fields() -> None:
    # User-only setup: no media streams discovered.
    assert not any(n.startswith("ig_media") for n in _names(make_tap()))


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
