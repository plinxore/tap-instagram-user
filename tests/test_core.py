"""Smoke tests: the tap instantiates and exposes its config schema."""

from __future__ import annotations

from tests.conftest import make_tap


def test_tap_instantiates() -> None:
    tap = make_tap()
    assert tap.name == "tap-instagram-user"
    # package_name must point at the real PyPI distribution for version lookup.
    assert tap.package_name == "plinxore-tap-instagram-user"


def test_config_schema_exposes_media_settings() -> None:
    props = make_tap().config_jsonschema["properties"]
    for key in (
        "media_fields",
        "media_limit",
        "media_max_pages",
        "media_metrics",
        "media_metric_compatibility",
    ):
        assert key in props, f"missing config setting: {key}"


def test_start_date_has_no_default() -> None:
    # start_date must NOT carry an in-schema default (it is required on first run).
    start_date = make_tap().config_jsonschema["properties"]["start_date"]
    assert "default" not in start_date
