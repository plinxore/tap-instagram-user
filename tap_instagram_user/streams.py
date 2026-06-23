"""Stream type classes for tap-instagram-user."""
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from dateutil.relativedelta import relativedelta
from singer_sdk import typing as th
from singer_sdk.exceptions import ConfigurationError
from singer_sdk.helpers.types import Context
from singer_sdk.pagination import BaseAPIPaginator

from tap_instagram_user.client import InstagramUserStream


class UserInsightsStream(InstagramUserStream):
    """Account-level (user) insights — one stream per metric/breakdown.

    Covers the IG User `insights` edge: GET /{ig_user_id}/insights
    https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights

    (The IG User node's own profile fields — followers_count, media_count,
    etc. at GET /{ig_user_id} — are NOT extracted by any stream yet.)
    """

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
            first_day_in_2_last_month = (
                last_date_executes - relativedelta(months=2)
            ).replace(day=1)
            last_day_in_2_last_month = (
                first_day_in_2_last_month + relativedelta(months=1) - timedelta(days=1)
            )

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
        breakdown: str | None = None,
        start_date: str | None = None,
        days_to_subtract: int | None = None,
        period: str | None = None,
        timeframe: str | None = None,
        metric_type: str | None = None,
        generate_dates_range: str | None = None,
        **kwargs: Any,
    ) -> None:
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

    def get_records(self, context: Context | None) -> Iterable[dict]:
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
            "breakdown_type": self.breakdown or "none",
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

    def __init__(self, max_pages: int) -> None:
        """Store the page cap; pagination starts with no cursor."""
        super().__init__(None)
        self._max_pages = max_pages

    def get_next(self, response: requests.Response) -> str | None:
        """Return the next `after` cursor, or None to stop."""
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
    `raw_data`, following the same ELT pattern as UserInsightsStream.

    This single stream covers TWO Meta doc pages at once, so there is no
    separate "IG Media node" stream to implement:

    1. IG User -> `media` edge (the endpoint we actually call):
       GET /{ig_user_id}/media?fields=...
       https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media

    2. IG Media node fields (id, timestamp, media_type, media_product_type,
       like_count, owner, ...): obtained here via *field expansion* on the
       edge above (the `media_fields` config = the `fields=` list), NOT via a
       per-post `GET /{ig_media_id}`. Same fields, one paginated call instead
       of N. So the IG Media "root" page is already covered by this stream:
       https://developers.facebook.com/docs/instagram-platform/reference/instagram-media

    Only the IG Media *insights* edge is not field-expandable (one call per
    post), hence the separate child MediaInsightsStream.
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

    # Media edge of the configured user. `{ig_user_id}` is resolved by the SDK
    # from config when building the URL (cf. RESTStream.get_url).
    path = "/{ig_user_id}/media"

    def get_new_paginator(self) -> BaseAPIPaginator:
        """Cursor paginator capped at `media_max_pages`."""
        return InstagramMediaPaginator(self.get_param("media_max_pages", 100))

    def get_url_params(
        self, context: Context | None, next_page_token: Any | None
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

    def get_records(self, context: Context | None) -> Iterable[dict]:
        """Skip the run entirely if the snapshot was already taken today.

        `ig_media` is a once-a-day snapshot; re-running on the same day would
        duplicate the whole post list. The "already ran today" guard mirrors
        the legacy behaviour (and UserInsightsStream.partitions).
        """
        state_bookmark = self.get_context_state(None).get("replication_key_value")
        if state_bookmark and date.fromisoformat(state_bookmark[:10]) >= date.today():
            self.logger.info("Already ran today. Done.")
            return
        # A single extraction timestamp for the whole run (all posts share it).
        self._extraction_date = datetime.now(timezone.utc).isoformat()
        yield from super().get_records(context)

    def post_process(self, row: dict, context: Context | None = None) -> dict:
        """Wrap each raw post with its metadata, without transformation."""
        return {
            "ig_user_id": self.config.get("ig_user_id"),
            "id_post": row.get("id"),
            "extraction_date": self._extraction_date,
            "raw_data": row,
        }

    def get_child_context(self, record: dict, context: Context | None) -> dict:
        """Pass each post's id, product type and media type down to the child.

        `media_product_type` and `media_type` come straight from the `/media`
        response (they are requested `media_fields`); the child uses them to
        filter the metrics it may request. A value not requested is None and
        the child fails fast when the matching filter is enabled
        (cf. MediaInsightsStream.get_records).
        """
        return {
            "id_post": record["id_post"],
            "media_product_type": record["raw_data"].get("media_product_type"),
            "media_type": record["raw_data"].get("media_type"),
        }


class _SkipMediaError(Exception):
    """Internal sentinel: skip the current post without failing the run."""


class MediaInsightsStream(InstagramUserStream):
    """Per-post insights for a single metric (child of MediaStream).

    Covers the IG Media `insights` edge: GET /{id_post}/insights
    https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights

    This edge is NOT field-expandable in bulk, so unlike the post fields
    (handled by MediaStream), it requires one call per post — hence this
    child stream.

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
        breakdown: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Bind the metric and (optional) breakdown this child stream extracts."""
        super().__init__(tap=tap, name=name, **kwargs)
        self.metric_name = metric_name
        self.breakdown = breakdown

    def get_url_params(
        self, context: Context | None, next_page_token: Any | None
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

    def get_records(self, context: Context | None) -> Iterable[dict]:
        """Filter by product type (and optionally media type), then extract."""
        ctx = context or {}
        post_type = ctx.get("media_product_type")
        if post_type is None:
            # media_product_type was not requested in media_fields: the child
            # has no basis to filter. Fail fast rather than silently skip.
            raise RuntimeError(
                "media_product_type is required in 'media_fields' for media "
                "insights to work (it determines which metrics are valid per "
                f"post). Post {ctx.get('id_post', '?')} has none."
            )

        # Compatibility filtering (intersection of two independent axes): only
        # call the API if this metric is declared valid for the post's product
        # type AND, when the optional media_type table is set, for its media
        # type. Not an error — just not applicable. (Meta's support is finer
        # than product_type alone: e.g. `views` only applies to VIDEO media.)
        by_product_type = self.get_param("media_metric_compatibility", {})
        if self.metric_name not in by_product_type.get(post_type, []):
            return

        by_media_type = self.get_param("media_metric_compatibility_by_media_type")
        if by_media_type is not None:
            media_type = ctx.get("media_type")
            if media_type is None:
                raise RuntimeError(
                    "media_type is required in 'media_fields' when "
                    "'media_metric_compatibility_by_media_type' is set. Post "
                    f"{ctx.get('id_post', '?')} has none."
                )
            if self.metric_name not in by_media_type.get(media_type, []):
                return

        if not getattr(self, "_extraction_date", None):
            self._extraction_date = datetime.now(timezone.utc).isoformat()

        # Kept for validate_response logging (no context there).
        self._current_id_post = ctx.get("id_post")
        try:
            yield from super().get_records(context)
        except _SkipMediaError:
            # validate_response already logged the reason.
            return

    def validate_response(self, response: requests.Response) -> None:
        """Map Meta 400s to fail-fast or skip, depending on the condition.

        - "does not support the metric": the metric was sent because the
          compatibility tables said it was valid, yet Meta rejected it. By
          default (`on_unsupported_metric=fail`) this is raised loudly — it is
          usually systemic (recurs every run) and signals an outdated table.
          With `on_unsupported_metric=skip` it is logged (WARNING) and the
          post/metric is skipped instead, for resilient unattended pipelines.
        - "Media Posted Before Business Account Conversion": expected per-post
          condition, always skipped (info log).
        """
        post = getattr(self, "_current_id_post", "?")
        if response.status_code == 400:
            text = response.text
            if "does not support the" in text:
                if self.get_param("on_unsupported_metric", "fail") == "skip":
                    self.logger.warning(
                        f"Skipping post {post} for metric '{self.metric_name}': "
                        "Meta does not support it for this media "
                        "(on_unsupported_metric=skip). Meta said: %s", text,
                    )
                    raise _SkipMediaError
                raise RuntimeError(
                    f"Metric '{self.metric_name}' was rejected by Meta for a "
                    "media object. Your compatibility tables are likely "
                    "outdated (metric deprecated, renamed, or not valid for "
                    "this media_product_type/media_type), or set "
                    "'on_unsupported_metric' to 'skip'. Meta said: " + text
                )
            if "Media Posted Before Business Account Conversion" in text:
                self.logger.info(
                    f"Skipping post {post} for metric '{self.metric_name}': "
                    "media posted before business account conversion."
                )
                raise _SkipMediaError
        super().validate_response(response)

    def post_process(self, row: dict, context: Context | None = None) -> dict:
        """Wrap the raw insights response with its metadata, without transformation."""
        return {
            "ig_user_id": self.config.get("ig_user_id"),
            "id_post": (context or {}).get("id_post"),
            "metric_name": self.metric_name,
            "breakdown_type": self.breakdown or "none",
            "extraction_date": self._extraction_date,
            "raw_data": row,
        }
