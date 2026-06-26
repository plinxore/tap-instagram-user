"""InstagramUser tap class."""

import sys

from singer_sdk import Stream, Tap
from singer_sdk import typing as th
from singer_sdk.exceptions import ConfigurationError

from tap_instagram_user.streams import (
    MediaInsightsStream,
    MediaStream,
    UserInsightsStream,
    UserStream,
)

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


class TapInstagramUser(Tap):
    """Custom extractor for the Meta API (Instagram Insights)."""

    name = "tap-instagram-user"
    # Name of the actually installed PyPI package (different from `name`
    # above), required for get_plugin_version() to resolve the right version.
    package_name = "plinxore-tap-instagram-user"

    config_jsonschema = th.PropertiesList(
        th.Property(
            "access_token",
            th.StringType,
            required=True,
            secret=True,  # Masks the token in logs
            description="The client's Long-Lived Token"
        ),
        th.Property(
            "ig_user_id",
            th.StringType,
            required=True,
            description="The professional Instagram account ID"
        ),
        th.Property(
            "start_date",
            th.DateTimeType,
            description=(
                "Default 'start_date' for all metrics on first extraction "
                "(ignored once a bookmark exists). Overridable per entry in "
                "`metrics` (e.g. 2026-05-01T00:00:00Z). No default: required "
                "on a stream's first run (it fails fast if neither this nor a "
                "per-metric start_date is set)."
            ),
        ),
        th.Property(
            "days_to_subtract",
            th.IntegerType,
            default=0,
            description=(
                "Default number of already-covered days to re-extract on "
                "each run, in addition to genuinely new days (overlap "
                "window, useful because Meta insights can still be "
                "corrected after their first extraction). 0 = no "
                "re-extraction. Overridable per entry in `metrics`."
            ),
        ),
        th.Property(
            "period",
            th.StringType,
            default="day",
            description=(
                "Default granularity requested from the Meta Insights API "
                "(`period` parameter). Overridable per entry in `metrics`."
            ),
        ),
        th.Property(
            "timeframe",
            th.StringType,
            description=(
                "Default optional `timeframe` parameter passed to the Meta "
                "Insights API. Overridable per entry in `metrics`."
            ),
        ),
        th.Property(
            "metric_type",
            th.StringType,
            default="total_value",
            description=(
                "Default `metric_type` parameter passed to the Meta "
                "Insights API for each metric. Overridable per entry in "
                "`metrics`."
            ),
        ),
        th.Property(
            "generate_dates_range",
            th.StringType,
            default="active",
            allowed_values=["active", "inactive"],
            description=(
                "'active' (default): one API call per day (since/until = "
                "1 day). 'inactive': a single call covering the whole "
                "since/until range (fewer API calls, but loses day-by-day "
                "granularity depending on what the API returns for the "
                "metric). Overridable per entry in `metrics`."
            ),
        ),
        th.Property(
            "metrics",
            th.ArrayType(
                th.ObjectType(
                    th.Property(
                        "metric",
                        th.StringType,
                        required=True,
                        description="Meta Insights metric name (e.g. views, reach, impressions).",
                    ),
                    th.Property(
                        "breakdowns",
                        th.ArrayType(th.StringType),
                        description=(
                            "Breakdowns to extract for this metric. An empty "
                            "string generates a stream with no breakdown."
                        ),
                    ),
                    th.Property(
                        "start_date",
                        th.DateTimeType,
                        description="Overrides 'start_date' for this metric only.",
                    ),
                    th.Property(
                        "days_to_subtract",
                        th.IntegerType,
                        description="Overrides 'days_to_subtract' for this metric only.",
                    ),
                    th.Property(
                        "period",
                        th.StringType,
                        description="Overrides 'period' for this metric only.",
                    ),
                    th.Property(
                        "timeframe",
                        th.StringType,
                        description="Overrides 'timeframe' for this metric only.",
                    ),
                    th.Property(
                        "metric_type",
                        th.StringType,
                        description="Overrides 'metric_type' for this metric only.",
                    ),
                    th.Property(
                        "generate_dates_range",
                        th.StringType,
                        allowed_values=["active", "inactive"],
                        description="Overrides 'generate_dates_range' for this metric only.",
                    ),
                )
            ),
            required=True,
            description=(
                "List of metrics (and their breakdowns) to extract; one "
                "stream is generated per metric/breakdown combination. Each "
                "entry may override start_date/days_to_subtract/period/"
                "timeframe/metric_type/generate_dates_range for itself; "
                "otherwise the global value above applies. "
                "Required: no default value."
            ),
        ),
        th.Property(
            "user_fields",
            th.ArrayType(th.StringType),
            description=(
                "Fields to request on the IG User node for the `ig_user` "
                "stream (e.g. username, followers_count, follows_count, "
                "media_count, biography, website). No in-code default "
                "(Meta-controlled vocabulary). Set it to enable the `ig_user` "
                "account-profile snapshot; omit to skip it."
            ),
        ),
        th.Property(
            "media_fields",
            th.ArrayType(th.StringType),
            description=(
                "Fields to request on the `/media` edge for the `ig_media` "
                "stream (e.g. id, timestamp, media_type, media_product_type, "
                "like_count). No in-code default: this is a Meta-controlled "
                "vocabulary, so it must be supplied explicitly. Required to "
                "enable media extraction. `media_product_type` must be "
                "included for the media-insights child streams to work."
            ),
        ),
        th.Property(
            "media_limit",
            th.IntegerType,
            default=100,
            description="Page size (`limit`) for the `/media` edge.",
        ),
        th.Property(
            "media_max_pages",
            th.IntegerType,
            default=100,
            description=(
                "Maximum number of pages to fetch from the `/media` edge "
                "(safety cap against an unbounded pagination loop)."
            ),
        ),
        th.Property(
            "media_since",
            th.DateTimeType,
            description=(
                "Optional floor date for the `/media` list (passed as the "
                "`since` Unix timestamp). On the first run it bounds the "
                "backfill; omit it to backfill the whole catalogue (capped at "
                "Meta's ~10K most recent media). No default."
            ),
        ),
        th.Property(
            "media_until",
            th.DateTimeType,
            description=(
                "Optional ceiling date for the `/media` list (passed as the "
                "`until` Unix timestamp). Usually left unset (= up to now); "
                "useful for backfilling a fixed window. No default."
            ),
        ),
        th.Property(
            "media_active_window_days",
            th.IntegerType,
            description=(
                "Optional rolling refresh window (in days). When set, only the "
                "FIRST run backfills (down to `media_since`); later runs fetch "
                "just the last N days, so frozen old posts are not re-listed "
                "nor their insights re-fetched. Omit for a full snapshot every "
                "run. No default (this affects completeness, so it is opt-in)."
            ),
        ),
        th.Property(
            "media_metrics",
            th.ArrayType(
                th.ObjectType(
                    th.Property(
                        "metric",
                        th.StringType,
                        required=True,
                        description=(
                            "Media insights metric name "
                            "(e.g. reach, views, profile_activity)."
                        ),
                    ),
                    th.Property(
                        "breakdowns",
                        th.ArrayType(th.StringType),
                        description=(
                            "Breakdowns for this metric (e.g. action_type for "
                            "profile_activity, story_navigation_action_type for "
                            "navigation). An empty string generates a stream "
                            "with no breakdown."
                        ),
                    ),
                )
            ),
            description=(
                "List of per-post insight metrics to extract; one "
                "`ig_media_insights_<metric>` stream is generated per "
                "metric/breakdown combination. Requires `media_fields` and "
                "`media_metric_compatibility`."
            ),
        ),
        th.Property(
            "media_metric_compatibility",
            th.ObjectType(additional_properties=th.ArrayType(th.StringType)),
            description=(
                "Maps each media_product_type (e.g. FEED, REELS, STORY) to the "
                "list of metrics valid for it. Used to avoid requesting a "
                "metric on a post type Meta does not support. No in-code "
                "default: this is a Meta-controlled vocabulary and must be "
                "supplied explicitly. Required when `media_metrics` is set."
            ),
        ),
        th.Property(
            "media_metric_compatibility_by_media_type",
            th.ObjectType(additional_properties=th.ArrayType(th.StringType)),
            description=(
                "Optional second compatibility axis, mapping each media_type "
                "(e.g. IMAGE, VIDEO, CAROUSEL_ALBUM) to the list of metrics "
                "valid for it. When set, a metric is requested only if it is "
                "valid for BOTH the post's media_product_type and its "
                "media_type (intersection) — e.g. `views` applies to VIDEO "
                "only. Requires `media_type` in `media_fields`. Omit to filter "
                "by media_product_type alone."
            ),
        ),
        th.Property(
            "on_unsupported_metric",
            th.StringType,
            default="fail",
            allowed_values=["fail", "skip"],
            description=(
                "Behaviour when Meta rejects a media-insights metric with "
                "'does not support the metric' despite the compatibility "
                "tables allowing it. 'fail' (default): raise and stop the run "
                "(treat as a stale-table signal, no silent data loss). 'skip': "
                "log a WARNING and skip that post/metric, for resilient "
                "unattended pipelines."
            ),
        ),
    ).to_dict()


    @override
    def discover_streams(self) -> list[Stream]:
        """Return the list of streams (tables) to extract."""
        streams: list[Stream] = []

        # "metrics" is required (cf. config_jsonschema): tap validation fails
        # before this point is even reached if it's absent.
        metrics_config = self.config["metrics"]

        for entry in metrics_config:
            metric = entry["metric"]
            breakdowns = entry.get("breakdowns") or [""]
            # Effective metric_type for this entry (per-entry override, else the
            # tap default). A `_<metric_type>` segment is added only when it is
            # NOT total_value, so the common case keeps clean names AND the same
            # metric can be requested in both metric_types without collision
            # (e.g. reach in total_value -> ig_user_insights_reach, and in
            # time_series -> ig_user_insights_reach_time_series).
            metric_type = (
                entry.get("metric_type") or self.config.get("metric_type") or "total_value"
            )
            mt_segment = "" if metric_type == "total_value" else f"_{metric_type}"
            for breakdown in breakdowns:
                # SQL-friendly table name (no comma). Scheme:
                # ig_<node>_<edge>_<metric>[_<metric_type>][_by_<breakdown>]
                # — here the User node's Insights edge.
                base = f"ig_user_insights_{metric}{mt_segment}"
                if breakdown:
                    safe_breakdown = breakdown.replace(",", "_and_")
                    stream_name = f"{base}_by_{safe_breakdown}"
                else:
                    stream_name = base

                # Any overrides on this `metrics` entry are propagated to the
                # stream (None if absent, in which case get_param() falls
                # back to the tap's global value).
                stream = UserInsightsStream(
                    tap=self,
                    name=stream_name,
                    metric_name=metric,
                    breakdown=breakdown,
                    start_date=entry.get("start_date"),
                    days_to_subtract=entry.get("days_to_subtract"),
                    period=entry.get("period"),
                    timeframe=entry.get("timeframe"),
                    metric_type=entry.get("metric_type"),
                    generate_dates_range=entry.get("generate_dates_range"),
                )

                streams.append(stream)

        # IG User node (account profile/stats) — optional, only when
        # `user_fields` is configured.
        if self.config.get("user_fields"):
            streams.append(UserStream(tap=self, name="ig_user"))

        # Media extraction is optional: the `ig_media` stream is only
        # discovered when `media_fields` is configured, so user-insights-only
        # setups are unaffected.
        if self.config.get("media_fields"):
            streams.append(MediaStream(tap=self, name="ig_media"))

        # Per-post insight children. Conditionally required (cf. the
        # no-hardcoded-vocab rule): if `media_metrics` is set, both
        # `media_fields` (for the parent) and `media_metric_compatibility`
        # (for filtering) must be present too.
        media_metrics = self.config.get("media_metrics")
        if media_metrics:
            if not self.config.get("media_fields"):
                raise ConfigurationError(
                    "'media_metrics' requires 'media_fields' (the ig_media "
                    "parent stream must be enabled to provide post ids)."
                )
            if not self.config.get("media_metric_compatibility"):
                raise ConfigurationError(
                    "'media_metrics' requires 'media_metric_compatibility' "
                    "(maps each media_product_type to its valid metrics)."
                )

            for entry in media_metrics:
                metric = entry["metric"]
                breakdowns = entry.get("breakdowns") or [""]
                for breakdown in breakdowns:
                    # ig_<node>_<edge>...: the Media node's Insights edge. The
                    # `insights` segment keeps these names distinct from other
                    # Media edges added later (e.g. ig_media_comments), even
                    # when a metric shares the edge's name (metric `comments`
                    # -> ig_media_insights_comments, not ig_media_comments).
                    if breakdown:
                        safe_breakdown = breakdown.replace(",", "_and_")
                        stream_name = f"ig_media_insights_{metric}_by_{safe_breakdown}"
                    else:
                        stream_name = f"ig_media_insights_{metric}"

                    streams.append(MediaInsightsStream(
                        tap=self,
                        name=stream_name,
                        metric_name=metric,
                        breakdown=breakdown,
                    ))

        return streams


if __name__ == "__main__":
    TapInstagramUser.cli()
