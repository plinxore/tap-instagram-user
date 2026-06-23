"""Media streams, client params, and error handling."""

from __future__ import annotations

import pytest

from tap_instagram_user.streams import InstagramMediaPaginator, UserStream, _SkipMediaError
from tests.conftest import (
    FakeResponse,
    make_tap,
    media_insights_stream,
    media_stream,
    user_stream,
)

COMPAT = {"FEED": ["reach", "views"], "REELS": ["reach"]}


def media_tap(**extra):
    return make_tap(
        media_fields=["id", "timestamp", "media_product_type"],
        media_metrics=[{"metric": "reach"}],
        media_metric_compatibility=COMPAT,
        **extra,
    )


# --- pagination --------------------------------------------------------------

def test_paginator_follows_after_cursor() -> None:
    pag = InstagramMediaPaginator(max_pages=100)
    resp = FakeResponse({"paging": {"next": "url", "cursors": {"after": "CUR"}}})
    assert pag.get_next(resp) == "CUR"


def test_paginator_stops_without_next() -> None:
    pag = InstagramMediaPaginator(max_pages=100)
    assert pag.get_next(FakeResponse({"paging": {}})) is None


def test_paginator_respects_max_pages() -> None:
    pag = InstagramMediaPaginator(max_pages=1)
    resp = FakeResponse({"paging": {"next": "url", "cursors": {"after": "CUR"}}})
    # First page already fetched (count == 0) and max_pages == 1 -> stop.
    assert pag.get_next(resp) is None


# --- media list URL params ---------------------------------------------------

def test_media_list_url_params() -> None:
    stream = media_stream(media_tap(media_limit=50))
    params = stream.get_url_params(None, None)
    assert params["access_token"] == "test-token"
    assert params["fields"] == "id,timestamp,media_product_type"
    assert params["limit"] == 50
    assert "after" not in params


def test_media_list_url_params_pagination_token() -> None:
    stream = media_stream(media_tap())
    params = stream.get_url_params(None, "CURSOR")
    assert params["after"] == "CURSOR"


# --- media insights URL params (no period / no metric_type) ------------------

def test_media_insights_url_params_minimal() -> None:
    stream = media_insights_stream(media_tap(), metric="reach")
    params = stream.get_url_params({"id_post": "1"}, None)
    assert params == {"access_token": "test-token", "metric": "reach"}
    assert "period" not in params
    assert "metric_type" not in params


def test_media_insights_url_params_with_breakdown() -> None:
    stream = media_insights_stream(media_tap(), metric="profile_activity", breakdown="action_type")
    params = stream.get_url_params({"id_post": "1"}, None)
    assert params["breakdown"] == "action_type"


# --- compatibility filtering + fail-fast -------------------------------------

def test_filtered_when_metric_invalid_for_type() -> None:
    # reach is NOT in COMPAT["STORY"] (no STORY key) -> skipped, no records.
    stream = media_insights_stream(media_tap(), metric="reach")
    ctx = {"id_post": "1", "media_product_type": "STORY"}
    assert list(stream.get_records(ctx)) == []


def test_missing_media_product_type_fails_fast() -> None:
    stream = media_insights_stream(media_tap(), metric="reach")
    with pytest.raises(RuntimeError, match="media_product_type is required"):
        list(stream.get_records({"id_post": "1"}))


def _media_type_tap():
    # views is valid for FEED (axis 1) but only for VIDEO (axis 2).
    return make_tap(
        media_fields=["id", "media_product_type", "media_type"],
        media_metrics=[{"metric": "views"}],
        media_metric_compatibility={"FEED": ["reach", "views"], "REELS": ["reach", "views"]},
        media_metric_compatibility_by_media_type={
            "IMAGE": ["reach"],
            "VIDEO": ["reach", "views"],
        },
    )


def test_media_type_filter_skips_views_on_image() -> None:
    # views passes the product_type axis (FEED) but not the media_type axis
    # (IMAGE) -> skipped before any API call.
    stream = media_insights_stream(_media_type_tap(), metric="views")
    ctx = {"id_post": "1", "media_product_type": "FEED", "media_type": "IMAGE"}
    assert list(stream.get_records(ctx)) == []


def test_media_type_required_when_table_is_set() -> None:
    stream = media_insights_stream(_media_type_tap(), metric="views")
    ctx = {"id_post": "1", "media_product_type": "FEED"}  # no media_type
    with pytest.raises(RuntimeError, match="media_type is required"):
        list(stream.get_records(ctx))


def test_validate_response_raises_on_unsupported_metric() -> None:
    stream = media_insights_stream(media_tap(), metric="reach")
    resp = FakeResponse(
        status_code=400,
        text='{"error":{"message":"The Media Insights API does not support the reach metric"}}',
    )
    with pytest.raises(RuntimeError, match="compatibility tables"):
        stream.validate_response(resp)


def test_unsupported_metric_skips_when_configured() -> None:
    # on_unsupported_metric=skip -> "does not support" becomes a skip, not a raise.
    stream = media_insights_stream(media_tap(on_unsupported_metric="skip"), metric="reach")
    resp = FakeResponse(
        status_code=400,
        text='{"error":{"message":"The Media Insights API does not support the reach metric"}}',
    )
    with pytest.raises(_SkipMediaError):
        stream.validate_response(resp)


def test_validate_response_skips_pre_conversion_media() -> None:
    stream = media_insights_stream(media_tap(), metric="reach")
    resp = FakeResponse(
        status_code=400,
        text="(#10) Media Posted Before Business Account Conversion",
    )
    with pytest.raises(_SkipMediaError):
        stream.validate_response(resp)


# --- client get_param + user insights params ---------------------------------

def test_get_param_override_precedence() -> None:
    tap = make_tap(period="day")
    stream = user_stream(tap, period="week")  # per-metric override
    assert stream.get_param("period") == "week"


def test_get_param_falls_back_to_config() -> None:
    tap = make_tap(period="day")
    stream = user_stream(tap)  # no override
    assert stream.get_param("period") == "day"


def test_user_node_url_params_and_post_process() -> None:
    tap = make_tap(user_fields=["username", "followers_count"])
    stream = UserStream(tap=tap, name="ig_user")
    params = stream.get_url_params(None, None)
    assert params["fields"] == "username,followers_count"
    assert params["access_token"] == "test-token"
    stream._extraction_date = "2026-06-20T00:00:00+00:00"
    row = stream.post_process({"id": "1", "followers_count": 10}, None)
    assert row["ig_user_id"] == "123456789"
    assert row["raw_data"]["followers_count"] == 10


def test_user_insights_always_sends_metric_type() -> None:
    tap = make_tap()
    stream = user_stream(tap, metric="reach")
    params = stream.get_url_params({"since": "2026-06-18", "until": "2026-06-19"}, None)
    assert params["metric"] == "reach"
    assert params["metric_type"] == "total_value"
    # since/until are converted to UNIX timestamps for the Meta API.
    assert isinstance(params["since"], int)
    assert isinstance(params["until"], int)
