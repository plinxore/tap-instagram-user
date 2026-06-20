"""Stream type classes for tap-instagram-user."""
from datetime import date, timedelta, datetime, timezone
from dateutil.relativedelta import relativedelta

from typing import Any, Iterable, Optional
import requests

from singer_sdk import typing as th
from singer_sdk.pagination import BaseAPIPaginator
from singer_sdk.exceptions import ConfigurationError

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
            # First run (no bookmark yet): an explicit start_date is required.
            # No computed default on purpose — the look-back window is the
            # user's call from the start (a default like "12 months" would
            # silently trigger a very long first extraction).
            start_date_str = self.get_param("start_date")
            if not start_date_str:
                raise ConfigurationError(
                    f"Stream '{self.name}': no bookmark yet and no 'start_date' "
                    "set (neither globally nor on this metric). Provide a "
                    "'start_date' to define where the first extraction starts."
                )
            last_date_executes = date.fromisoformat(start_date_str[:10])
            self.logger.info(f"First run, start at: {last_date_executes}")

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


class InstagramMediaPaginator(BaseAPIPaginator):
    """Cursor paginator for the Meta `/media` edge.

    Follows the `paging.cursors.after` token as long as the API advertises a
    `paging.next` link, and stops once `media_max_pages` pages have been
    fetched (safety cap against an unbounded pagination loop).
    """

    def __init__(self, max_pages: int):
        super().__init__(None)
        self._max_pages = max_pages

    def get_next(self, response: requests.Response) -> Optional[str]:
        # `count` is the number of pages already fetched beyond the first;
        # once it reaches max_pages - 1 the cap is hit.
        if self.count >= self._max_pages - 1:
            return None
        paging = response.json().get("paging", {})
        # `next` is the authoritative "there is another page" signal.
        if "next" not in paging:
            return None
        return paging.get("cursors", {}).get("after")


class MediaStream(InstagramUserStream):
    """List of the account's Instagram media (posts).

    Daily snapshot of the current state of every post (cursor-paginated),
    not a time series: no since/until window. Each post is stored raw in
    `raw_data`, following the same ELT pattern as MetaRawInsightsStream.
    """

    primary_keys = ["ig_user_id", "id_post", "extraction_date"]
    replication_key = "extraction_date"
    is_sorted = False
    state_partitioning_keys = []
    # Each post is an element of the top-level "data" array.
    records_jsonpath = "$.data[*]"

    schema = th.PropertiesList(
        th.Property("ig_user_id", th.StringType, required=True),
        th.Property("id_post", th.StringType, required=True),
        th.Property("extraction_date", th.DateTimeType),
        th.Property(
            "raw_data",
            th.CustomType({"type": ["object", "array"]}),
            description="The raw JSON of the media object returned by the Meta API"
        ),
    ).to_dict()

    @property
    def path(self) -> str:
        """Media edge of the configured Instagram user."""
        return f"/{self.config.get('ig_user_id')}/media"

    def get_new_paginator(self) -> BaseAPIPaginator:
        """Cursor paginator capped at `media_max_pages`."""
        return InstagramMediaPaginator(self.get_param("media_max_pages", 100))

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> dict:
        """Build the `/media` query string.

        `media_fields` is required (no in-code default): the list of fields
        is a Meta-controlled vocabulary and must come from config. If
        `media_product_type` is omitted, the media-insights child stream
        will fail fast downstream rather than silently filter on missing data.
        """
        params: dict = {
            "access_token": self.config.get("access_token"),
            "fields": ",".join(self.get_param("media_fields")),
            "limit": self.get_param("media_limit", 100),
        }
        if next_page_token:
            params["after"] = next_page_token
        return params

    def get_records(self, context: Optional[dict]) -> Iterable[dict]:
        """Skip the run entirely if the snapshot was already taken today.

        `ig_media` is a once-a-day snapshot; re-running on the same day would
        duplicate the whole post list. The "already ran today" guard mirrors
        the legacy behaviour (and MetaRawInsightsStream.partitions).
        """
        state_bookmark = self.get_context_state(None).get("replication_key_value")
        if state_bookmark and date.fromisoformat(state_bookmark[:10]) >= date.today():
            self.logger.info("Already ran today. Done.")
            return
        # A single extraction timestamp for the whole run (all posts share it).
        self._extraction_date = datetime.now(timezone.utc).isoformat()
        yield from super().get_records(context)

    def post_process(self, row: dict, context: Optional[dict] = None) -> dict:
        """Wrap each raw post with its metadata, without transformation."""
        return {
            "ig_user_id": self.config.get("ig_user_id"),
            "id_post": row.get("id"),
            "extraction_date": self._extraction_date,
            "raw_data": row,
        }

    def get_child_context(self, record: dict, context: Optional[dict]) -> dict:
        """Pass each post's id and product type down to the insights child.

        `media_product_type` comes straight from the `/media` response (it is
        one of the requested `media_fields`); the child uses it to filter the
        metrics it may request. If it was not requested, the value is None and
        the child fails fast (cf. MediaInsightsStream.get_records).
        """
        return {
            "id_post": record["id_post"],
            "media_product_type": record["raw_data"].get("media_product_type"),
        }


