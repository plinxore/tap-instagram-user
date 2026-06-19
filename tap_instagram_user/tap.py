"""InstagramUser tap class."""

import sys
from typing import List

from singer_sdk import Tap, Stream
from singer_sdk import typing as th

from tap_instagram_user.streams import MetaRawInsightsStream

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
                "`metrics` (e.g. 2026-05-01T00:00:00Z). If absent, a default "
                "value is computed automatically: the 1st of the current "
                "month minus 12 months."
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
    ).to_dict()


    @override
    def discover_streams(self) -> List[Stream]:
        """Return the list of streams (tables) to extract."""

        streams: List[Stream] = []

        # "metrics" is required (cf. config_jsonschema): tap validation fails
        # before this point is even reached if it's absent.
        metrics_config = self.config["metrics"]

        for entry in metrics_config:
            metric = entry["metric"]
            breakdowns = entry.get("breakdowns") or [""]
            for breakdown in breakdowns:
                # SQL-friendly table name (no comma).
                if breakdown:
                    safe_breakdown = breakdown.replace(",", "_and_")
                    stream_name = f"ig_{metric}_by_{safe_breakdown}"
                else:
                    stream_name = f"ig_{metric}_base"

                # Any overrides on this `metrics` entry are propagated to the
                # stream (None if absent, in which case get_param() falls
                # back to the tap's global value).
                stream = MetaRawInsightsStream(
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

        return streams


if __name__ == "__main__":
    TapInstagramUser.cli()
