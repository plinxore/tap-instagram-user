"""Stream type classes for tap-instagram-user."""
from datetime import date, timedelta, datetime, timezone
from dateutil.relativedelta import relativedelta

from typing import Any, Iterable, Optional
import requests

from singer_sdk import typing as th

from tap_instagram_user.client import InstagramUserStream

class MetaRawInsightsStream(InstagramUserStream):
    """Generic stream for extracting any Instagram metric."""

    # `metric_date` (the day the data is for, = the partition's "since") is
    # required in the key: without it, two different days for the same
    # metric overwrite each other on an upsert on the target side.
    primary_keys = ["ig_user_id", "metric_name", "breakdown_type", "metric_date"]

    replication_key = "extraction_date"
    is_sorted = False
    # A single bookmark per stream (rather than one per since/until
    # partition), so that get_context_state(None) in `partitions` below
    # retrieves a global bookmark instead of a per-partition one.
    state_partitioning_keys = []

    @staticmethod
    def _build_range_partitions(start: date, end: date, day_by_day: bool) -> list[dict]:
        """Split [start, end] (inclusive) into since/until partitions.

        If `day_by_day` is True ("active" mode, legacy default): one
        partition per day. Otherwise ("inactive" mode): a single partition
        covering the whole range in one API call.
        """
        if start > end:
            return []
        if not day_by_day:
            return [{
                "since": start.strftime("%Y-%m-%d"),
                "until": (end + timedelta(days=1)).strftime("%Y-%m-%d"),
            }]
        partitions = []
        current = start
        while current <= end:
            partitions.append({
                "since": current.strftime("%Y-%m-%d"),
                "until": (current + timedelta(days=1)).strftime("%Y-%m-%d")
            })
            current += timedelta(days=1)
        return partitions

    @property
    def partitions(self) -> list[dict] | None:
        """Generate the extraction chunks (legacy logic)."""
        partitions = []
        today = date.today()
        days_to_subtract = self.get_param("days_to_subtract", 0)
        # "active" = day-by-day chunking; "inactive" = a single call covering
        # the whole since/until range.
        day_by_day = self.get_param("generate_dates_range", "active") != "inactive"

        # get_starting_replication_key_value() doesn't work here: that method
        # reads "starting_replication_value", a field the SDK only writes
        # after evaluating `partitions` (so it's always empty at this point).
        # The previous run's persisted bookmark is read directly via
        # "replication_key_value".
        state_bookmark = self.get_context_state(None).get("replication_key_value")

        if state_bookmark:
            # Keep only the first 10 characters (YYYY-MM-DD) of the bookmark,
            # e.g. "2026-06-18T18:39..." -> "2026-06-18".
            last_date_executes = date.fromisoformat(state_bookmark[:10])
            self.logger.info(f"Resuming from bookmark (state): {last_date_executes}")
        else:
            # First run: use the config value, otherwise a computed default.
            start_date_str = self.get_param("start_date")
            if start_date_str:
                last_date_executes = date.fromisoformat(start_date_str[:10])
                self.logger.info(f"First run, forced start at: {last_date_executes}")
            else:
                # No 'start_date' provided: fall back to the 1st day of the
                # current month, minus 12 months (e.g. running on 2026-06-19
                # -> 2025-06-01).
                last_date_executes = today.replace(day=1) - relativedelta(months=12)
                self.logger.info(
                    "First run, no 'start_date' provided: computed default "
                    f"(1st of the month - 12 months) = {last_date_executes}"
                )

        # Bookmark as it was at the start of this run. The consolidation
        # block below generates partitions with an "until" earlier than this
        # bookmark; without this floor, the SDK would take the max of the
        # "extraction_date" values seen in this run only (cf. parse_response)
        # and would make the bookmark regress if the "recent" block is empty.
        self._run_start_bookmark = datetime(
            last_date_executes.year, last_date_executes.month, last_date_executes.day,
            tzinfo=timezone.utc,
        )

        if last_date_executes >= today:
            self.logger.info("Already ran today. Done.")
            return []

        # Monthly consolidation: Meta insights can still be corrected after
        # publication, so the month before last is fully re-extracted at the
        # start of every month.
        if last_date_executes.day == 1:
            self.logger.info("Start of month: consolidating the month before last.")
            first_day_in_2_last_month = (last_date_executes - relativedelta(months=2)).replace(day=1)
            last_day_in_2_last_month = first_day_in_2_last_month + relativedelta(months=1) - timedelta(days=1)

            partitions.extend(self._build_range_partitions(
                first_day_in_2_last_month, last_day_in_2_last_month, day_by_day,
            ))

        # Extraction of recent days not yet covered.
        start_recent = last_date_executes - timedelta(days=days_to_subtract)
        end_recent = today - timedelta(days=1)

        partitions.extend(self._build_range_partitions(start_recent, end_recent, day_by_day))

        return partitions

    # Hybrid schema: structured metadata + raw data in JSONB.
    schema = th.PropertiesList(
        th.Property("ig_user_id", th.StringType, required=True),
        th.Property("metric_name", th.StringType),
        th.Property("breakdown_type", th.StringType),
        # Business date of the extracted data (= the partition's "since").
        th.Property("metric_date", th.DateType, required=True),
        th.Property("extraction_date", th.DateTimeType),
        th.Property(
            "raw_data",
            th.CustomType({"type": ["object", "array"]}),
            description="The raw JSON returned by the Meta API"
        )
    ).to_dict()

    def __init__(
        self,
        tap: Any,
        name: str,
        metric_name: str,
        breakdown: Optional[str] = None,
        start_date: Optional[str] = None,
        days_to_subtract: Optional[int] = None,
        period: Optional[str] = None,
        timeframe: Optional[str] = None,
        metric_type: Optional[str] = None,
        generate_dates_range: Optional[str] = None,
        **kwargs
    ):
        """Dynamic stream initialization.

        `start_date`, `days_to_subtract`, `period`, `timeframe`,
        `metric_type` and `generate_dates_range` are optional overrides
        defined on the corresponding `metrics` entry (cf. tap.py). If not
        provided (None), `get_param()` (cf. client.py) falls back to the
        tap's global value.
        """
        super().__init__(tap=tap, name=name, **kwargs)

        self.metric_name = metric_name
        self.breakdown = breakdown
        self._override_start_date = start_date
        self._override_days_to_subtract = days_to_subtract
        self._override_period = period
        self._override_timeframe = timeframe
        self._override_metric_type = metric_type
        self._override_generate_dates_range = generate_dates_range

        self.path = f"/{self.config.get('ig_user_id')}/insights"

    def get_records(self, context: Optional[dict]) -> Iterable[dict]:
        """No partition to process = no API call.

        `partitions` returns [] when there's nothing to extract (already ran
        today, no start_date, ...). But for the SDK, an empty partitions
        list is "falsy" and falls back to a single {} context (cf.
        `context_list or [{}]` in core.py), which would trigger an API call
        without since/until. This case is explicitly blocked here.
        """
        if not context:
            return
        yield from super().get_records(context)

    def parse_response(self, response: requests.Response) -> Iterable[dict]:
        """Wrap Meta's raw response with its metadata, without any transformation."""
        # The current partition's "until" (set in get_url_params in
        # client.py) is used as the bookmark value: it represents the day
        # after the last day of data actually covered, not the time of
        # execution. It is capped by the run's starting bookmark so that
        # consolidation partitions (past dates) never make the bookmark
        # regress.
        current_until = getattr(self, "_current_until", None)
        run_start_bookmark = getattr(self, "_run_start_bookmark", None)
        if current_until and run_start_bookmark:
            bookmark_value = max(current_until, run_start_bookmark)
        else:
            bookmark_value = current_until or datetime.now(timezone.utc)
        current_since = getattr(self, "_current_since", None)

        yield {
            "ig_user_id": self.config.get("ig_user_id"),
            "metric_name": self.metric_name,
            "breakdown_type": self.breakdown if self.breakdown else "none",
            "metric_date": current_since.date().isoformat() if current_since else None,
            "extraction_date": bookmark_value.isoformat(),  # The value the SDK will persist
            "raw_data": response.json()
        }