class _SkipMedia(Exception):
    """Internal sentinel: skip the current post without failing the run."""


class MediaInsightsStream(InstagramUserStream):
    """Per-post insights for a single metric (child of MediaStream).

    One instance per metric/breakdown combination (cf. discover_streams).
    For every post emitted by the parent, requests
    `GET /{id_post}/insights?metric=<metric>` — but only when the metric is
    declared valid for the post's `media_product_type` in the
    `media_metric_compatibility` table (no API call otherwise).
    """

    parent_stream_type = MediaStream
    primary_keys = ["ig_user_id", "id_post", "metric_name", "breakdown_type", "extraction_date"]
    replication_key = "extraction_date"
    is_sorted = False
    state_partitioning_keys = []
    # The whole insights response is stored as a single raw record.
    records_jsonpath = "$"
    # Insights edge of the current post (id_post comes from the parent context).
    path = "/{id_post}/insights"

    schema = th.PropertiesList(
        th.Property("ig_user_id", th.StringType, required=True),
        th.Property("id_post", th.StringType, required=True),
        th.Property("metric_name", th.StringType),
        th.Property("breakdown_type", th.StringType),
        th.Property("extraction_date", th.DateTimeType),
        th.Property(
            "raw_data",
            th.CustomType({"type": ["object", "array"]}),
            description="The raw JSON insights response returned by the Meta API"
        ),
    ).to_dict()

    def __init__(
        self,
        tap: Any,
        name: str,
        metric_name: str,
        breakdown: Optional[str] = None,
        **kwargs
    ):
        super().__init__(tap=tap, name=name, **kwargs)
        self.metric_name = metric_name
        self.breakdown = breakdown

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> dict:
        """Build the per-post insights query string.

        No `metric_type` and no `period` here (unlike user insights): the
        media insights edge ignores them and always reports `lifetime`.
        """
        params: dict = {
            "access_token": self.config.get("access_token"),
            "metric": self.metric_name,
        }
        if self.breakdown:
            params["breakdown"] = self.breakdown
        return params

    def get_records(self, context: Optional[dict]) -> Iterable[dict]:
        """Filter by media_product_type, then extract; skip expected per-post errors."""
        post_type = (context or {}).get("media_product_type")
        if post_type is None:
            # media_product_type was not requested in media_fields: the child
            # has no basis to filter. Fail fast rather than silently skip.
            raise RuntimeError(
                "media_product_type is required in 'media_fields' for media "
                "insights to work (it determines which metrics are valid per "
                f"post). Post {context.get('id_post') if context else '?'} has none."
            )

        # Compatibility filtering: only call the API if this metric is declared
        # valid for the post's product type. Not an error — just not applicable.
        allowed = self.get_param("media_metric_compatibility", {}).get(post_type, [])
        if self.metric_name not in allowed:
            return

        if not getattr(self, "_extraction_date", None):
            self._extraction_date = datetime.now(timezone.utc).isoformat()

        try:
            yield from super().get_records(context)
        except _SkipMedia:
            self.logger.info(
                f"Skipping post {context.get('id_post')} for metric "
                f"'{self.metric_name}': media posted before business account "
                "conversion."
            )
            return

    def validate_response(self, response: requests.Response) -> None:
        """Distinguish a stale compatibility table (fatal) from expected noise.

        - "does not support the metric": the metric was sent because the
          compatibility table said it was valid, yet Meta rejected it. This is
          systemic (it recurs every run) and signals an outdated table, so it
          is raised loudly rather than swallowed (which would silently drop
          data on the target side).
        - "Media Posted Before Business Account Conversion": expected per-post
          condition, raised as an internal sentinel and skipped upstream.
        """
        if response.status_code == 400:
            text = response.text
            if "does not support the" in text:
                raise RuntimeError(
                    f"Metric '{self.metric_name}' was rejected by Meta for a "
                    "media object. Your 'media_metric_compatibility' table is "
                    "likely outdated (metric deprecated, renamed, or no longer "
                    f"valid for this media_product_type). Meta said: {text}"
                )
            if "Media Posted Before Business Account Conversion" in text:
                raise _SkipMedia()
        super().validate_response(response)

    def post_process(self, row: dict, context: Optional[dict] = None) -> dict:
        """Wrap the raw insights response with its metadata, without transformation."""
        return {
            "ig_user_id": self.config.get("ig_user_id"),
            "id_post": context["id_post"],
            "metric_name": self.metric_name,
            "breakdown_type": self.breakdown if self.breakdown else "none",
            "extraction_date": self._extraction_date,
            "raw_data": row,
        }
